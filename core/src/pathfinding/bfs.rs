use super::utils::{get_artist_connections, reconstruct_path, PathResult, EnhancedPathResult};
use crate::pathfinding_config::PathfindingConfig;
use rustc_hash::{FxHashMap, FxHashSet};
use std::{collections::VecDeque, time::Instant};
use uuid::Uuid;

struct BfsState {
    queue: VecDeque<Uuid>,
    visited: FxHashSet<Uuid>,
    parent_map: FxHashMap<Uuid, (Uuid, f32)>,
    discovered_artists: FxHashMap<Uuid, (f32, usize)>,
    all_connections: FxHashMap<Uuid, Vec<(Uuid, f32)>>,
}

impl BfsState {
    fn new(start: Uuid) -> Self {
        let mut queue = VecDeque::new();
        let mut visited = FxHashSet::default();
        let mut discovered_artists = FxHashMap::default();
        
        queue.push_back(start);
        visited.insert(start);
        discovered_artists.insert(start, (1.0, 0));
        
        Self {
            queue,
            visited,
            parent_map: FxHashMap::default(),
            discovered_artists,
            all_connections: FxHashMap::default(),
        }
    }
    
    fn visit_neighbor(&mut self, neighbor: Uuid, current: Uuid, similarity: f32) {
        if !self.visited.contains(&neighbor) {
            self.visited.insert(neighbor);
            self.parent_map.insert(neighbor, (current, similarity));
            self.queue.push_back(neighbor);
            
            let current_layer = self.discovered_artists.get(&current).map(|(_, layer)| *layer).unwrap_or(0);
            self.discovered_artists.insert(neighbor, (similarity, current_layer + 1));
        }
    }
    
    fn explore_until_target_or_budget(&mut self, target: Uuid, budget: Option<usize>, graph_data: &memmap2::Mmap, graph_index: &FxHashMap<Uuid, u64>, config: &PathfindingConfig) -> Option<Vec<(Uuid, f32)>> {
        let mut primary_path = None;
        
        while let Some(current_artist) = self.queue.pop_front() {
            // Always check if we found the target first
            if primary_path.is_none() && current_artist == target {
                primary_path = Some(reconstruct_path(&self.parent_map, self.get_start_artist(), target));
                // If we have no budget constraint, we can stop here
                if budget.is_none() {
                    break;
                }
                // With budget constraint, continue exploring until budget is reached
            }
            
            let artist_connections = get_artist_connections(current_artist, graph_data, graph_index, config);
            self.all_connections.insert(current_artist, artist_connections.clone());
            
            for (neighbor_artist, similarity_score) in artist_connections {
                self.visit_neighbor(neighbor_artist, current_artist, similarity_score);
            }
            
            // Check budget after processing current artist and adding its neighbors
            if let Some(budget_limit) = budget {
                if self.discovered_artists.len() >= budget_limit {
                    return primary_path;
                }
            }
        }
        
        primary_path
    }
    
    fn get_start_artist(&self) -> Uuid {
        self.discovered_artists.iter()
            .find(|(_, (_, layer))| *layer == 0)
            .map(|(id, _)| *id)
            .expect("Start artist should always exist")
    }
}

pub fn bfs_find_path(
    start: Uuid,
    target: Uuid,
    graph_data: &memmap2::Mmap,
    graph_index: &FxHashMap<Uuid, u64>,
    config: &PathfindingConfig,
) -> PathResult {
    let search_timer = Instant::now();
    
    let mut bfs_state = BfsState::new(start);
    let path = bfs_state.explore_until_target_or_budget(target, None, graph_data, graph_index, config);
    
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
    
    // Phase 1: Find shortest path without budget constraints
    let mut path_finding_state = BfsState::new(start);
    let primary_path = path_finding_state.explore_until_target_or_budget(target, None, graph_data, graph_index, config);
    
    match primary_path {
        Some(path) => {
            let path_length = path.len();
            
            // Check if path length exceeds budget (can't even display the basic path)
            if path_length > budget {
                let duration_ms = search_timer.elapsed().as_millis() as u64;
                let artists_visited = path_finding_state.visited.len();
                EnhancedPathResult::PathTooLong {
                    primary_path: path,
                    path_length,
                    minimum_budget_needed: path_length,
                    artists_visited,
                    duration_ms,
                }
            } else {
                // Phase 2: Path fits in budget, do additional exploration within budget for display
                let mut exploration_state = BfsState::new(start);
                exploration_state.explore_until_target_or_budget(target, Some(budget), graph_data, graph_index, config);
                
                // Get connections for ALL discovered artists (like exploration does)
                let mut all_connections = FxHashMap::default();
                for &artist_id in exploration_state.discovered_artists.keys() {
                    let connections = get_artist_connections(artist_id, graph_data, graph_index, config);
                    all_connections.insert(artist_id, connections);
                }
                
                let duration_ms = search_timer.elapsed().as_millis() as u64;
                let artists_visited = exploration_state.visited.len();
                
                EnhancedPathResult::Success {
                    primary_path: path,
                    related_artists: exploration_state.discovered_artists,
                    connections: all_connections,
                    artists_visited,
                    duration_ms,
                }
            }
        },
        None => {
            // No path exists
            let duration_ms = search_timer.elapsed().as_millis() as u64;
            let artists_visited = path_finding_state.visited.len();
            EnhancedPathResult::NoPath {
                artists_visited,
                duration_ms,
            }
        }
    }
}

