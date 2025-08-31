use super::ExplorationResult;
use crate::{PathfindingConfig, get_artist_connections};
use memmap2::Mmap;
use rustc_hash::{FxHashMap, FxHashSet};
use std::{cmp::Ordering, collections::BinaryHeap, time::Instant};
use uuid::Uuid;

#[derive(Clone)]
struct ExplorationNode {
    cost: f32,
    artist: Uuid,
}

impl PartialEq for ExplorationNode {
    fn eq(&self, other: &Self) -> bool {
        self.cost == other.cost
    }
}

impl Eq for ExplorationNode {}

impl PartialOrd for ExplorationNode {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for ExplorationNode {
    fn cmp(&self, other: &Self) -> Ordering {
        // Reverse order for min-heap (BinaryHeap is max-heap by default)
        other
            .cost
            .partial_cmp(&self.cost)
            .unwrap_or(Ordering::Equal)
    }
}

pub fn explore_dijkstra(
    center_id: Uuid,
    budget: usize,
    max_relations: usize,
    min_similarity: f32,
    graph_mmap: &Mmap,
    graph_index: &FxHashMap<Uuid, u64>,
) -> ExplorationResult {
    let start_time = Instant::now();
    let config = PathfindingConfig::new(min_similarity, max_relations, false);
    
    let mut heap = BinaryHeap::new();
    let mut distances = FxHashMap::default();
    let mut discovered = FxHashMap::default();
    let mut visited = FxHashSet::default();
    let mut connection_cache: FxHashMap<Uuid, Vec<(Uuid, f32)>> = FxHashMap::default();
    let mut artists_visited = 0;
    
    // Initialize with center artist
    heap.push(ExplorationNode {
        cost: 0.0,
        artist: center_id,
    });
    distances.insert(center_id, 0.0);
    discovered.insert(center_id, (1.0, 0)); // (similarity, distance_from_center)
    
    while let Some(ExplorationNode { cost, artist: current_artist }) = heap.pop() {
        // Stop if we've reached our budget
        if discovered.len() >= budget {
            break;
        }
        
        // Skip if already visited
        if visited.contains(&current_artist) {
            continue;
        }
        visited.insert(current_artist);
        
        // Get artist connections (cached)
        let connections = if let Some(cached) = connection_cache.get(&current_artist) {
            cached.clone()
        } else {
            let conns = get_artist_connections(current_artist, graph_mmap, graph_index, &config);
            artists_visited += 1;
            let limited_conns: Vec<(Uuid, f32)> = conns.into_iter().take(max_relations).collect();
            connection_cache.insert(current_artist, limited_conns.clone());
            limited_conns
        };
        
        // Visit neighbors
        for (neighbor, similarity) in connections {
            if visited.contains(&neighbor) {
                continue;
            }
            
            let edge_weight = 1.0 - similarity; // Convert similarity to distance/weight
            let new_cost = cost + edge_weight;
            
            // Check if this is a better path to the neighbor
            if let Some(&existing_cost) = distances.get(&neighbor) {
                if new_cost >= existing_cost {
                    continue;
                }
            }
            
            // Update distance and add to heap
            distances.insert(neighbor, new_cost);
            heap.push(ExplorationNode {
                cost: new_cost,
                artist: neighbor,
            });
            
            // Add to discovered artists if not already there or if this is a better path
            if !discovered.contains_key(&neighbor) || new_cost < *distances.get(&neighbor).unwrap_or(&f32::INFINITY) {
                // Calculate distance from center - center artist always gets layer 0, others get layer > 0
                let distance_from_center = if neighbor == center_id { 
                    0 
                } else { 
                    // Ensure non-center artists get layer >= 1
                    1 + (new_cost * 5.0) as usize 
                };
                discovered.insert(neighbor, (similarity, distance_from_center));
            }
        }
    }
    
    // Build final connections map for discovered artists
    let mut final_connections = FxHashMap::default();
    for &artist_id in discovered.keys() {
        if let Some(cached_connections) = connection_cache.get(&artist_id) {
            // Filter connections to only include other discovered artists
            let filtered: Vec<(Uuid, f32)> = cached_connections
                .iter()
                .filter(|(neighbor_id, _)| discovered.contains_key(neighbor_id))
                .cloned()
                .collect();
            final_connections.insert(artist_id, filtered);
        }
    }
    
    ExplorationResult::new(
        discovered,
        final_connections,
        artists_visited,
        start_time.elapsed().as_millis() as u64,
    )
}
