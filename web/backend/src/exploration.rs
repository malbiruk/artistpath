use crate::models::{GraphEdge, GraphExploreResponse, GraphNode, PathArtist, SearchStats};
use crate::state::AppState;
use artistpath_core::{Algorithm, ExplorationResult, explore_bfs, explore_dijkstra};
use std::time::Instant;
use uuid::Uuid;

pub fn explore_artist_network_graph(
    center_id: Uuid,
    algorithm: Algorithm,
    budget: usize,
    max_relations: usize,
    min_similarity: f32,
    state: &AppState,
) -> GraphExploreResponse {
    let start_time = Instant::now();

    let center_artist = build_center_artist_info(center_id, state);

    if center_artist.name == "Unknown Artist" {
        return build_empty_graph_response(center_artist, start_time);
    }

    let exploration_result = match algorithm {
        Algorithm::Dijkstra => explore_dijkstra(
            center_id,
            budget,
            max_relations,
            min_similarity,
            &state.graph_mmap,
            &state.graph_index,
        ),
        Algorithm::Bfs => explore_bfs(
            center_id,
            budget,
            max_relations,
            min_similarity,
            &state.graph_mmap,
            &state.graph_index,
        ),
    };

    build_graph_response_from_exploration(center_artist, exploration_result, state)
}

pub fn explore_artist_network_reverse_graph(
    center_id: Uuid,
    algorithm: Algorithm,
    budget: usize,
    max_relations: usize,
    min_similarity: f32,
    state: &AppState,
) -> GraphExploreResponse {
    let start_time = Instant::now();

    let center_artist = build_center_artist_info(center_id, state);

    if center_artist.name == "Unknown Artist" {
        return build_empty_graph_response(center_artist, start_time);
    }

    // Use the same exploration functions but with reverse graph data
    let exploration_result = match algorithm {
        Algorithm::Dijkstra => explore_dijkstra(
            center_id,
            budget,
            max_relations,
            min_similarity,
            &state.reverse_graph_mmap,
            &state.reverse_graph_index,
        ),
        Algorithm::Bfs => explore_bfs(
            center_id,
            budget,
            max_relations,
            min_similarity,
            &state.reverse_graph_mmap,
            &state.reverse_graph_index,
        ),
    };

    build_reverse_graph_response_from_exploration(center_artist, exploration_result, state)
}

fn build_center_artist_info(center_id: Uuid, state: &AppState) -> PathArtist {
    match state.artist_metadata.get(&center_id) {
        Some(artist) => PathArtist {
            id: artist.id,
            name: artist.name.clone(),
            url: artist.url.clone(),
            similarity: None,
        },
        None => PathArtist {
            id: center_id,
            name: "Unknown Artist".to_string(),
            url: "".to_string(),
            similarity: None,
        },
    }
}

fn build_empty_graph_response(
    center_artist: PathArtist,
    start_time: Instant,
) -> GraphExploreResponse {
    GraphExploreResponse {
        center_artist,
        nodes: vec![],
        edges: vec![],
        total_found: 0,
        search_stats: SearchStats {
            artists_visited: 0,
            duration_ms: start_time.elapsed().as_millis() as u64,
        },
    }
}

fn build_graph_response_from_exploration(
    center_artist: PathArtist,
    exploration_result: ExplorationResult,
    state: &AppState,
) -> GraphExploreResponse {
    let nodes = build_graph_nodes(&exploration_result, state);
    let edges = build_graph_edges(&exploration_result);

    GraphExploreResponse {
        center_artist,
        nodes,
        edges,
        total_found: exploration_result.total_discovered(),
        search_stats: SearchStats {
            artists_visited: exploration_result.stats.artists_visited,
            duration_ms: exploration_result.stats.duration_ms,
        },
    }
}

fn build_graph_nodes(exploration_result: &ExplorationResult, state: &AppState) -> Vec<GraphNode> {
    exploration_result
        .discovered_artists
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

fn build_graph_edges(exploration_result: &ExplorationResult) -> Vec<GraphEdge> {
    let mut edges = Vec::new();
    let discovered_ids = exploration_result
        .discovered_artists
        .keys()
        .collect::<std::collections::HashSet<_>>();

    for (&from_id, connections) in &exploration_result.connections {
        for &(to_id, similarity) in connections {
            if discovered_ids.contains(&to_id) && from_id != to_id {
                edges.push(GraphEdge {
                    from: from_id,
                    to: to_id,
                    similarity,
                });
            }
        }
    }

    edges
}

fn build_reverse_graph_response_from_exploration(
    center_artist: PathArtist,
    exploration_result: ExplorationResult,
    state: &AppState,
) -> GraphExploreResponse {
    let nodes = build_graph_nodes(&exploration_result, state);
    let edges = build_reverse_graph_edges(&exploration_result);

    GraphExploreResponse {
        center_artist,
        nodes,
        edges,
        total_found: exploration_result.total_discovered(),
        search_stats: SearchStats {
            artists_visited: exploration_result.stats.artists_visited,
            duration_ms: exploration_result.stats.duration_ms,
        },
    }
}

fn build_reverse_graph_edges(exploration_result: &ExplorationResult) -> Vec<GraphEdge> {
    let mut edges = Vec::new();
    let discovered_ids = exploration_result
        .discovered_artists
        .keys()
        .collect::<std::collections::HashSet<_>>();

    for (&from_id, connections) in &exploration_result.connections {
        for &(to_id, similarity) in connections {
            if discovered_ids.contains(&to_id) && from_id != to_id {
                // Flip the edge direction for reverse exploration
                // In reverse graph, edges point from influenced TO influencer
                // But we want to show them as flowing FROM influencer TO influenced
                edges.push(GraphEdge {
                    from: to_id,  // Flipped
                    to: from_id,  // Flipped
                    similarity,
                });
            }
        }
    }

    edges
}
