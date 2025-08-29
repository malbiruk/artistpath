use crate::exploration::explore_artist_network_graph;
use crate::models::{
    ExploreQuery, GraphExploreResponse, HealthResponse,
    PathQuery, PathResponse, SearchQuery, SearchResponse, StatsResponse,
    EnhancedPathQuery, EnhancedPathResponse,
};
use crate::pathfinding::find_path_between_artists;
use crate::enhanced_pathfinding::find_enhanced_path_between_artists;
use crate::search::search_artists_in_state;
use crate::state::AppState;
use axum::{
    Json,
    extract::{Query, State},
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
