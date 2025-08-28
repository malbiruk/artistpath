use crate::models::{GraphEdge, GraphExploreResponse, GraphNode, PathArtist, SearchStats};
use crate::state::AppState;
use artistpath_core::{PathfindingConfig, get_artist_connections};
use rustc_hash::{FxHashMap, FxHashSet};
use std::time::Instant;
use uuid::Uuid;

// Maximum number of connections per artist in the graph data
const MAX_CONNECTIONS_PER_ARTIST: usize = 250;

pub struct ConnectionCache {
    cache: FxHashMap<Uuid, Vec<(Uuid, f32)>>,
    visited_count: usize,
}

impl ConnectionCache {
    pub fn new() -> Self {
        Self {
            cache: FxHashMap::default(),
            visited_count: 0,
        }
    }

    pub fn get_or_fetch(
        &mut self,
        artist_id: Uuid,
        state: &AppState,
        config: &PathfindingConfig,
    ) -> Vec<(Uuid, f32)> {
        if let Some(cached) = self.cache.get(&artist_id) {
            cached.clone()
        } else {
            let connections =
                get_artist_connections(artist_id, &state.graph_mmap, &state.graph_index, config);
            self.visited_count += 1;
            self.cache.insert(artist_id, connections.clone());
            connections
        }
    }

    pub fn visited_count(&self) -> usize {
        self.visited_count
    }
}

impl Default for ConnectionCache {
    fn default() -> Self {
        Self::new()
    }
}

pub struct ArtistExplorer<'a> {
    state: &'a AppState,
    config: PathfindingConfig,
    cache: ConnectionCache,
    visited: FxHashSet<Uuid>,
}

impl<'a> ArtistExplorer<'a> {
    pub fn new(state: &'a AppState, config: PathfindingConfig) -> Self {
        Self {
            state,
            config,
            cache: ConnectionCache::new(),
            visited: FxHashSet::default(),
        }
    }

    /// Explore network and return graph structure (nodes + edges)
    pub fn explore_as_graph(
        &mut self,
        center_id: Uuid,
        budget: usize,
        max_relations: usize,
    ) -> (Vec<GraphNode>, Vec<GraphEdge>) {
        let discovered_artists = self.discover_artists_bfs(center_id, budget, max_relations);
        let all_connections = self.get_all_connections(&discovered_artists, max_relations);

        let nodes = self.build_graph_nodes(&discovered_artists);
        let edges = self.build_graph_edges(&discovered_artists, &all_connections);

        (nodes, edges)
    }

    /// Discover artists using BFS until budget is reached
    fn discover_artists_bfs(
        &mut self,
        center_id: Uuid,
        budget: usize,
        max_relations: usize,
    ) -> FxHashMap<Uuid, (f32, usize)> {
        use std::collections::VecDeque;

        let mut queue: VecDeque<(Uuid, usize)> = VecDeque::new();
        let mut discovered: FxHashMap<Uuid, (f32, usize)> = FxHashMap::default();

        self.initialize_bfs(&mut queue, &mut discovered, center_id);

        let connection_config = self.create_connection_config(max_relations);

        while !queue.is_empty() && discovered.len() < budget {
            self.process_bfs_layer(
                &mut queue,
                &mut discovered,
                &connection_config,
                max_relations,
                budget,
            );
        }

        discovered
    }

    /// Initialize BFS with center artist
    fn initialize_bfs(
        &self,
        queue: &mut std::collections::VecDeque<(Uuid, usize)>,
        discovered: &mut FxHashMap<Uuid, (f32, usize)>,
        center_id: Uuid,
    ) {
        queue.push_back((center_id, 0));
        discovered.insert(center_id, (1.0, 0));
    }

    /// Create configuration for getting connections
    fn create_connection_config(&self, max_relations: usize) -> PathfindingConfig {
        PathfindingConfig::new(self.config.min_match, max_relations, false)
    }

    /// Process one layer of BFS
    fn process_bfs_layer(
        &mut self,
        queue: &mut std::collections::VecDeque<(Uuid, usize)>,
        discovered: &mut FxHashMap<Uuid, (f32, usize)>,
        connection_config: &PathfindingConfig,
        max_relations: usize,
        budget: usize,
    ) {
        let (current_id, current_layer) = queue.pop_front().unwrap();
        let connections = self.get_artist_connections(current_id, connection_config, max_relations);

        for (connected_id, similarity) in connections {
            if self.should_add_artist(discovered, connected_id, budget) {
                discovered.insert(connected_id, (similarity, current_layer + 1));
                queue.push_back((connected_id, current_layer + 1));
            }
        }
    }

    /// Get connections for an artist with proper caching
    fn get_artist_connections(
        &mut self,
        artist_id: Uuid,
        config: &PathfindingConfig,
        max_relations: usize,
    ) -> Vec<(Uuid, f32)> {
        let connections = if artist_id
            == self
                .state
                .artist_metadata
                .keys()
                .next()
                .copied()
                .unwrap_or(artist_id)
        {
            get_artist_connections(
                artist_id,
                &self.state.graph_mmap,
                &self.state.graph_index,
                config,
            )
        } else {
            self.cache.get_or_fetch(artist_id, self.state, config)
        };

        connections.into_iter().take(max_relations).collect()
    }

    /// Check if an artist should be added to the discovered set
    fn should_add_artist(
        &self,
        discovered: &FxHashMap<Uuid, (f32, usize)>,
        artist_id: Uuid,
        budget: usize,
    ) -> bool {
        !discovered.contains_key(&artist_id)
            && self.state.artist_metadata.contains_key(&artist_id)
            && discovered.len() < budget
    }

    /// Get all connections for discovered artists
    fn get_all_connections(
        &mut self,
        discovered: &FxHashMap<Uuid, (f32, usize)>,
        max_relations: usize,
    ) -> FxHashMap<Uuid, Vec<(Uuid, f32)>> {
        let mut all_connections = FxHashMap::default();
        let config = self.create_connection_config(max_relations);

        for &artist_id in discovered.keys() {
            let connections = self.get_artist_connections(artist_id, &config, max_relations);
            all_connections.insert(artist_id, connections);
        }

        all_connections
    }

    /// Build graph nodes from discovered artists
    fn build_graph_nodes(&self, discovered: &FxHashMap<Uuid, (f32, usize)>) -> Vec<GraphNode> {
        discovered
            .iter()
            .filter_map(|(&id, &(similarity, layer))| {
                self.state.artist_metadata.get(&id).map(|artist| GraphNode {
                    id,
                    name: artist.name.clone(),
                    layer,
                    similarity,
                    url: Some(artist.url.clone()),
                })
            })
            .collect()
    }

    /// Build graph edges from discovered artists and their connections
    fn build_graph_edges(
        &self,
        discovered: &FxHashMap<Uuid, (f32, usize)>,
        all_connections: &FxHashMap<Uuid, Vec<(Uuid, f32)>>,
    ) -> Vec<GraphEdge> {
        let mut edges = Vec::new();
        let discovered_ids: FxHashSet<Uuid> = discovered.keys().copied().collect();

        for (&from_id, connections) in all_connections {
            for &(to_id, similarity) in connections {
                if discovered_ids.contains(&to_id) && from_id != to_id {
                    edges.push(GraphEdge {
                        from: from_id,
                        to: to_id,
                        similarity,
                    });
                }
            }
        }

        edges
    }

    pub fn stats(&self) -> (usize, usize) {
        (self.cache.visited_count(), self.visited.len())
    }
}

/// Main exploration function returning graph structure
pub fn explore_artist_network_graph(
    center_id: Uuid,
    budget: usize,
    max_relations: usize,
    min_similarity: f32,
    state: &AppState,
) -> GraphExploreResponse {
    let start_time = Instant::now();

    let center_artist = build_center_artist_info(center_id, state);

    if center_artist.name == "Unknown Artist" {
        return build_empty_graph_response(center_artist, start_time);
    }

    let mut explorer = create_explorer(state, min_similarity);
    let (nodes, edges) = explorer.explore_as_graph(center_id, budget, max_relations);

    build_graph_response(center_artist, nodes, edges, explorer.stats(), start_time)
}

/// Build center artist information
fn build_center_artist_info(center_id: Uuid, state: &AppState) -> PathArtist {
    match state.artist_metadata.get(&center_id) {
        Some(artist) => PathArtist {
            id: artist.id,
            name: artist.name.clone(),
            url: artist.url.clone(),
            similarity: None,
        },
        None => PathArtist {
            id: center_id,
            name: "Unknown Artist".to_string(),
            url: "".to_string(),
            similarity: None,
        },
    }
}

/// Create explorer with proper configuration
fn create_explorer(state: &AppState, min_similarity: f32) -> ArtistExplorer {
    let config = PathfindingConfig::new(min_similarity, MAX_CONNECTIONS_PER_ARTIST, false);
    ArtistExplorer::new(state, config)
}

/// Build empty graph response for unknown artists
fn build_empty_graph_response(
    center_artist: PathArtist,
    start_time: Instant,
) -> GraphExploreResponse {
    GraphExploreResponse {
        center_artist,
        nodes: vec![],
        edges: vec![],
        total_found: 0,
        search_stats: SearchStats {
            artists_visited: 0,
            duration_ms: start_time.elapsed().as_millis() as u64,
        },
    }
}

/// Build complete graph response
fn build_graph_response(
    center_artist: PathArtist,
    nodes: Vec<GraphNode>,
    edges: Vec<GraphEdge>,
    stats: (usize, usize),
    start_time: Instant,
) -> GraphExploreResponse {
    let (artists_visited, _) = stats;
    let total_found = nodes.len(); // Actual number of discovered artists

    GraphExploreResponse {
        center_artist,
        nodes,
        edges,
        total_found,
        search_stats: SearchStats {
            artists_visited,
            duration_ms: start_time.elapsed().as_millis() as u64,
        },
    }
}
