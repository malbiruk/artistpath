use crate::enhanced_pathfinding::find_enhanced_path_between_artists;
use crate::exploration::{explore_artist_network_graph, explore_artist_network_reverse_graph};
use crate::models::{
    ArtistDetailsResponse, EnhancedPathQuery, EnhancedPathResponse, ExploreQuery,
    GraphExploreResponse, HealthResponse, PathQuery, PathResponse, SearchQuery, SearchResponse,
    StatsResponse,
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
use uuid::Uuid;

pub async fn health_check() -> Json<HealthResponse> {
    Json(HealthResponse {
        status: "ok".to_string(),
        message: "Artistpath API is running".to_string(),
    })
}

pub async fn search_artists(
    State(state): State<Arc<AppState>>,
    Query(mut params): Query<SearchQuery>,
) -> Json<SearchResponse> {
    params.clamp_to_limits();
    let query = params.q.trim().to_string();
    let query_for_search = query.clone();
    let limit = params.limit;

    // Trigram intersection + substring check is CPU-bound; keep it off the
    // async runtime so health checks and other requests stay responsive.
    let (results, count) = tokio::task::spawn_blocking(move || {
        search_artists_in_state(&state, &query_for_search, limit)
    })
    .await
    .expect("search task panicked");

    Json(SearchResponse {
        query,
        results,
        count,
    })
}

pub async fn find_path(
    State(state): State<Arc<AppState>>,
    Query(mut params): Query<PathQuery>,
) -> Json<PathResponse> {
    params.clamp_to_limits();
    let response = tokio::task::spawn_blocking(move || {
        find_path_between_artists(
            params.from_id,
            params.to_id,
            params.algorithm,
            params.min_similarity,
            params.max_relations,
            &state,
        )
    })
    .await
    .expect("pathfinding task panicked");

    Json(response)
}

pub async fn get_stats(State(state): State<Arc<AppState>>) -> Json<StatsResponse> {
    Json(StatsResponse {
        total_artists: state.artist_metadata.len(),
    })
}

pub async fn explore_artist(
    State(state): State<Arc<AppState>>,
    Query(mut params): Query<ExploreQuery>,
) -> Json<GraphExploreResponse> {
    params.clamp_to_limits();
    let response = tokio::task::spawn_blocking(move || {
        explore_artist_network_graph(
            params.artist_id,
            params.algorithm,
            params.budget,
            params.max_relations,
            params.min_similarity,
            &state,
        )
    })
    .await
    .expect("exploration task panicked");

    Json(response)
}

pub async fn explore_artist_reverse(
    State(state): State<Arc<AppState>>,
    Query(mut params): Query<ExploreQuery>,
) -> Json<GraphExploreResponse> {
    params.clamp_to_limits();
    let response = tokio::task::spawn_blocking(move || {
        explore_artist_network_reverse_graph(
            params.artist_id,
            params.algorithm,
            params.budget,
            params.max_relations,
            params.min_similarity,
            &state,
        )
    })
    .await
    .expect("reverse exploration task panicked");

    Json(response)
}

pub async fn find_enhanced_path(
    State(state): State<Arc<AppState>>,
    Query(mut params): Query<EnhancedPathQuery>,
) -> Json<EnhancedPathResponse> {
    params.clamp_to_limits();
    let response = tokio::task::spawn_blocking(move || {
        find_enhanced_path_between_artists(
            params.from_id,
            params.to_id,
            params.algorithm,
            params.min_similarity,
            params.max_relations,
            params.budget,
            &state,
        )
    })
    .await
    .expect("enhanced pathfinding task panicked");

    Json(response)
}

pub async fn get_artist_details(
    State(state): State<Arc<AppState>>,
    Path(artist_id): Path<Uuid>,
) -> Result<Json<ArtistDetailsResponse>, StatusCode> {
    let artist = state
        .artist_metadata
        .get(&artist_id)
        .ok_or(StatusCode::NOT_FOUND)?;

    let lastfm_data = state
        .metadata_cache
        .get_artist_metadata(artist_id, &artist.name, &artist.url)
        .await
        .unwrap_or(None);

    let top_tracks = state
        .metadata_cache
        .get_artist_tracks(artist_id, &artist.name)
        .await
        .unwrap_or(None);

    let response = ArtistDetailsResponse {
        id: artist_id,
        name: artist.name.clone(),
        url: artist.url.clone(),
        lastfm_data,
        top_tracks,
    };

    Ok(Json(response))
}

pub async fn get_random_artist(
    State(state): State<Arc<AppState>>,
) -> Result<Json<serde_json::Value>, StatusCode> {
    use rand::Rng;

    if state.artist_ids.is_empty() {
        return Err(StatusCode::NOT_FOUND);
    }

    // O(1) lookup via Vec — the old code iterated the HashMap, which was
    // O(n) and degraded badly at 5M artists.
    let random_index = rand::rng().random_range(0..state.artist_ids.len());
    let id = state.artist_ids[random_index];
    let artist = state
        .artist_metadata
        .get(&id)
        .ok_or(StatusCode::INTERNAL_SERVER_ERROR)?;

    Ok(Json(serde_json::json!({
        "id": id,
        "name": artist.name,
        "url": artist.url
    })))
}
