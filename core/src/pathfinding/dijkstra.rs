use super::utils::{PathResult, get_artist_connections, open_memory_mapped_file, reconstruct_path};
use crate::pathfinding_config::PathfindingConfig;
use rustc_hash::{FxHashMap, FxHashSet};
use std::{cmp::Ordering, collections::BinaryHeap, path::Path, time::Instant};
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
    graph_binary_path: &Path,
    graph_index: &FxHashMap<Uuid, u64>,
    config: &PathfindingConfig,
) -> PathResult {
    let search_timer = Instant::now();

    let graph_data = match open_memory_mapped_file(graph_binary_path) {
        Ok(data) => data,
        Err(_) => return (None, 0, 0.0),
    };

    let mut dijkstra_state = DijkstraState::new(start);

    while let Some(DijkstraNode {
        cost,
        artist: current_artist,
    }) = dijkstra_state.heap.pop()
    {
        if current_artist == target {
            let path = reconstruct_path(&dijkstra_state.parent_map, start, target);
            let elapsed_time = search_timer.elapsed().as_secs_f64();
            return (Some(path), dijkstra_state.visited.len(), elapsed_time);
        }

        if dijkstra_state.visited.contains(&current_artist) {
            continue;
        }
        dijkstra_state.visited.insert(current_artist);

        let artist_connections =
            get_artist_connections(current_artist, &graph_data, graph_index, config);

        for (neighbor_artist, similarity_score) in artist_connections {
            dijkstra_state.visit_neighbor(neighbor_artist, current_artist, similarity_score, cost);
        }
    }

    let elapsed_time = search_timer.elapsed().as_secs_f64();
    (None, dijkstra_state.visited.len(), elapsed_time)
}
