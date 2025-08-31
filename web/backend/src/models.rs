use serde::{Deserialize, Serialize};
use uuid::Uuid;
use artistpath_core::Algorithm;

#[derive(Serialize)]
pub struct HealthResponse {
    pub status: String,
    pub message: String,
}

#[derive(Serialize)]
pub struct ArtistSearchResult {
    pub id: Uuid,
    pub name: String,
    pub url: String,
}

#[derive(Serialize)]
pub struct SearchResponse {
    pub query: String,
    pub results: Vec<ArtistSearchResult>,
    pub count: usize,
}

#[derive(Deserialize)]
pub struct SearchQuery {
    pub q: String,
    #[serde(default = "default_limit")]
    pub limit: usize,
}

fn default_limit() -> usize {
    10
}

#[derive(Deserialize)]
pub struct PathQuery {
    pub from_id: Uuid,
    pub to_id: Uuid,
    #[serde(default)]
    pub algorithm: Algorithm,
    #[serde(default)]
    pub min_similarity: f32,
    #[serde(default = "default_max_relations")]
    pub max_relations: usize,
}

#[derive(Serialize, Deserialize)]
pub struct PathArtist {
    pub id: Uuid,
    pub name: String,
    pub url: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub similarity: Option<f32>,
}

#[derive(Serialize, Deserialize)]
pub struct SearchStats {
    pub artists_visited: usize,
    pub duration_ms: u64,
}

#[derive(Serialize, Deserialize)]
pub struct PathResponse {
    pub path: Option<Vec<PathArtist>>,
    pub artist_count: usize,
    pub step_count: usize,
    pub algorithm: Algorithm,
    pub search_stats: SearchStats,
}

#[derive(Serialize)]
pub struct StatsResponse {
    pub total_artists: usize,
}

#[derive(Deserialize)]
pub struct ExploreQuery {
    pub artist_id: Uuid,
    #[serde(default)]
    pub algorithm: Algorithm,
    #[serde(default)]
    pub min_similarity: f32,
    #[serde(default = "default_max_relations")]
    pub max_relations: usize,
    #[serde(default = "default_budget")]
    pub budget: usize,
}

#[derive(Serialize, Deserialize)]
pub struct GraphNode {
    pub id: Uuid,
    pub name: String,
    pub layer: usize,
    pub similarity: f32,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub url: Option<String>,
}

#[derive(Serialize, Deserialize)]
pub struct GraphEdge {
    pub from: Uuid,
    pub to: Uuid,
    pub similarity: f32,
}

#[derive(Serialize, Deserialize)]
pub struct GraphExploreResponse {
    pub center_artist: PathArtist,
    pub nodes: Vec<GraphNode>,
    pub edges: Vec<GraphEdge>,
    pub total_found: usize,
    pub search_stats: SearchStats,
}


fn default_max_relations() -> usize {
    80
}

fn default_budget() -> usize {
    100
}

#[derive(Deserialize)]
pub struct EnhancedPathQuery {
    pub from_id: Uuid,
    pub to_id: Uuid,
    #[serde(default)]
    pub algorithm: Algorithm,
    #[serde(default)]
    pub min_similarity: f32,
    #[serde(default = "default_max_relations")]
    pub max_relations: usize,
    #[serde(default = "default_budget")]
    pub budget: usize,
}

#[derive(Serialize, Deserialize)]
pub struct EnhancedPathResponse {
    pub status: String,
    pub data: Option<EnhancedPathData>,
    pub error: Option<EnhancedPathError>,
    pub search_stats: SearchStats,
}

#[derive(Serialize, Deserialize)]
pub struct EnhancedPathData {
    pub primary_path: Vec<PathArtist>,
    pub nodes: Vec<GraphNode>,
    pub edges: Vec<GraphEdge>,
    pub total_artists: usize,
}

#[derive(Serialize, Deserialize)]
pub struct EnhancedPathError {
    pub error_type: String,
    pub message: String,
    pub path_length: Option<usize>,
    pub minimum_budget_needed: Option<usize>,
    pub primary_path: Option<Vec<PathArtist>>,
}

