pub mod args;
pub mod colors;
pub mod parsing;
pub mod pathfinding;
pub mod string_normalization;
pub mod utils;

// Re-export commonly used items
pub use args::Args;
pub use parsing::{Artist, find_artist_id, parse_unified_metadata};
pub use pathfinding::{bfs_find_path, dijkstra_find_path};
pub use utils::format_number;
