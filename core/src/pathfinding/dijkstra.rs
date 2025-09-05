use super::utils::{PathResult, get_artist_connections};
use crate::pathfinding_config::PathfindingConfig;
use rustc_hash::{FxHashMap, FxHashSet};
use std::{cmp::Ordering, collections::BinaryHeap, time::Instant};
use uuid::Uuid;

#[derive(Clone)]
struct DijkstraNode {
    cost: f32,
    artist: Uuid,
}

impl PartialEq for DijkstraNode {
    fn eq(&self, other: &Self) -> bool {
        self.cost == other.cost
    }
}

impl Eq for DijkstraNode {}

impl PartialOrd for DijkstraNode {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for DijkstraNode {
    fn cmp(&self, other: &Self) -> Ordering {
        // Reverse order for min-heap (BinaryHeap is max-heap by default)
        // Handle NaN by treating it as Equal
        other
            .cost
            .partial_cmp(&self.cost)
            .unwrap_or(Ordering::Equal)
    }
}

struct DijkstraState {
    heap: BinaryHeap<DijkstraNode>,
    distances: FxHashMap<Uuid, f32>,
    parent_map: FxHashMap<Uuid, (Uuid, f32)>,
    visited: FxHashSet<Uuid>,
}

impl DijkstraState {
    fn new(start: Uuid) -> Self {
        let mut heap = BinaryHeap::new();
        let mut distances = FxHashMap::default();

        heap.push(DijkstraNode {
            cost: 0.0,
            artist: start,
        });
        distances.insert(start, 0.0);

        Self {
            heap,
            distances,
            parent_map: FxHashMap::default(),
            visited: FxHashSet::default(),
        }
    }

    fn visit_neighbor(
        &mut self,
        neighbor: Uuid,
        current: Uuid,
        similarity: f32,
        current_cost: f32,
    ) {
        let edge_weight = 1.0 - similarity;
        let new_cost = current_cost + edge_weight;

        if let Some(&existing_cost) = self.distances.get(&neighbor) {
            if new_cost >= existing_cost {
                return;
            }
        }

        self.distances.insert(neighbor, new_cost);
        self.parent_map.insert(neighbor, (current, similarity));
        self.heap.push(DijkstraNode {
            cost: new_cost,
            artist: neighbor,
        });
    }
}

pub fn dijkstra_find_path(
    start: Uuid,
    target: Uuid,
    forward_graph_data: &memmap2::Mmap,
    forward_graph_index: &FxHashMap<Uuid, u64>,
    reverse_graph_data: &memmap2::Mmap,
    reverse_graph_index: &FxHashMap<Uuid, u64>,
    config: &PathfindingConfig,
) -> PathResult {
    let search_timer = Instant::now();

    let mut forward_state = DijkstraState::new(start);
    let mut reverse_state = DijkstraState::new(target);
    let mut all_visited: FxHashSet<Uuid> = FxHashSet::default();

    loop {
        // Process forward search
        let forward_finished = if let Some(DijkstraNode { cost: forward_cost, artist: forward_current }) = forward_state.heap.pop() {
            if forward_state.visited.contains(&forward_current) {
                false
            } else {
                // Check if reverse search has visited this node
                if reverse_state.visited.contains(&forward_current) {
                    let path = reconstruct_bidirectional_dijkstra_path(
                        &forward_state.parent_map,
                        &reverse_state.parent_map, 
                        start, 
                        target, 
                        forward_current
                    );
                    let elapsed_time = search_timer.elapsed().as_secs_f64();
                    all_visited.extend(&forward_state.visited);
                    all_visited.extend(&reverse_state.visited);
                    return (Some(path), all_visited.len(), elapsed_time);
                }

                forward_state.visited.insert(forward_current);
                
                let connections = get_artist_connections(forward_current, forward_graph_data, forward_graph_index, config);
                for (neighbor, similarity) in connections {
                    forward_state.visit_neighbor(neighbor, forward_current, similarity, forward_cost);
                }
                false
            }
        } else {
            true
        };

        // Process reverse search
        let reverse_finished = if let Some(DijkstraNode { cost: reverse_cost, artist: reverse_current }) = reverse_state.heap.pop() {
            if reverse_state.visited.contains(&reverse_current) {
                false
            } else {
                // Check if forward search has visited this node
                if forward_state.visited.contains(&reverse_current) {
                    let path = reconstruct_bidirectional_dijkstra_path(
                        &forward_state.parent_map,
                        &reverse_state.parent_map, 
                        start, 
                        target, 
                        reverse_current
                    );
                    let elapsed_time = search_timer.elapsed().as_secs_f64();
                    all_visited.extend(&forward_state.visited);
                    all_visited.extend(&reverse_state.visited);
                    return (Some(path), all_visited.len(), elapsed_time);
                }

                reverse_state.visited.insert(reverse_current);
                
                let connections = get_artist_connections(reverse_current, reverse_graph_data, reverse_graph_index, config);
                for (neighbor, similarity) in connections {
                    reverse_state.visit_neighbor(neighbor, reverse_current, similarity, reverse_cost);
                }
                false
            }
        } else {
            true
        };

        // If both searches are finished, no path exists
        if forward_finished && reverse_finished {
            break;
        }
    }

    let elapsed_time = search_timer.elapsed().as_secs_f64();
    all_visited.extend(&forward_state.visited);
    all_visited.extend(&reverse_state.visited);
    (None, all_visited.len(), elapsed_time)
}

fn reconstruct_bidirectional_dijkstra_path(
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
    
    // Step 2: Traverse back from meeting point to target using reverse parent map  
    let mut current = meeting_point;
    let mut path_to_target = Vec::new();
    
    while current != target {
        if let Some(&(parent, similarity)) = reverse_parent.get(&current) {
            path_to_target.push((current, similarity));
            current = parent;
        } else {
            break;
        }
    }
    path_to_target.push((target, 0.0));
    
    // Step 3: Create unified path from start to target
    // Reverse path_to_start to get start -> meeting_point
    path_to_start.reverse();
    path.extend(path_to_start);
    
    // Add path_to_target as is (meeting_point -> target), but skip meeting_point to avoid duplication
    if path_to_target.len() > 1 {
        path.extend(path_to_target.into_iter().skip(1));
    }
    
    path
}
