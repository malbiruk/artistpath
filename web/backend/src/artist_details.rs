use crate::models::{
    ArtistDetailsResponse, CachedArtistMetadata, CachedLastFmData, CachedTrackData,
    LastFmArtistData, LastFmTrackData,
};
use crate::state::AppState;
use std::sync::Arc;
use uuid::Uuid;

pub fn build_response_from_cache(
    artist_id: Uuid,
    artist_name: String,
    artist_url: String,
    cached: &CachedArtistMetadata,
) -> ArtistDetailsResponse {
    let lastfm_data = cached
        .lastfm
        .as_ref()
        .map(|data| convert_cached_lastfm_data(data, &cached.name, &cached.url));
    let top_tracks = cached
        .tracks
        .as_ref()
        .map(|tracks| convert_cached_tracks(tracks));

    ArtistDetailsResponse {
        id: artist_id,
        name: artist_name,
        url: artist_url,
        lastfm_data,
        top_tracks,
    }
}

fn convert_cached_lastfm_data(
    data: &CachedLastFmData,
    artist_name: &str,
    fallback_url: &str,
) -> LastFmArtistData {
    LastFmArtistData {
        name: artist_name.to_string(),
        url: data.url.clone().unwrap_or_else(|| fallback_url.to_string()),
        image_url: data.image_url.clone(),
        listeners: data.listeners.clone(),
        plays: data.playcount.clone(),
        tags: data.tags.clone(),
        bio_summary: data.bio_summary.clone(),
        bio_full: data.bio_full.clone(),
    }
}

fn convert_cached_tracks(tracks: &[CachedTrackData]) -> Vec<LastFmTrackData> {
    tracks
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

fn extract_image_url(images: &[crate::lastfm::LastFmImage]) -> Option<String> {
    images
        .iter()
        .find(|img| img.size == "large" || img.size == "medium")
        .map(|img| img.url.clone())
        .filter(|url| !url.is_empty())
}

fn extract_tags(tags_wrapper: Option<crate::lastfm::LastFmTags>) -> Vec<String> {
    tags_wrapper
        .map(|t| t.tag.into_iter().map(|tag| tag.name).collect())
        .unwrap_or_default()
}

fn clean_bio_text(text: &str) -> String {
    text.replace("&quot;", "\"")
        .replace("Read more on Last.fm", "")
        .replace("\\n", "\n")
        .trim()
        .to_string()
}

fn process_bio(bio: crate::lastfm::LastFmBio) -> (Option<String>, Option<String>) {
    let clean_summary = clean_bio_text(&bio.summary);
    let clean_full = clean_bio_text(&bio.content);

    (
        if clean_summary.is_empty() {
            None
        } else {
            Some(clean_summary)
        },
        if clean_full.is_empty() {
            None
        } else {
            Some(clean_full)
        },
    )
}

fn convert_lastfm_artist_to_data(info: crate::lastfm::LastFmArtist) -> LastFmArtistData {
    let image_url = extract_image_url(&info.image);
    let tags = extract_tags(info.tags);
    let (bio_summary, bio_full) = info.bio.map(process_bio).unwrap_or((None, None));

    LastFmArtistData {
        name: info.name,
        url: info.url,
        image_url,
        listeners: info.stats.as_ref().map(|s| s.listeners.clone()),
        plays: info.stats.as_ref().map(|s| s.playcount.clone()),
        tags,
        bio_summary,
        bio_full,
    }
}

async fn fetch_itunes_previews(
    state: &Arc<AppState>,
    artist_name: &str,
    tracks: &[crate::lastfm::LastFmTrack],
) -> Vec<Option<String>> {
    let itunes_futures: Vec<_> = tracks
        .iter()
        .map(|track| {
            let client = &state.itunes_client;
            let artist = artist_name.to_string();
            let track_name = track.name.clone();
            async move { client.search_track(&artist, &track_name).await }
        })
        .collect();

    let itunes_results = futures::future::join_all(itunes_futures).await;

    itunes_results
        .into_iter()
        .map(|result| match result {
            Ok(Some(itunes_track)) => Some(itunes_track.preview_url),
            _ => None,
        })
        .collect()
}

fn combine_tracks_with_previews(
    tracks: Vec<crate::lastfm::LastFmTrack>,
    preview_urls: Vec<Option<String>>,
) -> Vec<LastFmTrackData> {
    tracks
        .into_iter()
        .zip(preview_urls)
        .map(|(track, preview_url)| LastFmTrackData {
            name: track.name,
            url: track.url,
            playcount: track.playcount,
            listeners: track.listeners,
            preview_url,
        })
        .collect()
}

pub async fn fetch_live_artist_data(
    state: &Arc<AppState>,
    artist_name: &str,
) -> (Option<LastFmArtistData>, Option<Vec<LastFmTrackData>>) {
    let lastfm_info_fut = state.lastfm_client.get_artist_info(artist_name);
    let lastfm_tracks_fut = state.lastfm_client.get_top_tracks(artist_name, 5);

    type LastFmResult<T> = Result<T, Box<dyn std::error::Error + Send + Sync>>;
    let (lastfm_info, lastfm_tracks): (
        LastFmResult<crate::lastfm::LastFmArtist>,
        LastFmResult<Vec<crate::lastfm::LastFmTrack>>,
    ) = tokio::join!(lastfm_info_fut, lastfm_tracks_fut);

    let lastfm_data = lastfm_info.ok().map(convert_lastfm_artist_to_data);

    let top_tracks = match lastfm_tracks {
        Ok(tracks) => {
            let preview_urls = fetch_itunes_previews(state, artist_name, &tracks).await;
            Some(combine_tracks_with_previews(tracks, preview_urls))
        }
        Err(_) => None,
    };

    (lastfm_data, top_tracks)
}
