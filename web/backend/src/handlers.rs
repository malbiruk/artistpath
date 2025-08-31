use crate::enhanced_pathfinding::find_enhanced_path_between_artists;
use crate::exploration::explore_artist_network_graph;
use crate::models::{
    ArtistDetailsResponse, EnhancedPathQuery, EnhancedPathResponse, ExploreQuery,
    GraphExploreResponse, HealthResponse, LastFmArtistData, LastFmTrackData, PathQuery,
    PathResponse, SearchQuery, SearchResponse, StatsResponse,
};
use crate::pathfinding::find_path_between_artists;
use crate::search::search_artists_in_state;
use crate::state::AppState;
use axum::{
    Json,
    extract::{Path, Query, State},
    http::StatusCode,
};
use std::sync::Arc;

pub async fn health_check() -> Json<HealthResponse> {
    Json(HealthResponse {
        status: "ok".to_string(),
        message: "Artistpath API is running".to_string(),
    })
}

pub async fn search_artists(
    State(state): State<Arc<AppState>>,
    Query(params): Query<SearchQuery>,
) -> Json<SearchResponse> {
    let query = params.q.trim();
    let (results, count) = search_artists_in_state(&state, query, params.limit);

    Json(SearchResponse {
        query: query.to_string(),
        results,
        count,
    })
}

pub async fn find_path(
    State(state): State<Arc<AppState>>,
    Query(params): Query<PathQuery>,
) -> Json<PathResponse> {
    let response = find_path_between_artists(
        params.from_id,
        params.to_id,
        params.algorithm,
        params.min_similarity,
        params.max_relations,
        &state,
    );

    Json(response)
}

pub async fn get_stats(State(state): State<Arc<AppState>>) -> Json<StatsResponse> {
    Json(StatsResponse {
        total_artists: state.artist_metadata.len(),
    })
}

pub async fn explore_artist(
    State(state): State<Arc<AppState>>,
    Query(params): Query<ExploreQuery>,
) -> Json<GraphExploreResponse> {
    let response = explore_artist_network_graph(
        params.artist_id,
        params.algorithm,
        params.budget,
        params.max_relations,
        params.min_similarity,
        &state,
    );

    Json(response)
}

pub async fn find_enhanced_path(
    State(state): State<Arc<AppState>>,
    Query(params): Query<EnhancedPathQuery>,
) -> Json<EnhancedPathResponse> {
    let response = find_enhanced_path_between_artists(
        params.from_id,
        params.to_id,
        params.algorithm,
        params.min_similarity,
        params.max_relations,
        params.budget,
        &state,
    );

    Json(response)
}

pub async fn get_artist_details(
    State(state): State<Arc<AppState>>,
    Path(artist_id): Path<uuid::Uuid>,
) -> Result<Json<ArtistDetailsResponse>, StatusCode> {
    // Get artist from our metadata
    let artist = match state.artist_metadata.get(&artist_id) {
        Some(artist) => artist,
        None => return Err(StatusCode::NOT_FOUND),
    };

    // Fetch Last.fm data concurrently
    let artist_name = &artist.name;
    let lastfm_info_fut = state.lastfm_client.get_artist_info(artist_name);
    let lastfm_tracks_fut = state.lastfm_client.get_top_tracks(artist_name, 5);

    type LastFmResult<T> = Result<T, Box<dyn std::error::Error + Send + Sync>>;
    let (lastfm_info, lastfm_tracks): (
        LastFmResult<crate::lastfm::LastFmArtist>,
        LastFmResult<Vec<crate::lastfm::LastFmTrack>>,
    ) = tokio::join!(lastfm_info_fut, lastfm_tracks_fut);

    // Process Last.fm artist info
    let lastfm_data = match lastfm_info {
        Ok(info) => {
            let image_url = info
                .image
                .iter()
                .find(|img| img.size == "large" || img.size == "medium")
                .map(|img| img.url.clone())
                .filter(|url| !url.is_empty());

            let tags = info
                .tags
                .map(|t| t.tag.into_iter().map(|tag| tag.name).collect())
                .unwrap_or_default();

            let (bio_summary, bio_full) = info
                .bio
                .map(|b| {
                    let clean_summary = b
                        .summary
                        .replace("&quot;", "\"")
                        .replace("Read more on Last.fm", "")
                        .replace("\\n", "\n")
                        .trim()
                        .to_string();
                    let clean_full = b
                        .content
                        .replace("&quot;", "\"")
                        .replace("Read more on Last.fm", "")
                        .replace("\\n", "\n")
                        .trim()
                        .to_string();
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
                })
                .unwrap_or((None, None));

            Some(LastFmArtistData {
                name: info.name,
                url: info.url,
                image_url,
                listeners: info.stats.as_ref().map(|s| s.listeners.clone()),
                plays: info.stats.as_ref().map(|s| s.playcount.clone()),
                tags,
                bio_summary,
                bio_full,
            })
        }
        Err(_) => None,
    };

    // Process Last.fm top tracks with iTunes previews (parallel fetching)
    let top_tracks = match lastfm_tracks {
        Ok(tracks) => {
            // Create futures for all iTunes searches in parallel
            let itunes_futures: Vec<_> = tracks
                .iter()
                .map(|track| {
                    let client = &state.itunes_client;
                    let artist = artist_name.to_string();
                    let track_name = track.name.clone();
                    async move {
                        client.search_track(&artist, &track_name).await
                    }
                })
                .collect();
            
            // Wait for all iTunes searches to complete
            let itunes_results = futures::future::join_all(itunes_futures).await;
            
            // Combine track data with iTunes preview URLs
            let track_data: Vec<LastFmTrackData> = tracks
                .into_iter()
                .zip(itunes_results.into_iter())
                .map(|(track, itunes_result)| {
                    let preview_url = match itunes_result {
                        Ok(Some(itunes_track)) => Some(itunes_track.preview_url),
                        _ => None,
                    };
                    
                    LastFmTrackData {
                        name: track.name,
                        url: track.url,
                        playcount: track.playcount,
                        listeners: track.listeners,
                        preview_url,
                    }
                })
                .collect();
            
            Some(track_data)
        }
        Err(_) => None,
    };

    let response = ArtistDetailsResponse {
        id: artist_id,
        name: artist.name.clone(),
        url: artist.url.clone(),
        lastfm_data,
        top_tracks,
    };

    Ok(Json(response))
}
