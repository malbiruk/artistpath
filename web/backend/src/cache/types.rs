use std::time::{SystemTime, UNIX_EPOCH};
use uuid::Uuid;

pub const CACHE_TTL_SECONDS: i64 = 90 * 24 * 60 * 60; // 90 days

pub fn current_timestamp() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs() as i64
}

pub fn is_cache_valid(last_fetched: i64) -> bool {
    let current_time = current_timestamp();
    (current_time - last_fetched) < CACHE_TTL_SECONDS
}

#[derive(Debug, Clone)]
pub struct CacheKey {
    pub artist_id: Uuid,
    pub artist_name: String,
    pub artist_url: String,
}