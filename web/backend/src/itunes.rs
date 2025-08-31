use crate::models::{ITunesSearchResponse, ITunesTrack};
use reqwest::Client;
use std::collections::HashMap;
use std::time::{Duration, Instant};
use tokio::sync::Mutex;

pub struct ITunesClient {
    client: Client,
    cache: Mutex<HashMap<String, (ITunesSearchResponse, Instant)>>,
    cache_duration: Duration,
}

impl ITunesClient {
    pub fn new() -> Self {
        Self {
            client: Client::new(),
            cache: Mutex::new(HashMap::new()),
            cache_duration: Duration::from_secs(24 * 60 * 60), // 24 hours
        }
    }

    pub async fn search_track(
        &self,
        artist: &str,
        track: &str,
    ) -> Result<Option<ITunesTrack>, Box<dyn std::error::Error + Send + Sync>> {
        let cache_key = format!("{}:{}", artist, track);

        // Check cache first
        {
            let cache = self.cache.lock().await;
            if let Some((cached_response, cached_time)) = cache.get(&cache_key) {
                if cached_time.elapsed() < self.cache_duration {
                    return Ok(cached_response.results.first().cloned());
                }
            }
        }

        // Build search term
        let search_term = format!(
            "{}+{}",
            artist.replace(" ", "+").replace("&", "and"),
            track.replace(" ", "+").replace("&", "and")
        );

        let url = format!(
            "https://itunes.apple.com/search?term={}&media=music&entity=song&limit=1",
            search_term
        );

        let response = self
            .client
            .get(&url)
            .timeout(Duration::from_secs(10))
            .send()
            .await?;

        if !response.status().is_success() {
            return Ok(None);
        }

        let itunes_response: ITunesSearchResponse = response.json().await?;

        // Cache the response
        {
            let mut cache = self.cache.lock().await;
            cache.insert(cache_key, (itunes_response.clone(), Instant::now()));
        }

        Ok(itunes_response.results.first().cloned())
    }
}

impl Default for ITunesClient {
    fn default() -> Self {
        Self::new()
    }
}
