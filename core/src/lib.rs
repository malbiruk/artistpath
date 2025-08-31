pub mod exploration;
pub mod parsing;
pub mod pathfinding;
pub mod pathfinding_config;
pub mod string_normalization;

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Algorithm {
    Bfs,
    Dijkstra,
}

impl Default for Algorithm {
    fn default() -> Self {
        Algorithm::Bfs
    }
}

impl Algorithm {
    pub fn as_str(&self) -> &'static str {
        match self {
            Algorithm::Bfs => "bfs",
            Algorithm::Dijkstra => "dijkstra",
        }
    }
}

impl From<&str> for Algorithm {
    fn from(s: &str) -> Self {
        match s.to_lowercase().as_str() {
            "dijkstra" => Algorithm::Dijkstra,
            _ => Algorithm::Bfs, // Default to BFS
        }
    }
}

impl From<String> for Algorithm {
    fn from(s: String) -> Self {
        Algorithm::from(s.as_str())
    }
}

// Re-export commonly used items
pub use exploration::{explore_bfs, explore_dijkstra, ExplorationResult, ExplorationStats};
pub use parsing::{Artist, find_artist_id, parse_unified_metadata};
pub use pathfinding::{bfs_find_path, dijkstra_find_path, get_artist_connections, find_paths_with_exploration, EnhancedPathResult};
pub use pathfinding_config::PathfindingConfig;

// Re-export PyO3 module when python feature is enabled
#[cfg(feature = "python")]
pub use string_normalization::normalization;