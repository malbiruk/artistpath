use super::ExplorationResult;
use crate::{PathfindingConfig, get_artist_connections};
use memmap2::Mmap;
use rustc_hash::FxHashMap;
use std::collections::VecDeque;
use std::time::Instant;
use uuid::Uuid;

pub fn explore_bfs(
    center_id: Uuid,
    budget: usize,
    max_relations: usize,
    min_similarity: f32,
    graph_mmap: &Mmap,
    graph_index: &FxHashMap<Uuid, u64>,
) -> ExplorationResult {
    let start_time = Instant::now();
    let mut explorer = BfsExplorer::new(min_similarity, max_relations, graph_mmap, graph_index);

    let discovered = explorer.discover_artists(center_id, budget);
    let connections = explorer.get_all_connections(&discovered);

    ExplorationResult::new(
        discovered,
        connections,
        explorer.artists_visited,
        start_time.elapsed().as_millis() as u64,
    )
}

struct BfsExplorer<'a> {
    config: PathfindingConfig,
    max_relations: usize,
    graph_mmap: &'a Mmap,
    graph_index: &'a FxHashMap<Uuid, u64>,
    connection_cache: FxHashMap<Uuid, Vec<(Uuid, f32)>>,
    artists_visited: usize,
}

impl<'a> BfsExplorer<'a> {
    fn new(
        min_similarity: f32,
        max_relations: usize,
        graph_mmap: &'a Mmap,
        graph_index: &'a FxHashMap<Uuid, u64>,
    ) -> Self {
        Self {
            config: PathfindingConfig::new(min_similarity, max_relations, false),
            max_relations,
            graph_mmap,
            graph_index,
            connection_cache: FxHashMap::default(),
            artists_visited: 0,
        }
    }

    fn discover_artists(
        &mut self,
        center_id: Uuid,
        budget: usize,
    ) -> FxHashMap<Uuid, (f32, usize)> {
        let mut queue = VecDeque::new();
        let mut discovered = FxHashMap::default();

        queue.push_back((center_id, 0));
        discovered.insert(center_id, (1.0, 0));

        while !queue.is_empty() && discovered.len() < budget {
            if let Some((current_id, current_layer)) = queue.pop_front() {
                let connections = self.get_cached_connections(current_id);

                for (connected_id, similarity) in connections {
                    if self.should_add_artist(&discovered, connected_id, budget) {
                        discovered.insert(connected_id, (similarity, current_layer + 1));
                        queue.push_back((connected_id, current_layer + 1));
                    }
                }
            }
        }

        discovered
    }

    fn get_cached_connections(&mut self, artist_id: Uuid) -> Vec<(Uuid, f32)> {
        if let Some(cached) = self.connection_cache.get(&artist_id) {
            cached.clone()
        } else {
            let connections =
                get_artist_connections(artist_id, self.graph_mmap, self.graph_index, &self.config);
            self.artists_visited += 1;

            let limited_connections: Vec<(Uuid, f32)> =
                connections.into_iter().take(self.max_relations).collect();

            self.connection_cache
                .insert(artist_id, limited_connections.clone());
            limited_connections
        }
    }

    fn should_add_artist(
        &self,
        discovered: &FxHashMap<Uuid, (f32, usize)>,
        artist_id: Uuid,
        budget: usize,
    ) -> bool {
        !discovered.contains_key(&artist_id)
            && self.graph_index.contains_key(&artist_id)
            && discovered.len() < budget
    }

    fn get_all_connections(
        &mut self,
        discovered: &FxHashMap<Uuid, (f32, usize)>,
    ) -> FxHashMap<Uuid, Vec<(Uuid, f32)>> {
        let mut all_connections = FxHashMap::default();

        for &artist_id in discovered.keys() {
            let connections = self.get_cached_connections(artist_id);
            all_connections.insert(artist_id, connections);
        }

        all_connections
    }
}
