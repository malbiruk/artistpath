use crate::fixtures::{TestArtists, create_empty_mmap};
use artistpath_web::{handlers::search_artists, models::SearchQuery, state::AppState};
use axum::extract::{Query, State};
use std::sync::Arc;
use uuid::Uuid;

#[tokio::test]
async fn search_returns_empty_for_empty_query() {
    let artists = TestArtists::new();
    let state = Arc::new(AppState {
        name_lookup: artists.as_name_lookup(),
        artist_metadata: artists.as_metadata(),
        graph_index: Default::default(),
        graph_mmap: create_empty_mmap(),
        lastfm_client: artistpath_web::lastfm::LastFmClient::new("test_api_key".to_string()),
        itunes_client: artistpath_web::itunes::ITunesClient::new(),
    });

    let params = SearchQuery {
        q: "".to_string(),
        limit: 10,
    };

    let response = search_artists(State(state), Query(params)).await;
    let data = response.0;

    assert_eq!(data.results.len(), 0);
    assert_eq!(data.count, 0);
    assert_eq!(data.query, "");
}

#[tokio::test]
async fn search_finds_exact_match() {
    let artists = TestArtists::new();
    let state = Arc::new(AppState {
        name_lookup: artists.as_name_lookup(),
        artist_metadata: artists.as_metadata(),
        graph_index: Default::default(),
        graph_mmap: create_empty_mmap(),
        lastfm_client: artistpath_web::lastfm::LastFmClient::new("test_api_key".to_string()),
        itunes_client: artistpath_web::itunes::ITunesClient::new(),
    });

    let params = SearchQuery {
        q: "taylor swift".to_string(),
        limit: 10,
    };

    let response = search_artists(State(state), Query(params)).await;
    let data = response.0;

    assert_eq!(data.results.len(), 1);
    assert_eq!(data.results[0].name, "Taylor Swift");
    assert_eq!(data.count, 1);
}

#[tokio::test]
async fn search_finds_partial_match() {
    let artists = TestArtists::new();
    let state = Arc::new(AppState {
        name_lookup: artists.as_name_lookup(),
        artist_metadata: artists.as_metadata(),
        graph_index: Default::default(),
        graph_mmap: create_empty_mmap(),
        lastfm_client: artistpath_web::lastfm::LastFmClient::new("test_api_key".to_string()),
        itunes_client: artistpath_web::itunes::ITunesClient::new(),
    });

    let params = SearchQuery {
        q: "billie".to_string(),
        limit: 10,
    };

    let response = search_artists(State(state), Query(params)).await;
    let data = response.0;

    assert_eq!(data.results.len(), 1);
    assert_eq!(data.results[0].name, "Billie Eilish");
}

#[tokio::test]
async fn search_respects_limit() {
    let artists = TestArtists::new();
    let state = Arc::new(AppState {
        name_lookup: artists.as_name_lookup(),
        artist_metadata: artists.as_metadata(),
        graph_index: Default::default(),
        graph_mmap: create_empty_mmap(),
        lastfm_client: artistpath_web::lastfm::LastFmClient::new("test_api_key".to_string()),
        itunes_client: artistpath_web::itunes::ITunesClient::new(),
    });

    // Search for something that matches multiple artists
    let params = SearchQuery {
        q: "i".to_string(), // matches Olivia, Billie
        limit: 1,
    };

    let response = search_artists(State(state), Query(params)).await;
    let data = response.0;

    assert_eq!(data.results.len(), 1);
    assert_eq!(data.count, 1);
}

#[tokio::test]
async fn search_prioritizes_prefix_matches() {
    let artists = TestArtists::new();
    let swift_boat_id = Uuid::new_v4();
    let mut name_lookup = artists.as_name_lookup();
    name_lookup.insert("swift boat".to_string(), swift_boat_id);

    let mut metadata = artists.as_metadata();
    metadata.insert(
        swift_boat_id,
        artistpath_core::Artist {
            id: swift_boat_id,
            name: "Swift Boat".to_string(),
            url: "".to_string(),
        },
    );

    let state = Arc::new(AppState {
        name_lookup,
        artist_metadata: metadata,
        graph_index: Default::default(),
        graph_mmap: create_empty_mmap(),
        lastfm_client: artistpath_web::lastfm::LastFmClient::new("test_api_key".to_string()),
        itunes_client: artistpath_web::itunes::ITunesClient::new(),
    });

    let params = SearchQuery {
        q: "swift".to_string(),
        limit: 10,
    };

    let response = search_artists(State(state), Query(params)).await;
    let data = response.0;

    // "Swift Boat" should come first because it starts with "swift"
    assert!(data.results.len() >= 2);
    assert_eq!(data.results[0].name, "Swift Boat");
}
