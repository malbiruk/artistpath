mod state;
pub mod neighborhood;

use rustc_hash::FxHashMap;
use std::time::Instant;
use uuid::Uuid;
use crate::pathfinding_config::PathfindingConfig;
use super::utils::PathResult;
use state::BfsState;

pub fn bfs_find_path(
    start: Uuid,
    target: Uuid,
    forward_graph_data: &memmap2::Mmap,
    forward_graph_index: &FxHashMap<Uuid, u64>,
    reverse_graph_data: &memmap2::Mmap,
    reverse_graph_index: &FxHashMap<Uuid, u64>,
    config: &PathfindingConfig,
) -> PathResult {
    let search_timer = Instant::now();
    
    let mut bfs_state = BfsState::new(start);
    let path = bfs_state.find_path_to_target(
        target, 
        forward_graph_data, 
        forward_graph_index, 
        reverse_graph_data, 
        reverse_graph_index, 
        config
    );
    
    let elapsed_time = search_timer.elapsed().as_secs_f64();
    (path, bfs_state.visited.len(), elapsed_time)
}

