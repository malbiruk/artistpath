use crate::models::{
    ArtistSearchResult, ExploreArtist, ExploreQuery, ExploreResponse, HealthResponse, PathArtist,
    PathQuery, PathResponse, SearchQuery, SearchResponse, SearchStats, StatsResponse,
};
use crate::state::AppState;
use artistpath_core::string_normalization::clean_str;
use artistpath_core::{
    PathfindingConfig, bfs_find_path, dijkstra_find_path, get_artist_connections,
};
use axum::{
    Json,
    extract::{Query, State},
};
use rustc_hash::{FxHashMap, FxHashSet};
use std::sync::Arc;
use std::time::Instant;
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

    if query.is_empty() {
        return Json(SearchResponse {
            query: query.to_string(),
            results: vec![],
            count: 0,
        });
    }

    let normalized_query = clean_str(query);

    let mut results: Vec<ArtistSearchResult> = state
        .name_lookup
        .iter()
        .filter(|(normalized_name, _)| normalized_name.contains(&normalized_query))
        .filter_map(|(_, artist_id)| {
            state
                .artist_metadata
                .get(artist_id)
                .map(|artist| ArtistSearchResult {
                    id: artist.id,
                    name: artist.name.clone(),
                    url: artist.url.clone(),
                })
        })
        .collect();

    results.sort_by(|a, b| {
        let a_normalized = clean_str(&a.name);
        let b_normalized = clean_str(&b.name);

        let a_starts = a_normalized.starts_with(&normalized_query);
        let b_starts = b_normalized.starts_with(&normalized_query);

        match (a_starts, b_starts) {
            (true, false) => std::cmp::Ordering::Less,
            (false, true) => std::cmp::Ordering::Greater,
            _ => a.name.len().cmp(&b.name.len()),
        }
    });

    results.truncate(params.limit);
    let count = results.len();

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
    let config = PathfindingConfig::new(
        params.min_similarity,
        params.max_relations,
        params.algorithm == "dijkstra",
    );

    let start_time = Instant::now();

    let (path_result, artists_visited, _duration) = if params.algorithm == "dijkstra" {
        dijkstra_find_path(
            params.from_id,
            params.to_id,
            std::path::Path::new("../../data/graph.bin"),
            &state.graph_index,
            &config,
        )
    } else {
        bfs_find_path(
            params.from_id,
            params.to_id,
            std::path::Path::new("../../data/graph.bin"),
            &state.graph_index,
            &config,
        )
    };

    let duration_ms = start_time.elapsed().as_millis() as u64;

    let path = path_result.map(|path_data| {
        path_data
            .into_iter()
            .enumerate()
            .map(|(index, (artist_id, similarity))| {
                let artist = &state.artist_metadata[&artist_id];
                PathArtist {
                    id: artist_id,
                    name: artist.name.clone(),
                    url: artist.url.clone(),
                    similarity: if index == 0 { None } else { Some(similarity) },
                }
            })
            .collect()
    });

    let artist_count = path.as_ref().map_or(0, |p: &Vec<PathArtist>| p.len());
    let step_count = if artist_count > 0 {
        artist_count - 1
    } else {
        0
    };

    Json(PathResponse {
        path,
        artist_count,
        step_count,
        algorithm: params.algorithm,
        search_stats: SearchStats {
            artists_visited,
            duration_ms,
        },
    })
}

pub async fn get_stats(State(state): State<Arc<AppState>>) -> Json<StatsResponse> {
    Json(StatsResponse {
        total_artists: state.artist_metadata.len(),
    })
}

pub async fn explore_artist(
    State(state): State<Arc<AppState>>,
    Query(params): Query<ExploreQuery>,
) -> Json<ExploreResponse> {
    let start_time = Instant::now();

    let center_artist = match state.artist_metadata.get(&params.artist_id) {
        Some(artist) => PathArtist {
            id: artist.id,
            name: artist.name.clone(),
            url: artist.url.clone(),
            similarity: None,
        },
        None => {
            return Json(ExploreResponse {
                center_artist: PathArtist {
                    id: params.artist_id,
                    name: "Unknown Artist".to_string(),
                    url: "".to_string(),
                    similarity: None,
                },
                related_artists: vec![],
                total_found: 0,
                search_stats: SearchStats {
                    artists_visited: 0,
                    duration_ms: start_time.elapsed().as_millis() as u64,
                },
            });
        }
    };

    let config = PathfindingConfig::new(params.min_similarity, params.max_relations, false);

    // Connection cache to avoid repeated disk reads
    let mut connection_cache: FxHashMap<Uuid, Vec<(Uuid, f32)>> = FxHashMap::default();
    let mut visited = FxHashSet::default();
    let mut total_artists_visited = 0;

    visited.insert(params.artist_id);

    // Cached connection getter
    let mut get_cached_connections = |artist_id: Uuid| -> Vec<(Uuid, f32)> {
        if let Some(cached) = connection_cache.get(&artist_id) {
            cached.clone()
        } else {
            let connections =
                get_artist_connections(artist_id, &state.graph_mmap, &state.graph_index, &config);
            total_artists_visited += 1;
            connection_cache.insert(artist_id, connections.clone());
            connections
        }
    };

    // Build artists recursively with proper budget distribution
    fn build_artists_tree(
        parent_artists: &[(Uuid, f32)],
        get_connections: &mut dyn FnMut(Uuid) -> Vec<(Uuid, f32)>,
        state: &AppState,
        visited: &mut FxHashSet<Uuid>,
        budget_remaining: &mut usize,
        depth: usize,
    ) -> Vec<ExploreArtist> {
        if *budget_remaining == 0 || depth >= 3 || parent_artists.is_empty() {
            return Vec::new();
        }

        let mut result = Vec::new();
        
        for &(parent_id, parent_similarity) in parent_artists {
            if *budget_remaining == 0 {
                break;
            }

            let connections = get_connections(parent_id);
            let mut children_for_next_level = Vec::new();

            // Take connections up to remaining budget
            for (connected_id, child_similarity) in connections {
                if *budget_remaining == 0 {
                    break;
                }

                if !visited.contains(&connected_id) {
                    visited.insert(connected_id);
                    
                    if state.artist_metadata.get(&connected_id).is_some() {
                        children_for_next_level.push((connected_id, child_similarity));
                        *budget_remaining -= 1;
                    }
                }
            }

            // Recursively build children
            let nested_children = if !children_for_next_level.is_empty() && *budget_remaining > 0 {
                build_artists_tree(
                    &children_for_next_level,
                    get_connections,
                    state,
                    visited,
                    budget_remaining,
                    depth + 1,
                )
            } else {
                Vec::new()
            };

            // Build the artist with its nested children
            if let Some(artist) = state.artist_metadata.get(&parent_id) {
                result.push(ExploreArtist {
                    id: parent_id,
                    name: artist.name.clone(),
                    url: artist.url.clone(),
                    similarity: parent_similarity,
                    related_artists: nested_children,
                });
            }
        }

        result
    }

    // Get initial connections from root artist  
    let root_connections = get_cached_connections(params.artist_id);
    let mut budget_remaining = params.budget;
    
    // First level: take min(budget, max_relations) artists
    let first_level_count = params.budget.min(params.max_relations);
    let mut first_level_artists: Vec<(Uuid, f32)> = Vec::new();
    
    for (id, similarity) in root_connections.into_iter().take(first_level_count) {
        if !visited.contains(&id) {
            visited.insert(id);
            first_level_artists.push((id, similarity));
            budget_remaining = budget_remaining.saturating_sub(1);
        }
    }
    
    // Calculate how many children per parent we can afford
    let children_per_parent = if first_level_artists.is_empty() || budget_remaining == 0 {
        0
    } else {
        budget_remaining / first_level_artists.len()
    };
    
    // Build nested structure with even distribution
    let mut related_artists = Vec::new();
    for (artist_id, similarity) in &first_level_artists {
        if let Some(artist) = state.artist_metadata.get(artist_id) {
            let mut children = Vec::new();
            
            if children_per_parent > 0 {
                let child_connections = get_cached_connections(*artist_id);
                let mut added = 0;
                
                for (child_id, child_sim) in child_connections {
                    if added >= children_per_parent {
                        break;
                    }
                    if !visited.contains(&child_id) {
                        visited.insert(child_id);
                        
                        if let Some(child_artist) = state.artist_metadata.get(&child_id) {
                            // For now, no third level
                            children.push(ExploreArtist {
                                id: child_id,
                                name: child_artist.name.clone(),
                                url: child_artist.url.clone(),
                                similarity: child_sim,
                                related_artists: Vec::new(),
                            });
                            added += 1;
                        }
                    }
                }
            }
            
            related_artists.push(ExploreArtist {
                id: *artist_id,
                name: artist.name.clone(),
                url: artist.url.clone(),
                similarity: *similarity,
                related_artists: children,
            });
        }
    }

    let duration_ms = start_time.elapsed().as_millis() as u64;

    fn count_total_artists(artists: &[ExploreArtist]) -> usize {
        artists.len()
            + artists
                .iter()
                .map(|a| count_total_artists(&a.related_artists))
                .sum::<usize>()
    }

    let total_found = count_total_artists(&related_artists);

    Json(ExploreResponse {
        center_artist,
        related_artists,
        total_found,
        search_stats: SearchStats {
            artists_visited: total_artists_visited,
            duration_ms,
        },
    })
}
