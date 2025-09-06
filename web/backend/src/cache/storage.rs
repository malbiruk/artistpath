use crate::models::CachedArtistMetadata;
use rustc_hash::FxHashMap;
use std::path::PathBuf;
use tokio::sync::RwLock;
use tokio::time::{Duration, interval};
use uuid::Uuid;

#[derive(Clone)]
pub struct CacheStorage {
    cache_file_path: PathBuf,
    cache: std::sync::Arc<RwLock<FxHashMap<Uuid, CachedArtistMetadata>>>,
    dirty: std::sync::Arc<RwLock<bool>>,
}

impl CacheStorage {
    pub fn new(cache_file_path: PathBuf) -> Self {
        Self {
            cache_file_path,
            cache: std::sync::Arc::new(RwLock::new(FxHashMap::default())),
            dirty: std::sync::Arc::new(RwLock::new(false)),
        }
    }

    pub async fn load_cache(&self) -> tokio::io::Result<()> {
        if !self.cache_file_path.exists() {
            println!("No existing cache file found, starting with empty cache");
            return Ok(());
        }

        println!("Loading metadata cache from {:?}...", self.cache_file_path);

        let file_contents = tokio::fs::read(&self.cache_file_path).await?;

        match bincode::deserialize::<FxHashMap<Uuid, CachedArtistMetadata>>(&file_contents) {
            Ok(loaded_cache) => {
                let mut cache = self.cache.write().await;
                *cache = loaded_cache;
                // println!("Loaded {} metadata entries from cache", cache.len());
                Ok(())
            }
            Err(e) => {
                println!("Failed to deserialize cache (will start fresh): {}", e);
                Ok(())
            }
        }
    }

    pub async fn get(&self, artist_id: &Uuid) -> Option<CachedArtistMetadata> {
        let cache = self.cache.read().await;
        cache.get(artist_id).cloned()
    }

    pub async fn insert(&self, artist_id: Uuid, metadata: CachedArtistMetadata) {
        {
            let mut cache = self.cache.write().await;
            cache.insert(artist_id, metadata);
        }

        {
            let mut dirty = self.dirty.write().await;
            *dirty = true;
        }

        // println!("Cached metadata for artist: {}", artist_id);
    }

    pub fn start_periodic_writes(&self) {
        let storage_clone = self.clone();
        tokio::spawn(async move {
            storage_clone.periodic_write_task().await;
        });
    }

    async fn periodic_write_task(&self) {
        let mut interval = interval(Duration::from_secs(30));

        loop {
            interval.tick().await;

            let is_dirty = {
                let dirty = self.dirty.read().await;
                *dirty
            };

            if is_dirty {
                if let Err(e) = self.write_cache_to_disk().await {
                    eprintln!("Failed to write cache to disk: {}", e);
                } else {
                    let mut dirty = self.dirty.write().await;
                    *dirty = false;
                }
            }
        }
    }

    async fn write_cache_to_disk(&self) -> tokio::io::Result<()> {
        let cache = self.cache.read().await;
        let serialized = bincode::serialize(&*cache)
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidData, e))?;

        // Write to temp file first, then atomic rename
        let temp_path = self.cache_file_path.with_extension("bin.tmp");
        tokio::fs::write(&temp_path, serialized).await?;
        tokio::fs::rename(&temp_path, &self.cache_file_path).await?;

        // println!("Wrote {} metadata entries to cache", cache.len());
        Ok(())
    }
}
