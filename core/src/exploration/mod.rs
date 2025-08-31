pub mod bfs;
pub mod dijkstra;

pub use bfs::explore_bfs;
pub use dijkstra::explore_dijkstra;

use rustc_hash::FxHashMap;
use uuid::Uuid;

#[derive(Debug, Clone)]
pub struct ExplorationResult {
    pub discovered_artists: FxHashMap<Uuid, (f32, usize)>,
    pub connections: FxHashMap<Uuid, Vec<(Uuid, f32)>>,
    pub stats: ExplorationStats,
}

#[derive(Debug, Clone)]
pub struct ExplorationStats {
    pub artists_visited: usize,
    pub duration_ms: u64,
}

impl ExplorationResult {
    pub fn new(
        discovered_artists: FxHashMap<Uuid, (f32, usize)>,
        connections: FxHashMap<Uuid, Vec<(Uuid, f32)>>,
        artists_visited: usize,
        duration_ms: u64,
    ) -> Self {
        Self {
            discovered_artists,
            connections,
            stats: ExplorationStats {
                artists_visited,
                duration_ms,
            },
        }
    }

    pub fn total_discovered(&self) -> usize {
        self.discovered_artists.len()
    }
}