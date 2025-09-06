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

pub async fn explore_artist_reverse(
    State(state): State<Arc<AppState>>,
    Query(params): Query<ExploreQuery>,
) -> Json<GraphExploreResponse> {
    let response = explore_artist_network_reverse_graph(
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
    Path(artist_id): Path<Uuid>,
) -> Result<Json<ArtistDetailsResponse>, StatusCode> {
    let artist = state
        .artist_metadata
        .get(&artist_id)
        .ok_or(StatusCode::NOT_FOUND)?;

    // Use the new metadata cache
    let lastfm_data = state.metadata_cache
        .get_artist_metadata(artist_id, &artist.name, &artist.url)
        .await
        .unwrap_or(None);
    
    let top_tracks = state.metadata_cache
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

    // Get a random artist from the metadata collection
    let artist_count = state.artist_metadata.len();
    if artist_count == 0 {
        return Err(StatusCode::NOT_FOUND);
    }

    let random_index = rand::rng().random_range(0..artist_count);

    // Get the random artist (since HashMap doesn't have direct indexing)
    if let Some((id, artist)) = state.artist_metadata.iter().nth(random_index) {
        Ok(Json(serde_json::json!({
            "id": id,
            "name": artist.name,
            "url": artist.url
        })))
    } else {
        Err(StatusCode::INTERNAL_SERVER_ERROR)
    }
}
