use crate::fixtures::{TestArtists, create_empty_mmap, create_empty_cached_metadata};
use artistpath_web::{
    handlers::get_artist_details,
    models::{CachedArtistMetadata, CachedLastFmData, CachedTrackData},
    state::AppState,
};
use axum::{
    extract::{Path, State},
    http::StatusCode,
};
use rustc_hash::FxHashMap;
use std::sync::Arc;
use uuid::Uuid;

#[tokio::test]
async fn artist_details_returns_404_for_unknown_artist() {
    let artists = TestArtists::new();
    let state = Arc::new(AppState {
        name_lookup: artists.as_name_lookup(),
        artist_metadata: artists.as_metadata(),
        graph_index: Default::default(),
        graph_mmap: create_empty_mmap(),
        lastfm_client: artistpath_web::lastfm::LastFmClient::new("test_api_key".to_string()),
        itunes_client: artistpath_web::itunes::ITunesClient::new(),
        cached_metadata: create_empty_cached_metadata(),
    });

    let unknown_id = Uuid::new_v4();
    let result = get_artist_details(State(state), Path(unknown_id)).await;

    assert!(result.is_err());
    if let Err(status) = result {
        assert_eq!(status, StatusCode::NOT_FOUND);
    }
}

#[tokio::test]
async fn artist_details_returns_basic_info_without_cache() {
    let artists = TestArtists::new();
    let state = Arc::new(AppState {
        name_lookup: artists.as_name_lookup(),
        artist_metadata: artists.as_metadata(),
        graph_index: Default::default(),
        graph_mmap: create_empty_mmap(),
        lastfm_client: artistpath_web::lastfm::LastFmClient::new("test_api_key".to_string()),
        itunes_client: artistpath_web::itunes::ITunesClient::new(),
        cached_metadata: create_empty_cached_metadata(),
    });

    let taylor_id = artists.taylor.0;
    let result = get_artist_details(State(state), Path(taylor_id)).await;

    assert!(result.is_ok());
    let response = result.unwrap().0;
    
    assert_eq!(response.id, taylor_id);
    assert_eq!(response.name, "Taylor Swift");
    assert_eq!(response.url, "https://www.last.fm/music/Taylor+Swift");
    // Without cache and with test API key, external API calls will fail
    assert!(response.lastfm_data.is_none());
    assert!(response.top_tracks.is_none());
}

#[tokio::test]
async fn artist_details_uses_cached_data_when_available() {
    let artists = TestArtists::new();
    let taylor_id = artists.taylor.0;
    
    // Create cached metadata for Taylor Swift
    let mut cached_metadata = FxHashMap::default();
    cached_metadata.insert(taylor_id, CachedArtistMetadata {
        id: taylor_id.to_string(),
        name: "Taylor Swift".to_string(),
        url: "https://www.last.fm/music/Taylor+Swift".to_string(),
        last_fetched: 1234567890,
        lastfm: Some(CachedLastFmData {
            url: Some("https://www.last.fm/music/Taylor+Swift".to_string()),
            image_url: Some("https://lastfm.freetls.fastly.net/i/u/174s/taylor.jpg".to_string()),
            listeners: Some("5000000".to_string()),
            playcount: Some("100000000".to_string()),
            tags: vec!["pop".to_string(), "country".to_string()],
            bio_summary: Some("Taylor Swift is an American singer-songwriter.".to_string()),
            bio_full: Some("Taylor Swift is an American singer-songwriter known for narrative songs about her personal life.".to_string()),
        }),
        tracks: Some(vec![
            CachedTrackData {
                name: "Anti-Hero".to_string(),
                url: "https://www.last.fm/music/Taylor+Swift/_/Anti-Hero".to_string(),
                playcount: "50000000".to_string(),
                listeners: "2500000".to_string(),
                preview_url: Some("https://audio-ssl.itunes.apple.com/itunes-assets/preview.mp3".to_string()),
            },
            CachedTrackData {
                name: "Shake It Off".to_string(),
                url: "https://www.last.fm/music/Taylor+Swift/_/Shake+It+Off".to_string(),
                playcount: "45000000".to_string(),
                listeners: "2300000".to_string(),
                preview_url: None,
            },
        ]),
    });

    let state = Arc::new(AppState {
        name_lookup: artists.as_name_lookup(),
        artist_metadata: artists.as_metadata(),
        graph_index: Default::default(),
        graph_mmap: create_empty_mmap(),
        lastfm_client: artistpath_web::lastfm::LastFmClient::new("test_api_key".to_string()),
        itunes_client: artistpath_web::itunes::ITunesClient::new(),
        cached_metadata,
    });

    let result = get_artist_details(State(state), Path(taylor_id)).await;

    assert!(result.is_ok());
    let response = result.unwrap().0;
    
    // Basic artist info
    assert_eq!(response.id, taylor_id);
    assert_eq!(response.name, "Taylor Swift");
    assert_eq!(response.url, "https://www.last.fm/music/Taylor+Swift");
    
    // Cached Last.fm data should be present
    assert!(response.lastfm_data.is_some());
    let lastfm_data = response.lastfm_data.unwrap();
    assert_eq!(lastfm_data.name, "Taylor Swift");
    assert_eq!(lastfm_data.url, "https://www.last.fm/music/Taylor+Swift");
    assert_eq!(lastfm_data.image_url.as_ref().unwrap(), "https://lastfm.freetls.fastly.net/i/u/174s/taylor.jpg");
    assert_eq!(lastfm_data.listeners.as_ref().unwrap(), "5000000");
    assert_eq!(lastfm_data.plays.as_ref().unwrap(), "100000000");
    assert_eq!(lastfm_data.tags, vec!["pop", "country"]);
    assert_eq!(lastfm_data.bio_summary.as_ref().unwrap(), "Taylor Swift is an American singer-songwriter.");
    
    // Cached tracks should be present
    assert!(response.top_tracks.is_some());
    let tracks = response.top_tracks.unwrap();
    assert_eq!(tracks.len(), 2);
    
    assert_eq!(tracks[0].name, "Anti-Hero");
    assert_eq!(tracks[0].playcount, "50000000");
    assert_eq!(tracks[0].preview_url.as_ref().unwrap(), "https://audio-ssl.itunes.apple.com/itunes-assets/preview.mp3");
    
    assert_eq!(tracks[1].name, "Shake It Off");
    assert_eq!(tracks[1].playcount, "45000000");
    assert!(tracks[1].preview_url.is_none());
}

#[tokio::test]
async fn artist_details_handles_partial_cached_data() {
    let artists = TestArtists::new();
    let olivia_id = artists.olivia.0;
    
    // Create cached metadata with only Last.fm data, no tracks
    let mut cached_metadata = FxHashMap::default();
    cached_metadata.insert(olivia_id, CachedArtistMetadata {
        id: olivia_id.to_string(),
        name: "Olivia Rodrigo".to_string(),
        url: "https://www.last.fm/music/Olivia+Rodrigo".to_string(),
        last_fetched: 1234567890,
        lastfm: Some(CachedLastFmData {
            url: Some("https://www.last.fm/music/Olivia+Rodrigo".to_string()),
            image_url: None,
            listeners: Some("3000000".to_string()),
            playcount: Some("80000000".to_string()),
            tags: vec!["pop".to_string(), "indie".to_string()],
            bio_summary: None,
            bio_full: None,
        }),
        tracks: None, // No cached tracks
    });

    let state = Arc::new(AppState {
        name_lookup: artists.as_name_lookup(),
        artist_metadata: artists.as_metadata(),
        graph_index: Default::default(),
        graph_mmap: create_empty_mmap(),
        lastfm_client: artistpath_web::lastfm::LastFmClient::new("test_api_key".to_string()),
        itunes_client: artistpath_web::itunes::ITunesClient::new(),
        cached_metadata,
    });

    let result = get_artist_details(State(state), Path(olivia_id)).await;

    assert!(result.is_ok());
    let response = result.unwrap().0;
    
    // Should have Last.fm data from cache
    assert!(response.lastfm_data.is_some());
    let lastfm_data = response.lastfm_data.unwrap();
    assert_eq!(lastfm_data.listeners.as_ref().unwrap(), "3000000");
    assert!(lastfm_data.image_url.is_none());
    assert!(lastfm_data.bio_summary.is_none());
    
    // Should not have tracks (not cached, and API calls will fail with test key)
    assert!(response.top_tracks.is_none());
}

#[tokio::test]
async fn artist_details_falls_back_when_no_cache() {
    let artists = TestArtists::new();
    let billie_id = artists.billie.0;
    
    // Empty cache - should fall back to live API calls
    let state = Arc::new(AppState {
        name_lookup: artists.as_name_lookup(),
        artist_metadata: artists.as_metadata(),
        graph_index: Default::default(),
        graph_mmap: create_empty_mmap(),
        lastfm_client: artistpath_web::lastfm::LastFmClient::new("test_api_key".to_string()),
        itunes_client: artistpath_web::itunes::ITunesClient::new(),
        cached_metadata: create_empty_cached_metadata(),
    });

    let result = get_artist_details(State(state), Path(billie_id)).await;

    assert!(result.is_ok());
    let response = result.unwrap().0;
    
    // Basic info should be present
    assert_eq!(response.id, billie_id);
    assert_eq!(response.name, "Billie Eilish");
    
    // API calls will fail with test key, so external data should be None
    assert!(response.lastfm_data.is_none());
    assert!(response.top_tracks.is_none());
}