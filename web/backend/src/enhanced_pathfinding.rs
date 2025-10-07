use crate::models::{EnhancedPathResponse, EnhancedPathData, EnhancedPathError, GraphNode, GraphEdge, PathArtist, SearchStats};
use crate::state::AppState;
use artistpath_core::{PathfindingConfig, find_paths_with_exploration, EnhancedPathResult, Algorithm, BiDirectionalGraphs};
use rustc_hash::FxHashSet;
use uuid::Uuid;

pub fn find_enhanced_path_between_artists(
    from_id: Uuid,
    to_id: Uuid,
    algorithm: Algorithm,
    min_similarity: f32,
    max_relations: usize,
    budget: usize,
    state: &AppState,
) -> EnhancedPathResponse {
    let config = PathfindingConfig::new(min_similarity, max_relations, algorithm == Algorithm::Dijkstra);

    let graphs = BiDirectionalGraphs {
        forward: (&state.graph_mmap, &state.graph_index),
        reverse: (&state.reverse_graph_mmap, &state.reverse_graph_index),
    };

    let core_result = find_paths_with_exploration(
        from_id,
        to_id,
        algorithm,
        budget,
        graphs,
        &config,
    );

    build_enhanced_path_response(core_result, state)
}

fn build_enhanced_path_response(
    core_result: EnhancedPathResult,
    state: &AppState,
) -> EnhancedPathResponse {
    match core_result {
        EnhancedPathResult::Success {
            primary_path,
            related_artists,
            connections,
            artists_visited,
            duration_ms,
        } => {
            let path_artists = convert_path_to_artists(&primary_path, state);
            let nodes = build_graph_nodes(&related_artists, state);
            let edges = build_graph_edges(&connections, &primary_path);

            EnhancedPathResponse {
                status: "success".to_string(),
                data: Some(EnhancedPathData {
                    primary_path: path_artists,
                    nodes,
                    edges,
                    total_artists: related_artists.len(),
                }),
                error: None,
                search_stats: SearchStats {
                    artists_visited,
                    duration_ms,
                },
            }
        }
        EnhancedPathResult::PathTooLong {
            primary_path,
            path_length,
            minimum_budget_needed,
            artists_visited,
            duration_ms,
        } => {
            let path_artists = convert_path_to_artists(&primary_path, state);

            EnhancedPathResponse {
                status: "path_too_long".to_string(),
                data: None,
                error: Some(EnhancedPathError {
                    error_type: "path_too_long".to_string(),
                    message: format!(
                        "Path requires {} artists but budget is insufficient. Increase budget to {} to enable full exploration.",
                        path_length, minimum_budget_needed
                    ),
                    path_length: Some(path_length),
                    minimum_budget_needed: Some(minimum_budget_needed),
                    primary_path: Some(path_artists),
                }),
                search_stats: SearchStats {
                    artists_visited,
                    duration_ms,
                },
            }
        }
        EnhancedPathResult::NoPath {
            artists_visited,
            duration_ms,
        } => EnhancedPathResponse {
            status: "no_path".to_string(),
            data: None,
            error: Some(EnhancedPathError {
                error_type: "no_path".to_string(),
                message: "No path found between the specified artists".to_string(),
                path_length: None,
                minimum_budget_needed: None,
                primary_path: None,
            }),
            search_stats: SearchStats {
                artists_visited,
                duration_ms,
            },
        },
    }
}

fn convert_path_to_artists(path: &[(Uuid, f32)], state: &AppState) -> Vec<PathArtist> {
    path.iter()
        .enumerate()
        .map(|(index, (artist_id, similarity))| {
            let artist = &state.artist_metadata[artist_id];
            PathArtist {
                id: *artist_id,
                name: artist.name.clone(),
                url: artist.url.clone(),
                similarity: if index == 0 { None } else { Some(*similarity) },
            }
        })
        .collect()
}

fn build_graph_nodes(
    related_artists: &rustc_hash::FxHashMap<Uuid, (f32, usize)>,
    state: &AppState,
) -> Vec<GraphNode> {
    related_artists
        .iter()
        .filter_map(|(&id, &(similarity, layer))| {
            state.artist_metadata.get(&id).map(|artist| GraphNode {
                id,
                name: artist.name.clone(),
                layer,
                similarity,
                url: Some(artist.url.clone()),
            })
        })
        .collect()
}

fn build_graph_edges(
    connections: &rustc_hash::FxHashMap<Uuid, Vec<(Uuid, f32)>>,
    primary_path: &[(Uuid, f32)],
) -> Vec<GraphEdge> {
    let mut edges = Vec::new();
    let discovered_ids: FxHashSet<Uuid> = connections.keys().copied().collect();

    // Build a set of path edges (as directed pairs) for quick lookup
    let mut path_edges = FxHashSet::default();
    for window in primary_path.windows(2) {
        if let [from, to] = window {
            path_edges.insert((from.0, to.0));
        }
    }

    // Add edges from the primary path first - these are guaranteed to be connected
    for window in primary_path.windows(2) {
        if let [from, to] = window {
            edges.push(GraphEdge {
                from: from.0,
                to: to.0,
                similarity: to.1, // Similarity of the edge leading TO the target
            });
        }
    }

    // Add neighborhood connections
    for (&from_id, artist_connections) in connections {
        for &(to_id, similarity) in artist_connections {
            if discovered_ids.contains(&to_id) && from_id != to_id {
                // Check if this edge already exists
                let already_exists = edges.iter().any(|edge|
                    edge.from == from_id && edge.to == to_id
                );

                // Check if this would be the reverse of a path edge
                let is_reverse_of_path = path_edges.contains(&(to_id, from_id));

                if !already_exists && !is_reverse_of_path {
                    edges.push(GraphEdge {
                        from: from_id,
                        to: to_id,
                        similarity,
                    });
                }
            }
        }
    }

    edges
}