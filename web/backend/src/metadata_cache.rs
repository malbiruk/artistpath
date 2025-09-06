use crate::itunes::ITunesClient;
use crate::lastfm::LastFmClient;
use crate::models::{CachedArtistMetadata, LastFmArtistData, LastFmTrackData};
use rustc_hash::FxHashMap;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};
use tokio::fs::{File, OpenOptions};
use tokio::io::{AsyncBufReadExt, AsyncSeekExt, AsyncWriteExt, BufReader, SeekFrom};
use tokio::sync::RwLock;
use uuid::Uuid;

const CACHE_TTL_SECONDS: i64 = 90 * 24 * 60 * 60; // 90 days

pub struct MetadataCache {
    cache_file_path: PathBuf,
    index: RwLock<FxHashMap<Uuid, u64>>, // UUID -> file position
    lastfm: LastFmClient,
    itunes: ITunesClient,
}

impl MetadataCache {
    pub async fn new(lastfm_api_key: String) -> tokio::io::Result<Self> {
        let cache_file_path = PathBuf::from("../../data/artist_metadata.ndjson");

        // Ensure data directory exists
        if let Some(parent) = cache_file_path.parent() {
            tokio::fs::create_dir_all(parent).await?;
        }

        let cache = Self {
            cache_file_path,
            index: RwLock::new(FxHashMap::default()),
            lastfm: LastFmClient::new(lastfm_api_key),
            itunes: ITunesClient::new(),
        };

        // Build index from existing cache file
        cache.build_index().await?;

        Ok(cache)
    }

    async fn build_index(&self) -> tokio::io::Result<()> {
        if !self.cache_file_path.exists() {
            return Ok(());
        }

        let file = File::open(&self.cache_file_path).await?;
        let mut reader = BufReader::new(file);
        let mut line = String::new();
        let mut position = 0u64;
        let mut index = self.index.write().await;

        while reader.read_line(&mut line).await? > 0 {
            if let Ok(metadata) = serde_json::from_str::<CachedArtistMetadata>(&line) {
                if let Ok(uuid) = Uuid::parse_str(&metadata.id) {
                    index.insert(uuid, position);
                }
            }
            position += line.len() as u64;
            line.clear();
        }

        println!("Built cache index with {} entries", index.len());
        Ok(())
    }

    pub async fn get_artist_metadata(
        &self,
        artist_id: Uuid,
        artist_name: &str,
        artist_url: &str,
    ) -> Result<Option<LastFmArtistData>, Box<dyn std::error::Error + Send + Sync>> {
        // Check cache first
        if let Some(cached_data) = self.get_cached_if_valid(artist_id).await {
            if let Some(lastfm_data) = cached_data.lastfm {
                return Ok(Some(convert_cached_to_response(
                    &lastfm_data,
                    artist_name,
                    artist_url,
                )));
            }
        }

        // Cache miss - fetch fresh data
        self.fetch_and_cache_artist_data(artist_id, artist_name, artist_url)
            .await
    }

    pub async fn get_artist_tracks(
        &self,
        artist_id: Uuid,
        artist_name: &str,
    ) -> Result<Option<Vec<LastFmTrackData>>, Box<dyn std::error::Error + Send + Sync>> {
        // Check cache first
        if let Some(cached_data) = self.get_cached_if_valid(artist_id).await {
            if let Some(tracks) = cached_data.tracks {
                return Ok(Some(convert_cached_tracks_to_response(&tracks)));
            }
        }

        // Cache miss - fetch with iTunes previews
        self.fetch_and_cache_tracks_with_previews(artist_id, artist_name)
            .await
    }

    async fn get_cached_if_valid(&self, artist_id: Uuid) -> Option<CachedArtistMetadata> {
        let index = self.index.read().await;
        let position = *index.get(&artist_id)?;
        drop(index);

        // Read from file at specific position
        match self.read_from_position(position).await {
            Ok(Some(metadata)) if is_cache_valid(metadata.last_fetched) => Some(metadata),
            _ => None,
        }
    }

    async fn read_from_position(
        &self,
        position: u64,
    ) -> tokio::io::Result<Option<CachedArtistMetadata>> {
        let mut file = File::open(&self.cache_file_path).await?;
        file.seek(SeekFrom::Start(position)).await?;

        let mut reader = BufReader::new(file);
        let mut line = String::new();

        if reader.read_line(&mut line).await? > 0 {
            match serde_json::from_str::<CachedArtistMetadata>(&line) {
                Ok(metadata) => Ok(Some(metadata)),
                Err(_) => Ok(None),
            }
        } else {
            Ok(None)
        }
    }

    async fn fetch_and_cache_artist_data(
        &self,
        artist_id: Uuid,
        artist_name: &str,
        artist_url: &str,
    ) -> Result<Option<LastFmArtistData>, Box<dyn std::error::Error + Send + Sync>> {
        // Fetch Last.fm artist info
        let lastfm_artist = self.lastfm.get_artist_info(artist_name).await.ok();
        let lastfm_tracks = self.lastfm.get_top_tracks(artist_name, 5).await.ok();

        // Cache the result
        let cached = CachedArtistMetadata {
            id: artist_id.to_string(),
            name: artist_name.to_string(),
            url: artist_url.to_string(),
            last_fetched: current_timestamp(),
            lastfm: lastfm_artist.as_ref().map(convert_lastfm_to_cached),
            tracks: lastfm_tracks
                .as_ref()
                .map(|tracks| convert_lastfm_tracks_to_cached(tracks, &FxHashMap::default())),
        };

        self.store_to_cache(artist_id, &cached).await.ok();

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
            match self.get_cached_if_valid(artist_id).await {
                Some(cached) => cached
                    .tracks
                    .as_ref()
                    .map(|tracks| {
                        tracks
                            .iter()
                            .map(|t| (t.name.clone(), t.preview_url.clone()))
                            .collect::<FxHashMap<_, _>>()
                    })
                    .unwrap_or_default(),
                None => FxHashMap::default(),
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
        let existing = self.get_cached_if_valid(artist_id).await;
        let cached = CachedArtistMetadata {
            id: artist_id.to_string(),
            name: artist_name.to_string(),
            url: format!("https://last.fm/music/{}", urlencoding::encode(artist_name)),
            last_fetched: current_timestamp(),
            lastfm: existing.and_then(|e| e.lastfm), // Preserve existing lastfm data
            tracks: Some(tracks_with_previews.clone()),
        };

        self.store_to_cache(artist_id, &cached).await.ok();

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
                        println!("✓ Found iTunes preview: {} - {}", artist_name, track.name);
                    }
                    _ => {
                        preview_urls.push(None);
                    }
                }
            }
        }

        preview_urls
    }

    async fn store_to_cache(
        &self,
        artist_id: Uuid,
        metadata: &CachedArtistMetadata,
    ) -> tokio::io::Result<()> {
        // Serialize to JSON line
        let json_line = serde_json::to_string(metadata)?;

        // Append to cache file
        let mut file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.cache_file_path)
            .await?;

        let position = file.metadata().await?.len();
        file.write_all(json_line.as_bytes()).await?;
        file.write_all(b"\n").await?;
        file.flush().await?;

        // Update index
        let mut index = self.index.write().await;
        index.insert(artist_id, position);

        Ok(())
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
