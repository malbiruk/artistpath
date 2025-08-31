use std::time::Duration;
use serde::{Deserialize, Serialize};
use reqwest::Client;
use moka::future::Cache;

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct LastFmArtistResponse {
    pub artist: LastFmArtist,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct LastFmArtist {
    pub name: String,
    pub mbid: Option<String>,
    pub url: String,
    pub image: Vec<LastFmImage>,
    pub stats: Option<LastFmStats>,
    pub tags: Option<LastFmTags>,
    pub bio: Option<LastFmBio>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct LastFmImage {
    #[serde(rename = "#text")]
    pub url: String,
    pub size: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct LastFmStats {
    pub listeners: String,
    pub playcount: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct LastFmTags {
    #[serde(default)]
    pub tag: Vec<LastFmTag>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct LastFmTag {
    pub name: String,
    pub url: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct LastFmBio {
    pub summary: String,
    pub content: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct LastFmTopTracksResponse {
    pub toptracks: LastFmTopTracks,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct LastFmTopTracks {
    pub track: Vec<LastFmTrack>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct LastFmTrack {
    pub name: String,
    pub url: String,
    pub playcount: String,
    pub listeners: String,
}

pub struct LastFmClient {
    client: Client,
    api_key: String,
    cache: Cache<String, String>, // Cache raw JSON responses
}

impl LastFmClient {
    pub fn new(api_key: String) -> Self {
        let cache = Cache::builder()
            .max_capacity(10_000)
            .time_to_live(Duration::from_secs(24 * 60 * 60)) // 24 hours
            .build();

        Self {
            client: Client::new(),
            api_key,
            cache,
        }
    }

    pub async fn get_artist_info(&self, artist_name: &str) -> Result<LastFmArtist, Box<dyn std::error::Error + Send + Sync>> {
        let cache_key = format!("artist_info:{}", artist_name);
        
        // Check cache first
        if let Some(cached_response) = self.cache.get(&cache_key).await {
            let response: LastFmArtistResponse = serde_json::from_str(&cached_response)?;
            return Ok(response.artist);
        }

        // Make API request
        let url = format!(
            "http://ws.audioscrobbler.com/2.0/?method=artist.getinfo&artist={}&api_key={}&format=json",
            urlencoding::encode(artist_name),
            self.api_key
        );

        let response = self.client.get(&url).send().await?;
        let response_text = response.text().await?;
        
        // Cache the raw response
        self.cache.insert(cache_key, response_text.clone()).await;

        // Parse and return
        let parsed_response: LastFmArtistResponse = serde_json::from_str(&response_text)?;
        Ok(parsed_response.artist)
    }

    pub async fn get_top_tracks(&self, artist_name: &str, limit: u32) -> Result<Vec<LastFmTrack>, Box<dyn std::error::Error + Send + Sync>> {
        let cache_key = format!("top_tracks:{}:{}", artist_name, limit);
        
        // Check cache first
        if let Some(cached_response) = self.cache.get(&cache_key).await {
            let response: LastFmTopTracksResponse = serde_json::from_str(&cached_response)?;
            return Ok(response.toptracks.track);
        }

        // Make API request
        let url = format!(
            "http://ws.audioscrobbler.com/2.0/?method=artist.gettoptracks&artist={}&api_key={}&format=json&limit={}",
            urlencoding::encode(artist_name),
            self.api_key,
            limit
        );

        let response = self.client.get(&url).send().await?;
        let response_text = response.text().await?;
        
        // Cache the raw response
        self.cache.insert(cache_key, response_text.clone()).await;

        // Parse and return
        let parsed_response: LastFmTopTracksResponse = serde_json::from_str(&response_text)?;
        Ok(parsed_response.toptracks.track)
    }
}