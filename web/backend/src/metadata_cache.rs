use crate::itunes::ITunesClient;
use crate::lastfm::LastFmClient;
use crate::models::{CachedArtistMetadata, LastFmArtistData, LastFmTrackData};
use rustc_hash::FxHashMap;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};
use tokio::sync::RwLock;
use tokio::time::{Duration, interval};
use uuid::Uuid;

const CACHE_TTL_SECONDS: i64 = 90 * 24 * 60 * 60; // 90 days

#[derive(Clone)]
pub struct MetadataCache {
    cache_file_path: PathBuf,
    cache: std::sync::Arc<RwLock<FxHashMap<Uuid, CachedArtistMetadata>>>, // UUID -> metadata
    lastfm: LastFmClient,
    itunes: ITunesClient,
    dirty: std::sync::Arc<RwLock<bool>>, // Track if cache needs to be written
}

impl MetadataCache {
    pub async fn new(lastfm_api_key: String) -> tokio::io::Result<Self> {
        let cache_file_path = PathBuf::from("../../data/artist_metadata.bin");

        // Ensure data directory exists
        if let Some(parent) = cache_file_path.parent() {
            tokio::fs::create_dir_all(parent).await?;
        }

        let cache = Self {
            cache_file_path: cache_file_path.clone(),
            cache: std::sync::Arc::new(RwLock::new(FxHashMap::default())),
            lastfm: LastFmClient::new(lastfm_api_key),
            itunes: ITunesClient::new(),
            dirty: std::sync::Arc::new(RwLock::new(false)),
        };

        // Load existing cache from binary file
        cache.load_cache().await?;

        // Start periodic write task
        let cache_clone = cache.clone();
        tokio::spawn(async move {
            cache_clone.periodic_write_task().await;
        });

        Ok(cache)
    }

    async fn load_cache(&self) -> tokio::io::Result<()> {
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

    async fn periodic_write_task(&self) {
        let mut interval = interval(Duration::from_secs(30)); // Write every 30 seconds if dirty

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

    pub async fn get_artist_metadata(
        &self,
        artist_id: Uuid,
        artist_name: &str,
        artist_url: &str,
    ) -> Result<Option<LastFmArtistData>, Box<dyn std::error::Error + Send + Sync>> {
        // Check cache first
        let cache = self.cache.read().await;
        if let Some(cached_data) = cache.get(&artist_id) {
            if is_cache_valid(cached_data.last_fetched) {
                if let Some(ref lastfm_data) = cached_data.lastfm {
                    return Ok(Some(convert_cached_to_response(
                        lastfm_data,
                        artist_name,
                        artist_url,
                    )));
                }
            }
        }
        drop(cache);

        // Cache miss or expired - fetch fresh data
        self.fetch_and_cache_artist_data(artist_id, artist_name, artist_url)
            .await
    }

    pub async fn get_artist_tracks(
        &self,
        artist_id: Uuid,
        artist_name: &str,
    ) -> Result<Option<Vec<LastFmTrackData>>, Box<dyn std::error::Error + Send + Sync>> {
        // Check cache first
        let cache = self.cache.read().await;
        if let Some(cached_data) = cache.get(&artist_id) {
            if is_cache_valid(cached_data.last_fetched) {
                if let Some(ref tracks) = cached_data.tracks {
                    // Check if tracks have iTunes preview URLs
                    let has_preview_urls = tracks.iter().any(|track| track.preview_url.is_some());

                    if has_preview_urls {
                        // Cache has iTunes URLs, return it
                        return Ok(Some(convert_cached_tracks_to_response(tracks)));
                    }
                    // Cache exists but no iTunes URLs - fall through to fetch them
                }
            }
        }
        drop(cache);

        // Cache miss or missing iTunes URLs - fetch with iTunes previews
        self.fetch_and_cache_tracks_with_previews(artist_id, artist_name)
            .await
    }

    async fn fetch_and_cache_artist_data(
        &self,
        artist_id: Uuid,
        artist_name: &str,
        artist_url: &str,
    ) -> Result<Option<LastFmArtistData>, Box<dyn std::error::Error + Send + Sync>> {
        // Fetch Last.fm artist info and top tracks
        let lastfm_artist = self.lastfm.get_artist_info(artist_name).await.ok();
        let lastfm_tracks = self.lastfm.get_top_tracks(artist_name, 5).await.ok();

        // Fetch iTunes preview URLs for tracks
        let preview_urls = if let Some(ref tracks) = lastfm_tracks {
            self.fetch_missing_itunes_previews(artist_name, tracks, &FxHashMap::default())
                .await
        } else {
            Vec::new()
        };

        let preview_map: FxHashMap<String, Option<String>> = lastfm_tracks
            .as_ref()
            .map(|tracks| {
                tracks
                    .iter()
                    .zip(preview_urls.iter())
                    .map(|(track, url)| (track.name.clone(), url.clone()))
                    .collect()
            })
            .unwrap_or_default();

        // Cache the result WITH iTunes URLs
        let cached = CachedArtistMetadata {
            id: artist_id.to_string(),
            name: artist_name.to_string(),
            url: artist_url.to_string(),
            last_fetched: current_timestamp(),
            lastfm: lastfm_artist.as_ref().map(convert_lastfm_to_cached),
            tracks: lastfm_tracks
                .as_ref()
                .map(|tracks| convert_lastfm_tracks_to_cached(tracks, &preview_map)),
        };

        self.store_to_cache(artist_id, cached).await;

        // Convert and return
        Ok(lastfm_artist
            .map(|artist| convert_lastfm_to_response_data(&artist, artist_name, artist_url)))
    }

    async fn fetch_and_cache_tracks_with_previews(
        &self,
        artist_id: Uuid,
        artist_name: &str,
    ) -> Result<Option<Vec<LastFmTrackData>>, Box<dyn std::error::Error + Send + Sync>> {
        // Get existing cached data to preserve iTunes URLs
        let existing_previews = {
            let cache = self.cache.read().await;
            match cache.get(&artist_id) {
                Some(cached) if is_cache_valid(cached.last_fetched) => cached
                    .tracks
                    .as_ref()
                    .map(|tracks| {
                        tracks
                            .iter()
                            .map(|t| (t.name.clone(), t.preview_url.clone()))
                            .collect::<FxHashMap<_, _>>()
                    })
                    .unwrap_or_default(),
                _ => FxHashMap::default(),
            }
        };

        // Fetch fresh Last.fm tracks
        let lastfm_tracks = self.lastfm.get_top_tracks(artist_name, 5).await?;

        // Fetch iTunes previews for tracks that don't have them yet
        let preview_urls = self
            .fetch_missing_itunes_previews(artist_name, &lastfm_tracks, &existing_previews)
            .await;

        // Combine Last.fm tracks with preview URLs
        let tracks_with_previews = lastfm_tracks
            .iter()
            .enumerate()
            .map(|(i, track)| crate::models::CachedTrackData {
                name: track.name.clone(),
                url: track.url.clone(),
                playcount: track.playcount.clone(),
                listeners: track.listeners.clone(),
                preview_url: preview_urls[i].clone(),
            })
            .collect::<Vec<_>>();

        // Update cache - merge with existing data
        let existing_lastfm = {
            let cache = self.cache.read().await;
            cache
                .get(&artist_id)
                .and_then(|cached| cached.lastfm.clone())
        };

        let cached = CachedArtistMetadata {
            id: artist_id.to_string(),
            name: artist_name.to_string(),
            url: format!("https://last.fm/music/{}", urlencoding::encode(artist_name)),
            last_fetched: current_timestamp(),
            lastfm: existing_lastfm, // Preserve existing lastfm data
            tracks: Some(tracks_with_previews.clone()),
        };

        self.store_to_cache(artist_id, cached).await;

        Ok(Some(convert_cached_tracks_to_response(
            &tracks_with_previews,
        )))
    }

    async fn fetch_missing_itunes_previews(
        &self,
        artist_name: &str,
        tracks: &[crate::lastfm::LastFmTrack],
        existing_previews: &FxHashMap<String, Option<String>>,
    ) -> Vec<Option<String>> {
        // Build list of preview URLs, fetching missing ones
        let mut preview_urls = Vec::new();

        for track in tracks {
            // Use existing preview if we have it
            if let Some(existing) = existing_previews.get(&track.name) {
                preview_urls.push(existing.clone());
            } else {
                // Need to fetch from iTunes
                match self.itunes.search_track(artist_name, &track.name).await {
                    Ok(Some(itunes_track)) => {
                        preview_urls.push(Some(itunes_track.preview_url));
                    }
                    _ => {
                        preview_urls.push(None);
                    }
                }
            }
        }

        preview_urls
    }

    async fn store_to_cache(&self, artist_id: Uuid, metadata: CachedArtistMetadata) {
        // Update in-memory cache
        {
            let mut cache = self.cache.write().await;
            cache.insert(artist_id, metadata);
        }

        // Mark as dirty for periodic write
        {
            let mut dirty = self.dirty.write().await;
            *dirty = true;
        }
    }
}

fn is_cache_valid(last_fetched: i64) -> bool {
    let current_time = current_timestamp();
    (current_time - last_fetched) < CACHE_TTL_SECONDS
}

fn current_timestamp() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs() as i64
}

fn convert_lastfm_to_cached(
    artist: &crate::lastfm::LastFmArtist,
) -> crate::models::CachedLastFmData {
    let image_url = artist
        .image
        .iter()
        .find(|img| img.size == "large" || img.size == "medium")
        .map(|img| img.url.clone())
        .filter(|url| !url.is_empty());

    let tags = artist
        .tags
        .as_ref()
        .map(|tags| tags.tag.iter().map(|tag| tag.name.clone()).collect())
        .unwrap_or_default();

    crate::models::CachedLastFmData {
        url: Some(artist.url.clone()),
        image_url,
        listeners: artist.stats.as_ref().map(|s| s.listeners.clone()),
        playcount: artist.stats.as_ref().map(|s| s.playcount.clone()),
        tags,
        bio_summary: artist
            .bio
            .as_ref()
            .map(|bio| {
                bio.summary
                    .replace("Read more on Last.fm", "")
                    .trim()
                    .to_string()
            })
            .filter(|s| !s.is_empty()),
        bio_full: artist
            .bio
            .as_ref()
            .map(|bio| {
                bio.content
                    .replace("Read more on Last.fm", "")
                    .trim()
                    .to_string()
            })
            .filter(|s| !s.is_empty()),
    }
}

fn convert_lastfm_tracks_to_cached(
    tracks: &[crate::lastfm::LastFmTrack],
    preview_urls: &FxHashMap<String, Option<String>>,
) -> Vec<crate::models::CachedTrackData> {
    tracks
        .iter()
        .map(|track| crate::models::CachedTrackData {
            name: track.name.clone(),
            url: track.url.clone(),
            playcount: track.playcount.clone(),
            listeners: track.listeners.clone(),
            preview_url: preview_urls.get(&track.name).cloned().unwrap_or(None),
        })
        .collect()
}

fn convert_cached_to_response(
    cached: &crate::models::CachedLastFmData,
    artist_name: &str,
    artist_url: &str,
) -> LastFmArtistData {
    LastFmArtistData {
        name: artist_name.to_string(),
        url: artist_url.to_string(),
        image_url: cached.image_url.clone(),
        listeners: cached.listeners.clone(),
        plays: cached.playcount.clone(),
        tags: cached.tags.clone(),
        bio_summary: cached.bio_summary.clone(),
        bio_full: cached.bio_full.clone(),
    }
}

fn convert_lastfm_to_response_data(
    artist: &crate::lastfm::LastFmArtist,
    artist_name: &str,
    artist_url: &str,
) -> LastFmArtistData {
    // First convert to cached format, then to response (DRY principle)
    let cached = convert_lastfm_to_cached(artist);
    convert_cached_to_response(&cached, artist_name, artist_url)
}

fn convert_cached_tracks_to_response(
    cached: &[crate::models::CachedTrackData],
) -> Vec<LastFmTrackData> {
    cached
        .iter()
        .map(|track| LastFmTrackData {
            name: track.name.clone(),
            url: track.url.clone(),
            playcount: track.playcount.clone(),
            listeners: track.listeners.clone(),
            preview_url: track.preview_url.clone(),
        })
        .collect()
}
