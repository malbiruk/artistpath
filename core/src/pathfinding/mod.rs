pub mod bfs;
pub mod dijkstra;
pub mod utils;

pub mod profiled_bfs;

use crate::{Algorithm, pathfinding_config::PathfindingConfig};
use bfs::neighborhood::explore_path_neighborhood;
use rustc_hash::FxHashMap;
use std::time::Instant;
use uuid::Uuid;

// Type alias to reduce complexity
type GraphData<'a> = (&'a memmap2::Mmap, &'a FxHashMap<Uuid, u64>);

// Struct to group related parameters and reduce argument count
pub struct BiDirectionalGraphs<'a> {
    pub forward: GraphData<'a>,
    pub reverse: GraphData<'a>,
}

// Re-export the public functions
pub use bfs::bfs_find_path;
pub use dijkstra::dijkstra_find_path;
pub use utils::{EnhancedPathResult, get_artist_connections};

pub fn find_paths_with_exploration(
    start: Uuid,
    target: Uuid,
    algorithm: Algorithm,
    budget: usize,
    graphs: BiDirectionalGraphs,
    config: &PathfindingConfig,
) -> utils::EnhancedPathResult {
    let search_timer = Instant::now();

    // Find primary path using chosen algorithm (now bidirectional)
    let (forward_data, forward_index) = graphs.forward;
    let (reverse_data, reverse_index) = graphs.reverse;

    let (primary_path, artists_visited, _) = match algorithm {
        Algorithm::Dijkstra => dijkstra_find_path(
            start,
            target,
            forward_data,
            forward_index,
            reverse_data,
            reverse_index,
            config,
        ),
        Algorithm::Bfs => bfs_find_path(
            start,
            target,
            forward_data,
            forward_index,
            reverse_data,
            reverse_index,
            config,
        ),
    };

    match primary_path {
        Some(path) => handle_successful_path_generic(
            path,
            budget,
            artists_visited,
            BiDirectionalGraphs {
                forward: (forward_data, forward_index),
                reverse: (reverse_data, reverse_index),
            },
            config,
            search_timer,
        ),
        None => utils::EnhancedPathResult::NoPath {
            artists_visited,
            duration_ms: search_timer.elapsed().as_millis() as u64,
        },
    }
}

fn handle_successful_path_generic(
    path: Vec<(Uuid, f32)>,
    budget: usize,
    artists_visited: usize,
    graphs: BiDirectionalGraphs,
    config: &PathfindingConfig,
    start_time: Instant,
) -> utils::EnhancedPathResult {
    let path_length = path.len();

    if path_length > budget {
        utils::EnhancedPathResult::PathTooLong {
            primary_path: path,
            path_length,
            minimum_budget_needed: path_length,
            artists_visited,
            duration_ms: start_time.elapsed().as_millis() as u64,
        }
    } else {
        let (related_artists, connections) =
            explore_path_neighborhood(&path, budget, graphs, config);

        utils::EnhancedPathResult::Success {
            primary_path: path,
            related_artists,
            connections,
            artists_visited,
            duration_ms: start_time.elapsed().as_millis() as u64,
        }
    }
}
