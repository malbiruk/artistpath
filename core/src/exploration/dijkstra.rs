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
        // Clean algorithmic stopping condition:
        // If we have found at least 'budget' artists, and the current cost
        // is higher than the cost of the budget-th cheapest artist we've found,
        // we can stop because all remaining artists will be more expensive.
        if discovered.len() >= budget {
            let mut sorted_costs: Vec<f32> = distances.values().copied().collect();
            sorted_costs.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
            if let Some(&budget_threshold) = sorted_costs.get(budget - 1) {
                if cost > budget_threshold {
                    break; // Found optimal subset
                }
            }
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
            let is_better_path = if let Some(&existing_cost) = distances.get(&neighbor) {
                new_cost < existing_cost
            } else {
                true // First time discovering this neighbor
            };
            
            if !is_better_path {
                continue;
            }
            
            // Update distance and add to heap
            distances.insert(neighbor, new_cost);
            heap.push(ExplorationNode {
                cost: new_cost,
                artist: neighbor,
            });
            
            // Update discovered artists with the better path
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
    
    // Select optimal subset of artists that minimizes total cost
    let optimal_discovered = select_optimal_subset(center_id, &distances, budget);
    
    // Build final connections map for optimal subset
    let mut final_connections = FxHashMap::default();
    for &artist_id in optimal_discovered.keys() {
        if let Some(cached_connections) = connection_cache.get(&artist_id) {
            // Filter connections to only include other artists in optimal subset
            let filtered: Vec<(Uuid, f32)> = cached_connections
                .iter()
                .filter(|(neighbor_id, _)| optimal_discovered.contains_key(neighbor_id))
                .cloned()
                .collect();
            final_connections.insert(artist_id, filtered);
        }
    }
    
    ExplorationResult::new(
        optimal_discovered,
        final_connections,
        artists_visited,
        start_time.elapsed().as_millis() as u64,
    )
}

fn select_optimal_subset(
    center_id: Uuid,
    distances: &FxHashMap<Uuid, f32>,
    budget: usize,
) -> FxHashMap<Uuid, (f32, usize)> {
    // Convert distances to sorted vector (artist_id, cost)
    let mut candidates: Vec<(Uuid, f32)> = distances.iter().map(|(&id, &cost)| (id, cost)).collect();
    candidates.sort_by(|a, b| a.1.partial_cmp(&b.1).unwrap_or(std::cmp::Ordering::Equal));
    
    // Take the cheapest `budget` artists
    let selected: Vec<Uuid> = candidates.into_iter().take(budget).map(|(id, _)| id).collect();
    
    // Build result map with (similarity, layer) for each selected artist
    let mut result = FxHashMap::default();
    for artist_id in selected {
        let cost = distances[&artist_id];
        let similarity = if artist_id == center_id { 1.0 } else { 1.0 - cost }; // Approximate similarity
        let layer = if artist_id == center_id { 0 } else { 1 + (cost * 5.0) as usize };
        result.insert(artist_id, (similarity, layer));
    }
    
    result
}
