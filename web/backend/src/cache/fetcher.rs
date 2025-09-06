use crate::cache::types::{CacheKey, current_timestamp};
use crate::itunes::ITunesClient;
use crate::lastfm::LastFmClient;
use crate::models::{CachedArtistMetadata, LastFmArtistData, LastFmTrackData};
use rustc_hash::FxHashMap;

#[derive(Clone)]
pub struct ApiFetcher {
    lastfm: LastFmClient,
    itunes: ITunesClient,
}

impl ApiFetcher {
    pub fn new(lastfm: LastFmClient, itunes: ITunesClient) -> Self {
        Self { lastfm, itunes }
    }

    pub async fn fetch_artist_data(
        &self,
        key: &CacheKey,
    ) -> Result<
        (CachedArtistMetadata, Option<LastFmArtistData>),
        Box<dyn std::error::Error + Send + Sync>,
    > {
        // println!("Fetching fresh artist data for: {}", key.artist_name);

        // Fetch Last.fm artist info and top tracks
        let lastfm_artist = self.lastfm.get_artist_info(&key.artist_name).await.ok();
        let lastfm_tracks = self.lastfm.get_top_tracks(&key.artist_name, 5).await.ok();

        // Fetch iTunes preview URLs for tracks
        let preview_urls = if let Some(ref tracks) = lastfm_tracks {
            self.fetch_itunes_previews(&key.artist_name, tracks).await
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

        // Create cached metadata
        let cached = CachedArtistMetadata {
            id: key.artist_id.to_string(),
            name: key.artist_name.clone(),
            url: key.artist_url.clone(),
            last_fetched: current_timestamp(),
            lastfm: lastfm_artist.as_ref().map(convert_lastfm_to_cached),
            tracks: lastfm_tracks
                .as_ref()
                .map(|tracks| convert_lastfm_tracks_to_cached(tracks, &preview_map)),
        };

        // Return both cached data and response data
        let response_data = lastfm_artist.map(|artist| {
            convert_lastfm_to_response_data(&artist, &key.artist_name, &key.artist_url)
        });

        Ok((cached, response_data))
    }

    pub async fn fetch_tracks_data(
        &self,
        key: &CacheKey,
        existing_previews: &FxHashMap<String, Option<String>>,
    ) -> Result<Option<Vec<LastFmTrackData>>, Box<dyn std::error::Error + Send + Sync>> {
        // println!("Fetching fresh track data for: {}", key.artist_name);

        // Fetch fresh Last.fm tracks
        let lastfm_tracks = self.lastfm.get_top_tracks(&key.artist_name, 5).await?;

        // Fetch iTunes previews for tracks that don't have them yet
        let preview_urls = self
            .fetch_missing_itunes_previews(&key.artist_name, &lastfm_tracks, existing_previews)
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

        Ok(Some(convert_cached_tracks_to_response(
            &tracks_with_previews,
        )))
    }

    async fn fetch_itunes_previews(
        &self,
        artist_name: &str,
        tracks: &[crate::lastfm::LastFmTrack],
    ) -> Vec<Option<String>> {
        let mut preview_urls = Vec::new();

        for track in tracks {
            match self.itunes.search_track(artist_name, &track.name).await {
                Ok(Some(itunes_track)) => {
                    preview_urls.push(Some(itunes_track.preview_url));
                }
                _ => {
                    preview_urls.push(None);
                }
            }
        }

        preview_urls
    }

    async fn fetch_missing_itunes_previews(
        &self,
        artist_name: &str,
        tracks: &[crate::lastfm::LastFmTrack],
        existing_previews: &FxHashMap<String, Option<String>>,
    ) -> Vec<Option<String>> {
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
}

// Helper functions for data conversion
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
