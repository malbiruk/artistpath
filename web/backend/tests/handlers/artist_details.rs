use crate::fixtures::{TestArtists, create_empty_mmap, create_test_metadata_cache};
use artistpath_web::{
    handlers::get_artist_details,
    state::AppState,
};
use axum::{
    extract::{Path, State},
    http::StatusCode,
};
use std::sync::Arc;
use uuid::Uuid;

#[tokio::test]
async fn artist_details_returns_404_for_unknown_artist() {
    let artists = TestArtists::new();
    let state = Arc::new(AppState {
        name_lookup: artists.as_name_lookup(),
        artist_metadata: artists.as_metadata(),
        graph_index: Default::default(),
        reverse_graph_index: Default::default(),
        graph_mmap: create_empty_mmap(),
        reverse_graph_mmap: create_empty_mmap(),
        metadata_cache: create_test_metadata_cache().await,
    });

    let unknown_id = Uuid::new_v4();
    let result = get_artist_details(State(state), Path(unknown_id)).await;

    assert!(result.is_err());
    if let Err(status) = result {
        assert_eq!(status, StatusCode::NOT_FOUND);
    }
}

#[tokio::test]
async fn artist_details_returns_basic_info_without_external_data() {
    let artists = TestArtists::new();
    let state = Arc::new(AppState {
        name_lookup: artists.as_name_lookup(),
        artist_metadata: artists.as_metadata(),
        graph_index: Default::default(),
        reverse_graph_index: Default::default(),
        graph_mmap: create_empty_mmap(),
        reverse_graph_mmap: create_empty_mmap(),
        metadata_cache: create_test_metadata_cache().await,
    });

    let taylor_id = artists.taylor.0;
    let result = get_artist_details(State(state), Path(taylor_id)).await;

    assert!(result.is_ok());
    let response = result.unwrap().0;
    
    assert_eq!(response.id, taylor_id);
    assert_eq!(response.name, "Taylor Swift");
    assert_eq!(response.url, "https://www.last.fm/music/Taylor+Swift");
    // With test API key, external API calls will fail, so external data should be None
    assert!(response.lastfm_data.is_none());
    assert!(response.top_tracks.is_none());
}

#[tokio::test]
async fn artist_details_handles_all_test_artists() {
    let artists = TestArtists::new();
    let state = Arc::new(AppState {
        name_lookup: artists.as_name_lookup(),
        artist_metadata: artists.as_metadata(),
        graph_index: Default::default(),
        reverse_graph_index: Default::default(),
        graph_mmap: create_empty_mmap(),
        reverse_graph_mmap: create_empty_mmap(),
        metadata_cache: create_test_metadata_cache().await,
    });

    // Test each artist
    for (artist_id, artist) in [
        (artists.taylor.0, &artists.taylor.1),
        (artists.olivia.0, &artists.olivia.1),
        (artists.billie.0, &artists.billie.1),
        (artists.finneas.0, &artists.finneas.1),
    ] {
        let result = get_artist_details(State(state.clone()), Path(artist_id)).await;
        assert!(result.is_ok(), "Failed for artist: {}", artist.name);
        
        let response = result.unwrap().0;
        assert_eq!(response.id, artist_id);
        assert_eq!(response.name, artist.name);
        assert_eq!(response.url, artist.url);
    }
}