pub mod bfs;
pub mod dijkstra;
pub mod utils;

use rustc_hash::FxHashMap;
use std::time::Instant;
use uuid::Uuid;
use crate::{pathfinding_config::PathfindingConfig, Algorithm};
use bfs::neighborhood::explore_path_neighborhood;

// Re-export the public functions
pub use bfs::bfs_find_path;
pub use dijkstra::dijkstra_find_path;
pub use utils::{get_artist_connections, EnhancedPathResult};

pub fn find_paths_with_exploration(
    start: Uuid,
    target: Uuid,
    algorithm: Algorithm,
    budget: usize,
    graph_data: &memmap2::Mmap,
    graph_index: &FxHashMap<Uuid, u64>,
    config: &PathfindingConfig,
) -> utils::EnhancedPathResult {
    let search_timer = Instant::now();
    
    // Find primary path using chosen algorithm
    let (primary_path, artists_visited, _) = match algorithm {
        Algorithm::Dijkstra => dijkstra_find_path(start, target, graph_data, graph_index, config),
        Algorithm::Bfs => bfs_find_path(start, target, graph_data, graph_index, config),
    };
    
    match primary_path {
        Some(path) => handle_successful_path_generic(
            path,
            budget,
            artists_visited,
            graph_data,
            graph_index,
            config,
            search_timer,
        ),
        None => utils::EnhancedPathResult::NoPath {
            artists_visited,
            duration_ms: search_timer.elapsed().as_millis() as u64,
        }
    }
}

fn handle_successful_path_generic(
    path: Vec<(Uuid, f32)>,
    budget: usize,
    artists_visited: usize,
    graph_data: &memmap2::Mmap,
    graph_index: &FxHashMap<Uuid, u64>,
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
        let (related_artists, connections) = explore_path_neighborhood(
            &path,
            budget,
            graph_data,
            graph_index,
            config
        );
        
        utils::EnhancedPathResult::Success {
            primary_path: path,
            related_artists,
            connections,
            artists_visited,
            duration_ms: start_time.elapsed().as_millis() as u64,
        }
    }
}