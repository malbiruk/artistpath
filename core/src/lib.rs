pub mod exploration;
pub mod parsing;
pub mod pathfinding;
pub mod pathfinding_config;
pub mod string_normalization;

// Re-export commonly used items
pub use exploration::{explore_bfs, explore_dijkstra, ExplorationResult, ExplorationStats};
pub use parsing::{Artist, find_artist_id, parse_unified_metadata};
pub use pathfinding::{bfs_find_path, dijkstra_find_path, get_artist_connections, find_paths_with_exploration_bfs, EnhancedPathResult};
pub use pathfinding_config::PathfindingConfig;

// Re-export PyO3 module when python feature is enabled
#[cfg(feature = "python")]
pub use string_normalization::normalization;