/// Configuration for pathfinding algorithms
#[derive(Debug, Clone)]
pub struct PathfindingConfig {
    /// Only use connections with similarity >= threshold (0.0-1.0)
    pub min_match: f32,
    /// Limit to top N connections per artist
    pub top_related: usize,
    /// Use weighted pathfinding for best similarity (default: shortest path)
    pub weighted: bool,
}

impl PathfindingConfig {
    pub fn new(min_match: f32, top_related: usize, weighted: bool) -> Self {
        Self {
            min_match,
            top_related,
            weighted,
        }
    }
}

impl Default for PathfindingConfig {
    fn default() -> Self {
        Self {
            min_match: 0.0,
            top_related: 80,
            weighted: false,
        }
    }
}