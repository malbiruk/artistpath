pub mod fetcher;
pub mod storage;
pub mod types;

use crate::cache::fetcher::ApiFetcher;
use crate::cache::storage::CacheStorage;
use crate::cache::types::{is_cache_valid, CacheKey};
use crate::itunes::ITunesClient;
use crate::lastfm::LastFmClient;
use crate::models::{LastFmArtistData, LastFmTrackData};
use rustc_hash::FxHashMap;
use std::path::PathBuf;
use uuid::Uuid;

#[derive(Clone)]
pub struct MetadataCache {
    storage: CacheStorage,
    fetcher: ApiFetcher,
}

impl MetadataCache {
    pub async fn new(lastfm_api_key: String) -> tokio::io::Result<Self> {
        let cache_file_path = PathBuf::from("../../data/artist_metadata.bin");

        // Ensure data directory exists
        if let Some(parent) = cache_file_path.parent() {
            tokio::fs::create_dir_all(parent).await?;
        }

        let storage = CacheStorage::new(cache_file_path);
        let fetcher = ApiFetcher::new(
            LastFmClient::new(lastfm_api_key),
            ITunesClient::new(),
        );

        // Load existing cache from binary file
        storage.load_cache().await?;

        // Start periodic write task
        storage.start_periodic_writes();

        Ok(Self { storage, fetcher })
    }

    pub async fn get_artist_metadata(
        &self,
        artist_id: Uuid,
        artist_name: &str,
        artist_url: &str,
    ) -> Result<Option<LastFmArtistData>, Box<dyn std::error::Error + Send + Sync>> {
        let key = CacheKey {
            artist_id,
            artist_name: artist_name.to_string(),
            artist_url: artist_url.to_string(),
        };

        // Check cache first
        if let Some(cached_data) = self.storage.get(&artist_id).await {
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

        // Cache miss or expired - fetch fresh data
        let (cached_data, result) = self.fetcher.fetch_artist_data(&key).await?;
        
        // Store the fetched data
        self.storage.insert(artist_id, cached_data).await;
        
        Ok(result)
    }

    pub async fn get_artist_tracks(
        &self,
        artist_id: Uuid,
        artist_name: &str,
    ) -> Result<Option<Vec<LastFmTrackData>>, Box<dyn std::error::Error + Send + Sync>> {
        let key = CacheKey {
            artist_id,
            artist_name: artist_name.to_string(),
            artist_url: format!("https://last.fm/music/{}", urlencoding::encode(artist_name)),
        };

        // Check cache first
        if let Some(cached_data) = self.storage.get(&artist_id).await {
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

        // Get existing previews to preserve them
        let existing_previews = self.storage.get(&artist_id).await
            .and_then(|cached| cached.tracks)
            .map(|tracks| {
                tracks
                    .iter()
                    .map(|t| (t.name.clone(), t.preview_url.clone()))
                    .collect::<FxHashMap<_, _>>()
            })
            .unwrap_or_default();

        // Cache miss or missing iTunes URLs - fetch with iTunes previews
        self.fetcher.fetch_tracks_data(&key, &existing_previews).await
    }
}

// Helper functions
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