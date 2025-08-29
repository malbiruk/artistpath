use crate::fixtures::create_test_app_state;
use artistpath_web::models::EnhancedPathResponse;
use axum::body::to_bytes;
use axum::{
    body::Body,
    http::{Request, StatusCode},
};
use tower::util::ServiceExt;

#[tokio::test]
async fn test_enhanced_path_success() {
    let (app, test_artists) = create_test_app_state().await;

    let response = app
        .oneshot(
            Request::builder()
                .uri(format!(
                    "/api/enhanced_path?from_id={}&to_id={}&budget=10",
                    test_artists.taylor.0, test_artists.billie.0
                ))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::OK);

    let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    let enhanced_response: EnhancedPathResponse = serde_json::from_slice(&body).unwrap();

    assert_eq!(enhanced_response.status, "success");
    assert!(enhanced_response.data.is_some());

    let data = enhanced_response.data.unwrap();
    assert!(!data.primary_path.is_empty());
    assert_eq!(data.primary_path[0].id, test_artists.taylor.0);
    assert_eq!(data.primary_path.last().unwrap().id, test_artists.billie.0);
    assert!(!data.nodes.is_empty());
    assert!(data.total_artists <= 10);
}

#[tokio::test]
async fn test_enhanced_path_respects_budget() {
    let (app, test_artists) = create_test_app_state().await;

    let response = app
        .oneshot(
            Request::builder()
                .uri(format!(
                    "/api/enhanced_path?from_id={}&to_id={}&budget=3",
                    test_artists.taylor.0, test_artists.olivia.0
                ))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::OK);

    let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    let enhanced_response: EnhancedPathResponse = serde_json::from_slice(&body).unwrap();

    // Should be either success with <= 3 artists or path_too_long
    if enhanced_response.status == "success" {
        let data = enhanced_response.data.unwrap();
        assert!(data.total_artists <= 3);
    } else if enhanced_response.status == "path_too_long" {
        assert!(enhanced_response.error.is_some());
        let error = enhanced_response.error.unwrap();
        assert_eq!(error.error_type, "path_too_long");
        assert!(error.minimum_budget_needed.is_some());
    }
}

#[tokio::test]
async fn test_enhanced_path_with_similarity_filter() {
    let (app, test_artists) = create_test_app_state().await;

    let response = app
        .oneshot(
            Request::builder()
                .uri(format!(
                    "/api/enhanced_path?from_id={}&to_id={}&budget=10&min_similarity=0.7",
                    test_artists.taylor.0, test_artists.finneas.0
                ))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::OK);

    let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    let enhanced_response: EnhancedPathResponse = serde_json::from_slice(&body).unwrap();

    if enhanced_response.status == "success" {
        let data = enhanced_response.data.unwrap();
        // All edges should respect the similarity filter
        for edge in &data.edges {
            assert!(edge.similarity >= 0.7);
        }
    }
}

#[tokio::test]
async fn test_enhanced_path_no_path() {
    let (app, test_artists) = create_test_app_state().await;
    let isolated_id = uuid::Uuid::new_v4(); // Non-existent artist

    let response = app
        .oneshot(
            Request::builder()
                .uri(format!(
                    "/api/enhanced_path?from_id={}&to_id={}&budget=10",
                    test_artists.taylor.0, isolated_id
                ))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::OK);

    let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    let enhanced_response: EnhancedPathResponse = serde_json::from_slice(&body).unwrap();

    assert_eq!(enhanced_response.status, "no_path");
    assert!(enhanced_response.error.is_some());
    let error = enhanced_response.error.unwrap();
    assert_eq!(error.error_type, "no_path");
    assert!(error.primary_path.is_none());
}

#[tokio::test]
async fn test_enhanced_path_budget_too_low() {
    let (app, test_artists) = create_test_app_state().await;

    let response = app
        .oneshot(
            Request::builder()
                .uri(format!(
                    "/api/enhanced_path?from_id={}&to_id={}&budget=2",
                    test_artists.taylor.0, test_artists.billie.0
                ))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::OK);

    let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    let enhanced_response: EnhancedPathResponse = serde_json::from_slice(&body).unwrap();

    // With budget=2, should get path_too_long (path needs 3 artists: Taylor->Olivia->Billie)
    assert_eq!(enhanced_response.status, "path_too_long");
    assert!(enhanced_response.error.is_some());

    let error = enhanced_response.error.unwrap();
    assert_eq!(error.error_type, "path_too_long");
    assert!(error.primary_path.is_some());
    assert!(error.minimum_budget_needed.is_some());
    assert!(error.minimum_budget_needed.unwrap() > 2);
}

#[tokio::test]
async fn test_enhanced_path_with_max_relations() {
    let (app, test_artists) = create_test_app_state().await;

    let response = app
        .oneshot(
            Request::builder()
                .uri(format!(
                    "/api/enhanced_path?from_id={}&to_id={}&budget=10&max_relations=2",
                    test_artists.taylor.0, test_artists.billie.0
                ))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::OK);

    let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    let enhanced_response: EnhancedPathResponse = serde_json::from_slice(&body).unwrap();

    // Should still find a path but exploration will be limited
    assert!(enhanced_response.search_stats.artists_visited > 0);
}

#[tokio::test]
async fn test_enhanced_path_default_parameters() {
    let (app, test_artists) = create_test_app_state().await;

    let response = app
        .oneshot(
            Request::builder()
                .uri(format!(
                    "/api/enhanced_path?from_id={}&to_id={}",
                    test_artists.taylor.0, test_artists.billie.0
                ))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::OK);

    let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    let enhanced_response: EnhancedPathResponse = serde_json::from_slice(&body).unwrap();

    // Should work with default budget=100
    assert_eq!(enhanced_response.status, "success");
}

#[tokio::test]
async fn test_enhanced_path_graph_structure() {
    let (app, test_artists) = create_test_app_state().await;

    let response = app
        .oneshot(
            Request::builder()
                .uri(format!(
                    "/api/enhanced_path?from_id={}&to_id={}&budget=10",
                    test_artists.taylor.0, test_artists.billie.0
                ))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::OK);

    let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    let enhanced_response: EnhancedPathResponse = serde_json::from_slice(&body).unwrap();

    if enhanced_response.status == "success" {
        let data = enhanced_response.data.unwrap();

        // Verify graph structure
        let node_ids: std::collections::HashSet<_> = data.nodes.iter().map(|n| n.id).collect();

        // All edge endpoints should be in nodes
        for edge in &data.edges {
            assert!(node_ids.contains(&edge.from));
            assert!(node_ids.contains(&edge.to));
            assert!(edge.from != edge.to); // No self-loops
        }

        // All path artists should be in nodes
        for artist in &data.primary_path {
            assert!(node_ids.contains(&artist.id));
        }
    }
}
