use super::utils::{get_artist_connections, open_memory_mapped_file, reconstruct_path, PathResult};
use crate::pathfinding_config::PathfindingConfig;
use rustc_hash::{FxHashMap, FxHashSet};
use std::{collections::VecDeque, path::Path, time::Instant};
use uuid::Uuid;

struct BfsState {
    queue: VecDeque<Uuid>,
    visited: FxHashSet<Uuid>,
    parent_map: FxHashMap<Uuid, (Uuid, f32)>,
}

impl BfsState {
    fn new(start: Uuid) -> Self {
        let mut queue = VecDeque::new();
        let mut visited = FxHashSet::default();
        
        queue.push_back(start);
        visited.insert(start);
        
        Self {
            queue,
            visited,
            parent_map: FxHashMap::default(),
        }
    }
    
    fn visit_neighbor(&mut self, neighbor: Uuid, current: Uuid, similarity: f32) {
        if !self.visited.contains(&neighbor) {
            self.visited.insert(neighbor);
            self.parent_map.insert(neighbor, (current, similarity));
            self.queue.push_back(neighbor);
        }
    }
}

pub fn bfs_find_path(
    start: Uuid,
    target: Uuid,
    graph_binary_path: &Path,
    graph_index: &FxHashMap<Uuid, u64>,
    config: &PathfindingConfig,
) -> PathResult {
    let search_timer = Instant::now();
    
    let graph_data = match open_memory_mapped_file(graph_binary_path) {
        Ok(data) => data,
        Err(_) => return (None, 0, 0.0),
    };
    
    let mut bfs_state = BfsState::new(start);
    
    while let Some(current_artist) = bfs_state.queue.pop_front() {
        if current_artist == target {
            let path = reconstruct_path(&bfs_state.parent_map, start, target);
            let elapsed_time = search_timer.elapsed().as_secs_f64();
            return (Some(path), bfs_state.visited.len(), elapsed_time);
        }
        
        let artist_connections = get_artist_connections(current_artist, &graph_data, graph_index, config);
        
        for (neighbor_artist, similarity_score) in artist_connections {
            bfs_state.visit_neighbor(neighbor_artist, current_artist, similarity_score);
        }
    }
    
    let elapsed_time = search_timer.elapsed().as_secs_f64();
    (None, bfs_state.visited.len(), elapsed_time)
}