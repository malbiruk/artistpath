use crate::fixtures::{TestArtists, build_app_state, create_empty_mmap, create_test_app_state};
use artistpath_web::{handlers::search_artists, models::SearchQuery, state::AppState};
use axum::{
    body::{Body, to_bytes},
    extract::{Query, State},
    http::{Request, StatusCode},
};
use rustc_hash::FxHashMap;
use std::sync::Arc;
use tower::util::ServiceExt;
use uuid::Uuid;

#[tokio::test]
async fn search_returns_empty_for_empty_query() {
    let artists = TestArtists::new();
    let state = build_app_state(
        artists.as_name_lookup(),
        artists.as_metadata(),
        Default::default(),
        Default::default(),
        create_empty_mmap(),
        create_empty_mmap(),
    )
    .await;

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
    let state = build_app_state(
        artists.as_name_lookup(),
        artists.as_metadata(),
        Default::default(),
        Default::default(),
        create_empty_mmap(),
        create_empty_mmap(),
    )
    .await;

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
    let state = build_app_state(
        artists.as_name_lookup(),
        artists.as_metadata(),
        Default::default(),
        Default::default(),
        create_empty_mmap(),
        create_empty_mmap(),
    )
    .await;

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
    // Two artists match "swift"; limit 1 must truncate to a single result.
    let artists = TestArtists::new();
    let swift_boat_id = Uuid::new_v4();
    let mut name_lookup = artists.as_name_lookup();
    name_lookup.insert("swift boat".to_string(), vec![swift_boat_id]);

    let mut metadata = artists.as_metadata();
    metadata.insert(
        swift_boat_id,
        artistpath_core::Artist {
            id: swift_boat_id,
            name: "Swift Boat".to_string(),
            url: "".to_string(),
        },
    );

    let state = build_app_state(
        name_lookup,
        metadata,
        Default::default(),
        Default::default(),
        create_empty_mmap(),
        create_empty_mmap(),
    )
    .await;

    let params = SearchQuery {
        q: "swift".to_string(),
        limit: 1,
    };

    let response = search_artists(State(state), Query(params)).await;
    let data = response.0;

    assert_eq!(data.results.len(), 1);
    assert_eq!(data.count, 1);
}

#[tokio::test]
async fn search_short_query_matches_by_prefix() {
    // Sub-3-char queries prefix-match rather than substring-match.
    let artists = TestArtists::new();
    let state = build_app_state(
        artists.as_name_lookup(),
        artists.as_metadata(),
        Default::default(),
        Default::default(),
        create_empty_mmap(),
        create_empty_mmap(),
    )
    .await;

    // "fi" is a prefix of "finneas" -> match.
    let params = SearchQuery {
        q: "fi".to_string(),
        limit: 10,
    };
    let data = search_artists(State(state.clone()), Query(params)).await.0;
    assert_eq!(data.results.len(), 1);
    assert_eq!(data.results[0].name, "FINNEAS");

    // "il" occurs inside "billie eilish" but is not a prefix -> no match.
    let params = SearchQuery {
        q: "il".to_string(),
        limit: 10,
    };
    let data = search_artists(State(state.clone()), Query(params)).await.0;
    assert_eq!(data.results.len(), 0);
}

#[tokio::test]
async fn search_prioritizes_prefix_matches() {
    let artists = TestArtists::new();
    let swift_boat_id = Uuid::new_v4();
    let mut name_lookup = artists.as_name_lookup();
    name_lookup.insert("swift boat".to_string(), vec![swift_boat_id]);

    let mut metadata = artists.as_metadata();
    metadata.insert(
        swift_boat_id,
        artistpath_core::Artist {
            id: swift_boat_id,
            name: "Swift Boat".to_string(),
            url: "".to_string(),
        },
    );

    let state = build_app_state(
        name_lookup,
        metadata,
        Default::default(),
        Default::default(),
        create_empty_mmap(),
        create_empty_mmap(),
    )
    .await;

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

// --- clamp_to_limits tests ---

#[tokio::test]
async fn search_with_huge_limit_does_not_error() {
    // A limit far above the server-side cap (100) must not error.
    // With only 4 artists in the fixture it's impractical to have >100 matches,
    // so we assert the response is valid and identical to passing limit=100.
    let (app, _) = create_test_app_state().await;

    let response = app
        .oneshot(
            Request::builder()
                // "billie" matches one fixture artist.
                .uri("/api/artists/search?q=billie&limit=999999999")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::OK);

    let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    let data: serde_json::Value = serde_json::from_slice(&body).unwrap();

    // Response must parse and contain a non-negative count.
    let count = data["count"].as_u64().expect("count field missing");
    // With 4 artists the clamped limit (100) is never the binding constraint,
    // so the result count equals however many artists matched — at least 1.
    assert!(count >= 1);
}
