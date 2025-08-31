use rustc_hash::{FxHashMap, FxHashSet};
use std::collections::VecDeque;
use uuid::Uuid;
use crate::pathfinding_config::PathfindingConfig;
use super::super::utils::{get_artist_connections, reconstruct_path};

pub struct BfsState {
    queue: VecDeque<Uuid>,
    pub visited: FxHashSet<Uuid>,
    parent_map: FxHashMap<Uuid, (Uuid, f32)>,
}

impl BfsState {
    pub fn new(start: Uuid) -> Self {
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
    
    pub fn find_path_to_target(
        &mut self, 
        target: Uuid, 
        graph_data: &memmap2::Mmap, 
        graph_index: &FxHashMap<Uuid, u64>, 
        config: &PathfindingConfig
    ) -> Option<Vec<(Uuid, f32)>> {
        while let Some(current_artist) = self.queue.pop_front() {
            if current_artist == target {
                return Some(reconstruct_path(&self.parent_map, self.get_start_artist(), target));
            }
            
            let connections = get_artist_connections(current_artist, graph_data, graph_index, config);
            for (neighbor, similarity) in connections {
                self.visit_neighbor(neighbor, current_artist, similarity);
            }
        }
        
        None
    }
    
    fn get_start_artist(&self) -> Uuid {
        // The start artist is the one without a parent
        let children: FxHashSet<_> = self.parent_map.keys().cloned().collect();
        self.visited
            .iter()
            .find(|&id| !children.contains(id))
            .cloned()
            .expect("Start artist should always exist")
    }
}