use rustc_hash::{FxHashMap, FxHashSet};
use std::collections::VecDeque;
use uuid::Uuid;
use crate::pathfinding_config::PathfindingConfig;
use super::super::utils::get_artist_connections;

pub struct BfsState {
    queue: VecDeque<Uuid>,
    pub visited: FxHashSet<Uuid>,
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
        }
    }
    
    
    pub fn find_path_to_target(
        &mut self, 
        target: Uuid, 
        forward_graph_data: &memmap2::Mmap, 
        forward_graph_index: &FxHashMap<Uuid, u64>,
        reverse_graph_data: &memmap2::Mmap, 
        reverse_graph_index: &FxHashMap<Uuid, u64>,
        config: &PathfindingConfig
    ) -> Option<Vec<(Uuid, f32)>> {
        let mut forward_queue = VecDeque::new();
        let mut reverse_queue = VecDeque::new();
        let mut forward_visited = FxHashSet::default();
        let mut reverse_visited = FxHashSet::default();
        let mut forward_queued = FxHashSet::default();  // Track what's in queue
        let mut reverse_queued = FxHashSet::default();  // Track what's in queue
        let mut forward_parent = FxHashMap::default();
        let mut reverse_parent = FxHashMap::default();
        
        // Initialize both searches
        let start = self.queue[0]; // Get start from our initial queue
        forward_queue.push_back(start);
        forward_queued.insert(start);
        reverse_queue.push_back(target);
        reverse_queued.insert(target);
        // Don't mark as visited yet - let the main loop handle it
        // This ensures proper parent map construction
        
        // Track total visited for compatibility
        self.visited.clear(); // Clear any previous state
        
        while !forward_queue.is_empty() || !reverse_queue.is_empty() {
            // Expand from forward direction
            if let Some(current) = forward_queue.pop_front() {
                // Skip if already processed
                if forward_visited.contains(&current) {
                    continue;
                }
                
                // Mark as visited NOW, before checking intersection
                forward_visited.insert(current);
                forward_queued.remove(&current);  // Remove from queued set
                self.visited.insert(current);
                
                // Check if we've met the reverse search
                if reverse_visited.contains(&current) {
                    return Some(self.reconstruct_bidirectional_path(
                        &forward_parent, &reverse_parent, start, target, current
                    ));
                }
                
                let connections = get_artist_connections(current, forward_graph_data, forward_graph_index, config);
                for (neighbor, similarity) in connections {
                    if !forward_visited.contains(&neighbor) && !forward_queued.contains(&neighbor) {
                        forward_parent.insert(neighbor, (current, similarity));
                        forward_queue.push_back(neighbor);
                        forward_queued.insert(neighbor);  // Track that it's queued
                    }
                }
            }
            
            // Expand from reverse direction
            if let Some(current) = reverse_queue.pop_front() {
                // Skip if already processed
                if reverse_visited.contains(&current) {
                    continue;
                }
                
                // Mark as visited NOW, before checking intersection
                reverse_visited.insert(current);
                reverse_queued.remove(&current);  // Remove from queued set
                self.visited.insert(current);
                
                // Check if we've met the forward search
                if forward_visited.contains(&current) {
                    return Some(self.reconstruct_bidirectional_path(
                        &forward_parent, &reverse_parent, start, target, current
                    ));
                }
                
                let connections = get_artist_connections(current, reverse_graph_data, reverse_graph_index, config);
                for (neighbor, similarity) in connections {
                    if !reverse_visited.contains(&neighbor) && !reverse_queued.contains(&neighbor) {
                        reverse_parent.insert(neighbor, (current, similarity));
                        reverse_queue.push_back(neighbor);
                        reverse_queued.insert(neighbor);  // Track that it's queued
                    }
                }
            }
        }
        
        None
    }
    
    fn reconstruct_bidirectional_path(
        &self,
        forward_parent: &FxHashMap<Uuid, (Uuid, f32)>,
        reverse_parent: &FxHashMap<Uuid, (Uuid, f32)>,
        start: Uuid,
        target: Uuid,
        meeting_point: Uuid
    ) -> Vec<(Uuid, f32)> {
        let mut path = Vec::new();
        
        // Step 1: Traverse back from meeting point to start using forward parent map
        let mut current = meeting_point;
        let mut path_to_start = Vec::new();
        
        while current != start {
            if let Some(&(parent, similarity)) = forward_parent.get(&current) {
                path_to_start.push((current, similarity));
                current = parent;
            } else {
                break;
            }
        }
        path_to_start.push((start, 0.0));
        
        // Step 2: Build path from meeting point to target using reverse parent map
        // reverse_parent[X] = (Y, sim) means in the reverse search, Y -> X with similarity sim
        // Since reverse search starts from target and goes backwards, 
        // following parents from meeting point should lead us to target
        let mut current = meeting_point;
        let mut path_to_target = Vec::new();
        
        while current != target {
            if let Some(&(parent, similarity)) = reverse_parent.get(&current) {
                // In reverse search, parent reached current, so the edge is parent -> current
                // Since we're going from meeting to target, we follow the parents
                path_to_target.push((parent, similarity));
                current = parent;
            } else {
                // No parent means current was a starting point
                break;
            }
        }
        
        // Step 3: Create unified path from start to target
        // Reverse path_to_start to get start -> meeting_point
        path_to_start.reverse();
        path.extend(path_to_start);
        
        // Add path_to_target
        if !path_to_target.is_empty() {
            path.extend(path_to_target);
        }
        
        path
    }
}