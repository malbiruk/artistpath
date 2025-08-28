use crate::fixtures::create_test_app_state;
use artistpath_web::models::PathResponse;
use axum::{
    body::{Body, to_bytes},
    http::{Request, StatusCode},
};
use tower::util::ServiceExt;

/// Test basic pathfinding functionality
#[tokio::test]
async fn test_path_basic() {
    let (app, test_artists) = create_test_app_state().await;

    let response = app
        .oneshot(
            Request::builder()
                .uri(format!(
                    "/api/path?from_id={}&to_id={}",
                    test_artists.taylor.0, test_artists.billie.0
                ))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::OK);

    let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    let path_response: PathResponse = serde_json::from_slice(&body).unwrap();

    // Should find a path
    assert!(path_response.path.is_some());
    let path = path_response.path.unwrap();
    assert!(path.len() >= 2); // At least from and to
    assert_eq!(path[0].id, test_artists.taylor.0); // First should be Taylor
    assert_eq!(path[path.len() - 1].id, test_artists.billie.0); // Last should be Billie

    assert_eq!(path_response.artist_count, path.len());
    assert_eq!(path_response.step_count, path.len().saturating_sub(1));
    assert_eq!(path_response.algorithm, "bfs"); // Default algorithm
    assert!(path_response.search_stats.artists_visited > 0);
}

/// Test BFS vs Dijkstra algorithms
#[tokio::test]
async fn test_path_algorithms() {
    let (app, test_artists) = create_test_app_state().await;

    // Test BFS
    let bfs_response = app
        .clone()
        .oneshot(
            Request::builder()
                .uri(format!(
                    "/api/path?from_id={}&to_id={}&algorithm=bfs",
                    test_artists.taylor.0, test_artists.billie.0
                ))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(bfs_response.status(), StatusCode::OK);
    let bfs_body = to_bytes(bfs_response.into_body(), usize::MAX)
        .await
        .unwrap();
    let bfs_path: PathResponse = serde_json::from_slice(&bfs_body).unwrap();
    assert_eq!(bfs_path.algorithm, "bfs");

    // Test Dijkstra
    let dijkstra_response = app
        .oneshot(
            Request::builder()
                .uri(format!(
                    "/api/path?from_id={}&to_id={}&algorithm=dijkstra",
                    test_artists.taylor.0, test_artists.billie.0
                ))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(dijkstra_response.status(), StatusCode::OK);
    let dijkstra_body = to_bytes(dijkstra_response.into_body(), usize::MAX)
        .await
        .unwrap();
    let dijkstra_path: PathResponse = serde_json::from_slice(&dijkstra_body).unwrap();
    assert_eq!(dijkstra_path.algorithm, "dijkstra");
}

/// Test same artist (from = to)
#[tokio::test]
async fn test_path_same_artist() {
    let (app, test_artists) = create_test_app_state().await;

    let response = app
        .oneshot(
            Request::builder()
                .uri(format!(
                    "/api/path?from_id={}&to_id={}",
                    test_artists.taylor.0, test_artists.taylor.0
                ))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::OK);

    let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    let path_response: PathResponse = serde_json::from_slice(&body).unwrap();

    // Should have a path with just the single artist
    assert!(path_response.path.is_some());
    let path = path_response.path.unwrap();
    assert_eq!(path.len(), 1);
    assert_eq!(path[0].id, test_artists.taylor.0);
    assert_eq!(path_response.artist_count, 1);
    assert_eq!(path_response.step_count, 0);
}

/// Test unknown artist handling
#[tokio::test]
async fn test_path_unknown_artists() {
    let (app, test_artists) = create_test_app_state().await;

    let unknown_id = uuid::Uuid::new_v4();

    // Unknown from_id
    let response = app
        .clone()
        .oneshot(
            Request::builder()
                .uri(format!(
                    "/api/path?from_id={}&to_id={}",
                    unknown_id, test_artists.taylor.0
                ))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::OK);
    let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    let path_response: PathResponse = serde_json::from_slice(&body).unwrap();
    assert!(path_response.path.is_none());
    assert_eq!(path_response.artist_count, 0);
    assert_eq!(path_response.step_count, 0);

    // Unknown to_id
    let response = app
        .oneshot(
            Request::builder()
                .uri(format!(
                    "/api/path?from_id={}&to_id={}",
                    test_artists.taylor.0, unknown_id
                ))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::OK);
    let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    let path_response: PathResponse = serde_json::from_slice(&body).unwrap();
    assert!(path_response.path.is_none());
}

/// Test parameter validation
#[tokio::test]
async fn test_path_parameter_validation() {
    let (app, _) = create_test_app_state().await;

    // Missing required parameters
    let response = app
        .clone()
        .oneshot(
            Request::builder()
                .uri("/api/path?from_id=20244d07-534f-4eff-b4d4-930878889970") // Missing to_id
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::BAD_REQUEST);

    // Invalid UUID format
    let response = app
        .oneshot(
            Request::builder()
                .uri("/api/path?from_id=invalid-uuid&to_id=20244d07-534f-4eff-b4d4-930878889970")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
}

/// Test path response structure
#[tokio::test]
async fn test_path_response_structure() {
    let (app, test_artists) = create_test_app_state().await;

    let response = app
        .oneshot(
            Request::builder()
                .uri(format!(
                    "/api/path?from_id={}&to_id={}",
                    test_artists.taylor.0, test_artists.olivia.0
                ))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    let path_response: PathResponse = serde_json::from_slice(&body).unwrap();

    // Verify response structure
    if let Some(path) = &path_response.path {
        for artist in path {
            assert!(!artist.name.is_empty());
            assert!(!artist.url.is_empty());
            // Similarity is optional and only present for non-starting artists
        }
    }

    // Verify counts are consistent
    if let Some(path) = &path_response.path {
        assert_eq!(path_response.artist_count, path.len());
        assert_eq!(path_response.step_count, path.len().saturating_sub(1));
    } else {
        assert_eq!(path_response.artist_count, 0);
        assert_eq!(path_response.step_count, 0);
    }
}

/// Test min_similarity parameter
#[tokio::test]
async fn test_path_min_similarity() {
    let (app, test_artists) = create_test_app_state().await;

    // Test with very high min_similarity (should make path harder to find)
    let response = app
        .clone()
        .oneshot(
            Request::builder()
                .uri(format!(
                    "/api/path?from_id={}&to_id={}&min_similarity=0.9",
                    test_artists.taylor.0, test_artists.billie.0
                ))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::OK);

    // Test with low min_similarity (should be more permissive)
    let response = app
        .oneshot(
            Request::builder()
                .uri(format!(
                    "/api/path?from_id={}&to_id={}&min_similarity=0.1",
                    test_artists.taylor.0, test_artists.olivia.0
                ))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    let path_response: PathResponse = serde_json::from_slice(&body).unwrap();

    // With low similarity, should likely find a path
    assert!(path_response.path.is_some());
}

/// Test max_relations parameter
#[tokio::test]
async fn test_path_max_relations() {
    let (app, test_artists) = create_test_app_state().await;

    // Test with limited max_relations
    let response = app
        .clone()
        .oneshot(
            Request::builder()
                .uri(format!(
                    "/api/path?from_id={}&to_id={}&max_relations=1",
                    test_artists.taylor.0, test_artists.billie.0
                ))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::OK);

    // Test with higher max_relations
    let response = app
        .oneshot(
            Request::builder()
                .uri(format!(
                    "/api/path?from_id={}&to_id={}&max_relations=5",
                    test_artists.taylor.0, test_artists.olivia.0
                ))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    let path_response: PathResponse = serde_json::from_slice(&body).unwrap();

    // Should likely find a direct path with higher max_relations
    assert!(path_response.path.is_some());
}

/// Test performance
#[tokio::test]
async fn test_path_performance() {
    let (app, test_artists) = create_test_app_state().await;

    let start = std::time::Instant::now();

    let response = app
        .oneshot(
            Request::builder()
                .uri(format!(
                    "/api/path?from_id={}&to_id={}",
                    test_artists.taylor.0, test_artists.finneas.0
                ))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    let duration = start.elapsed();

    assert_eq!(response.status(), StatusCode::OK);
    assert!(
        duration.as_millis() < 1000,
        "Request too slow: {}ms",
        duration.as_millis()
    );

    let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    let path_response: PathResponse = serde_json::from_slice(&body).unwrap();

    // Response should include reasonable timing information
    assert!(
        path_response.search_stats.duration_ms < 1000,
        "Reported duration too slow: {}ms",
        path_response.search_stats.duration_ms
    );
}
