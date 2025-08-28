use crate::models::{PathArtist, PathResponse, SearchStats};
use crate::state::AppState;
use artistpath_core::{PathfindingConfig, bfs_find_path, dijkstra_find_path};
use std::time::Instant;
use uuid::Uuid;

pub fn find_path_between_artists(
    from_id: Uuid,
    to_id: Uuid,
    algorithm: String,
    min_similarity: f32,
    max_relations: usize,
    state: &AppState,
) -> PathResponse {
    let config = PathfindingConfig::new(min_similarity, max_relations, algorithm == "dijkstra");

    let (path_result, artists_visited, start_time) =
        execute_pathfinding(from_id, to_id, &algorithm, &config, state);

    build_path_response(path_result, artists_visited, start_time, algorithm, state)
}

pub fn execute_pathfinding(
    from_id: Uuid,
    to_id: Uuid,
    algorithm: &str,
    config: &PathfindingConfig,
    state: &AppState,
) -> (Option<Vec<(Uuid, f32)>>, usize, Instant) {
    let start_time = Instant::now();

    let (path_result, artists_visited, _duration) = if algorithm == "dijkstra" {
        dijkstra_find_path(
            from_id,
            to_id,
            std::path::Path::new("../../data/graph.bin"),
            &state.graph_index,
            config,
        )
    } else {
        bfs_find_path(
            from_id,
            to_id,
            std::path::Path::new("../../data/graph.bin"),
            &state.graph_index,
            config,
        )
    };

    (path_result, artists_visited, start_time)
}

pub fn build_path_response(
    path_result: Option<Vec<(Uuid, f32)>>,
    artists_visited: usize,
    start_time: Instant,
    algorithm: String,
    state: &AppState,
) -> PathResponse {
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

    PathResponse {
        path,
        artist_count,
        step_count,
        algorithm,
        search_stats: SearchStats {
            artists_visited,
            duration_ms,
        },
    }
}
