mod state;
mod neighborhood;

use rustc_hash::FxHashMap;
use std::time::Instant;
use uuid::Uuid;
use crate::pathfinding_config::PathfindingConfig;
use super::utils::{PathResult, EnhancedPathResult};
use state::BfsState;
use neighborhood::explore_path_neighborhood;

pub fn bfs_find_path(
    start: Uuid,
    target: Uuid,
    graph_data: &memmap2::Mmap,
    graph_index: &FxHashMap<Uuid, u64>,
    config: &PathfindingConfig,
) -> PathResult {
    let search_timer = Instant::now();
    
    let mut bfs_state = BfsState::new(start);
    let path = bfs_state.find_path_to_target(target, graph_data, graph_index, config);
    
    let elapsed_time = search_timer.elapsed().as_secs_f64();
    (path, bfs_state.visited.len(), elapsed_time)
}

pub fn find_paths_with_exploration_bfs(
    start: Uuid,
    target: Uuid,
    budget: usize,
    graph_data: &memmap2::Mmap,
    graph_index: &FxHashMap<Uuid, u64>,
    config: &PathfindingConfig,
) -> EnhancedPathResult {
    let search_timer = Instant::now();
    
    // Find shortest path
    let (primary_path, artists_visited, _) = bfs_find_path(
        start, 
        target, 
        graph_data, 
        graph_index, 
        config
    );
    
    match primary_path {
        Some(path) => handle_successful_path(
            path,
            budget,
            artists_visited,
            graph_data,
            graph_index,
            config,
            search_timer,
        ),
        None => EnhancedPathResult::NoPath {
            artists_visited,
            duration_ms: search_timer.elapsed().as_millis() as u64,
        }
    }
}

fn handle_successful_path(
    path: Vec<(Uuid, f32)>,
    budget: usize,
    artists_visited: usize,
    graph_data: &memmap2::Mmap,
    graph_index: &FxHashMap<Uuid, u64>,
    config: &PathfindingConfig,
    start_time: Instant,
) -> EnhancedPathResult {
    let path_length = path.len();
    
    if path_length > budget {
        EnhancedPathResult::PathTooLong {
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
        
        EnhancedPathResult::Success {
            primary_path: path,
            related_artists,
            connections,
            artists_visited,
            duration_ms: start_time.elapsed().as_millis() as u64,
        }
    }
}