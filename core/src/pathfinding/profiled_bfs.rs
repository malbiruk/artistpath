use rustc_hash::{FxHashMap, FxHashSet};
use std::collections::VecDeque;
use std::time::Instant;
use uuid::Uuid;
use crate::pathfinding_config::PathfindingConfig;
use super::utils::get_artist_connections;

#[derive(Debug, Clone)]
pub struct ProfilingMetrics {
    pub total_time_ms: u128,
    pub memory_access_time_ms: u128,
    pub queue_operations_time_ms: u128,
    pub hash_operations_time_ms: u128,
    pub path_reconstruction_time_ms: u128,
    pub memory_accesses: usize,
    pub queue_operations: usize,
    pub hash_lookups: usize,
    pub nodes_explored_forward: usize,
    pub nodes_explored_reverse: usize,
    pub nodes_in_queue_forward: usize,
    pub nodes_in_queue_reverse: usize,
    pub meeting_point_found_at: Option<usize>,
}

impl ProfilingMetrics {
    fn new() -> Self {
        Self {
            total_time_ms: 0,
            memory_access_time_ms: 0,
            queue_operations_time_ms: 0,
            hash_operations_time_ms: 0,
            path_reconstruction_time_ms: 0,
            memory_accesses: 0,
            queue_operations: 0,
            hash_lookups: 0,
            nodes_explored_forward: 0,
            nodes_explored_reverse: 0,
            nodes_in_queue_forward: 0,
            nodes_in_queue_reverse: 0,
            meeting_point_found_at: None,
        }
    }
}

pub fn profiled_bidirectional_bfs(
    start: Uuid,
    target: Uuid,
    forward_graph_data: &memmap2::Mmap,
    forward_graph_index: &FxHashMap<Uuid, u64>,
    reverse_graph_data: &memmap2::Mmap,
    reverse_graph_index: &FxHashMap<Uuid, u64>,
    config: &PathfindingConfig,
) -> (Option<Vec<(Uuid, f32)>>, ProfilingMetrics) {
    let total_timer = Instant::now();
    let mut metrics = ProfilingMetrics::new();
    
    let mut forward_queue = VecDeque::new();
    let mut reverse_queue = VecDeque::new();
    let mut forward_visited = FxHashSet::default();
    let mut reverse_visited = FxHashSet::default();
    let mut forward_queued = FxHashSet::default();
    let mut reverse_queued = FxHashSet::default();
    let mut forward_parent = FxHashMap::default();
    let mut reverse_parent = FxHashMap::default();
    
    // Initialize
    forward_queue.push_back(start);
    forward_queued.insert(start);
    reverse_queue.push_back(target);
    reverse_queued.insert(target);
    
    let mut iterations = 0;
    
    while !forward_queue.is_empty() || !reverse_queue.is_empty() {
        iterations += 1;
        metrics.nodes_in_queue_forward = forward_queue.len();
        metrics.nodes_in_queue_reverse = reverse_queue.len();
        
        // Forward expansion
        if let Some(current) = forward_queue.pop_front() {
            let queue_timer = Instant::now();
            metrics.queue_operations += 1;
            metrics.queue_operations_time_ms += queue_timer.elapsed().as_micros();
            
            if forward_visited.contains(&current) {
                continue;
            }
            
            let hash_timer = Instant::now();
            forward_visited.insert(current);
            forward_queued.remove(&current);
            metrics.hash_lookups += 2;
            metrics.hash_operations_time_ms += hash_timer.elapsed().as_micros();
            metrics.nodes_explored_forward += 1;
            
            // Check intersection
            let hash_timer = Instant::now();
            if reverse_visited.contains(&current) {
                metrics.hash_lookups += 1;
                metrics.hash_operations_time_ms += hash_timer.elapsed().as_micros();
                metrics.meeting_point_found_at = Some(iterations);
                
                let path_timer = Instant::now();
                let path = reconstruct_path(
                    &forward_parent, &reverse_parent, start, target, current
                );
                metrics.path_reconstruction_time_ms = path_timer.elapsed().as_millis();
                metrics.total_time_ms = total_timer.elapsed().as_millis();
                return (Some(path), metrics);
            }
            metrics.hash_lookups += 1;
            metrics.hash_operations_time_ms += hash_timer.elapsed().as_micros();
            
            // Get connections (memory access)
            let mem_timer = Instant::now();
            let connections = get_artist_connections(
                current, forward_graph_data, forward_graph_index, config
            );
            metrics.memory_accesses += 1;
            metrics.memory_access_time_ms += mem_timer.elapsed().as_micros();
            
            for (neighbor, similarity) in connections {
                let hash_timer = Instant::now();
                if !forward_visited.contains(&neighbor) && !forward_queued.contains(&neighbor) {
                    forward_parent.insert(neighbor, (current, similarity));
                    forward_queue.push_back(neighbor);
                    forward_queued.insert(neighbor);
                    metrics.queue_operations += 1;
                }
                metrics.hash_lookups += 2;
                metrics.hash_operations_time_ms += hash_timer.elapsed().as_micros();
            }
        }
        
        // Reverse expansion
        if let Some(current) = reverse_queue.pop_front() {
            let queue_timer = Instant::now();
            metrics.queue_operations += 1;
            metrics.queue_operations_time_ms += queue_timer.elapsed().as_micros();
            
            if reverse_visited.contains(&current) {
                continue;
            }
            
            let hash_timer = Instant::now();
            reverse_visited.insert(current);
            reverse_queued.remove(&current);
            metrics.hash_lookups += 2;
            metrics.hash_operations_time_ms += hash_timer.elapsed().as_micros();
            metrics.nodes_explored_reverse += 1;
            
            // Check intersection
            let hash_timer = Instant::now();
            if forward_visited.contains(&current) {
                metrics.hash_lookups += 1;
                metrics.hash_operations_time_ms += hash_timer.elapsed().as_micros();
                metrics.meeting_point_found_at = Some(iterations);
                
                let path_timer = Instant::now();
                let path = reconstruct_path(
                    &forward_parent, &reverse_parent, start, target, current
                );
                metrics.path_reconstruction_time_ms = path_timer.elapsed().as_millis();
                metrics.total_time_ms = total_timer.elapsed().as_millis();
                return (Some(path), metrics);
            }
            metrics.hash_lookups += 1;
            metrics.hash_operations_time_ms += hash_timer.elapsed().as_micros();
            
            // Get connections (memory access)
            let mem_timer = Instant::now();
            let connections = get_artist_connections(
                current, reverse_graph_data, reverse_graph_index, config
            );
            metrics.memory_accesses += 1;
            metrics.memory_access_time_ms += mem_timer.elapsed().as_micros();
            
            for (neighbor, similarity) in connections {
                let hash_timer = Instant::now();
                if !reverse_visited.contains(&neighbor) && !reverse_queued.contains(&neighbor) {
                    reverse_parent.insert(neighbor, (current, similarity));
                    reverse_queue.push_back(neighbor);
                    reverse_queued.insert(neighbor);
                    metrics.queue_operations += 1;
                }
                metrics.hash_lookups += 2;
                metrics.hash_operations_time_ms += hash_timer.elapsed().as_micros();
            }
        }
    }
    
    metrics.total_time_ms = total_timer.elapsed().as_millis();
    (None, metrics)
}

pub fn profiled_unidirectional_bfs(
    start: Uuid,
    target: Uuid,
    graph_data: &memmap2::Mmap,
    graph_index: &FxHashMap<Uuid, u64>,
    config: &PathfindingConfig,
) -> (Option<Vec<(Uuid, f32)>>, ProfilingMetrics) {
    let total_timer = Instant::now();
    let mut metrics = ProfilingMetrics::new();
    
    let mut queue = VecDeque::new();
    let mut visited = FxHashSet::default();
    let mut parent = FxHashMap::default();
    
    queue.push_back(start);
    visited.insert(start);
    
    while let Some(current) = queue.pop_front() {
        let queue_timer = Instant::now();
        metrics.queue_operations += 1;
        metrics.queue_operations_time_ms += queue_timer.elapsed().as_micros();
        metrics.nodes_explored_forward += 1;
        
        if current == target {
            let path_timer = Instant::now();
            let path = reconstruct_unidirectional_path(&parent, start, target);
            metrics.path_reconstruction_time_ms = path_timer.elapsed().as_millis();
            metrics.total_time_ms = total_timer.elapsed().as_millis();
            return (Some(path), metrics);
        }
        
        // Get connections (memory access)
        let mem_timer = Instant::now();
        let connections = get_artist_connections(current, graph_data, graph_index, config);
        metrics.memory_accesses += 1;
        metrics.memory_access_time_ms += mem_timer.elapsed().as_micros();
        
        for (neighbor, similarity) in connections {
            let hash_timer = Instant::now();
            if !visited.contains(&neighbor) {
                visited.insert(neighbor);
                parent.insert(neighbor, (current, similarity));
                queue.push_back(neighbor);
                metrics.queue_operations += 1;
            }
            metrics.hash_lookups += 1;
            metrics.hash_operations_time_ms += hash_timer.elapsed().as_micros();
        }
    }
    
    metrics.total_time_ms = total_timer.elapsed().as_millis();
    (None, metrics)
}

fn reconstruct_path(
    forward_parent: &FxHashMap<Uuid, (Uuid, f32)>,
    reverse_parent: &FxHashMap<Uuid, (Uuid, f32)>,
    start: Uuid,
    target: Uuid,
    meeting_point: Uuid,
) -> Vec<(Uuid, f32)> {
    let mut path = Vec::new();
    
    // Build path from start to meeting point
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
    path_to_start.reverse();
    path.extend(path_to_start);
    
    // Build path from meeting point to target
    let mut current = meeting_point;
    let mut path_to_target = Vec::new();
    
    while current != target {
        if let Some(&(parent, similarity)) = reverse_parent.get(&current) {
            path_to_target.push((parent, similarity));
            current = parent;
        } else {
            break;
        }
    }
    
    if !path_to_target.is_empty() {
        path.extend(path_to_target);
    }
    
    path
}

fn reconstruct_unidirectional_path(
    parent_map: &FxHashMap<Uuid, (Uuid, f32)>,
    start: Uuid,
    target: Uuid,
) -> Vec<(Uuid, f32)> {
    let mut path = Vec::new();
    let mut current = target;
    
    while current != start {
        if let Some(&(parent, similarity)) = parent_map.get(&current) {
            path.push((current, similarity));
            current = parent;
        } else {
            break;
        }
    }
    
    path.push((start, 0.0));
    path.reverse();
    path
}