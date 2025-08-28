use serde::{Deserialize, Serialize};
use uuid::Uuid;

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
    #[serde(default = "default_algorithm")]
    pub algorithm: String,
    #[serde(default)]
    pub min_similarity: f32,
    #[serde(default = "default_max_relations")]
    pub max_relations: usize,
}

#[derive(Serialize)]
pub struct PathArtist {
    pub id: Uuid,
    pub name: String,
    pub url: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub similarity: Option<f32>,
}

#[derive(Serialize)]
pub struct SearchStats {
    pub artists_visited: usize,
    pub duration_ms: u64,
}

#[derive(Serialize)]
pub struct PathResponse {
    pub path: Option<Vec<PathArtist>>,
    pub artist_count: usize,
    pub step_count: usize,
    pub algorithm: String,
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
    pub min_similarity: f32,
    #[serde(default = "default_max_relations")]
    pub max_relations: usize,
    #[serde(default = "default_budget")]
    pub budget: usize,
}

#[derive(Serialize)]
pub struct ExploreArtist {
    pub id: Uuid,
    pub name: String,
    pub url: String,
    pub similarity: f32,
    pub related_artists: Vec<ExploreArtist>,
}

#[derive(Serialize)]
pub struct ExploreResponse {
    pub center_artist: PathArtist,
    pub related_artists: Vec<ExploreArtist>,
    pub total_found: usize,
    pub search_stats: SearchStats,
}

fn default_algorithm() -> String {
    "bfs".to_string()
}

fn default_max_relations() -> usize {
    80
}

fn default_budget() -> usize {
    100
}
