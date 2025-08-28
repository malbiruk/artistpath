use crate::fixtures::create_test_app_state;
use artistpath_web::models::{GraphExploreResponse, GraphNode};
use axum::{
    body::{Body, to_bytes},
    http::{Request, StatusCode},
};
use tower::util::ServiceExt;

/// Test basic explore functionality
#[tokio::test]
async fn test_explore_basic() {
    let (app, test_artists) = create_test_app_state().await;

    let response = app
        .oneshot(
            Request::builder()
                .uri(format!(
                    "/api/explore?artist_id={}&budget=5&max_relations=2",
                    test_artists.taylor.0
                ))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::OK);

    let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    let explore_response: GraphExploreResponse = serde_json::from_slice(&body).unwrap();

    // Should return valid graph structure
    assert_eq!(explore_response.center_artist.name, "Taylor Swift");
    assert!(!explore_response.nodes.is_empty());
    assert!(explore_response.nodes.len() <= 5); // Respects budget
    assert!(!explore_response.edges.is_empty());
    assert!(explore_response.total_found > 0);
    assert_eq!(explore_response.total_found, explore_response.nodes.len());
}

/// Test budget limiting
#[tokio::test]
async fn test_explore_budget_limiting() {
    let (app, test_artists) = create_test_app_state().await;

    // Test with small budget
    let response = app
        .oneshot(
            Request::builder()
                .uri(format!(
                    "/api/explore?artist_id={}&budget=3&max_relations=5",
                    test_artists.taylor.0
                ))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    let explore_response: GraphExploreResponse = serde_json::from_slice(&body).unwrap();

    // Should respect budget
    assert!(explore_response.nodes.len() <= 3);
    assert_eq!(explore_response.total_found, explore_response.nodes.len());
}

/// Test max_relations parameter
#[tokio::test]
async fn test_explore_max_relations() {
    let (app, test_artists) = create_test_app_state().await;

    // Test with different max_relations values
    let test_cases = vec![
        (1, "max_relations=1"),
        (3, "max_relations=3"),
        (5, "max_relations=5"),
    ];

    for (max_relations, description) in test_cases {
        let response = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri(format!(
                        "/api/explore?artist_id={}&budget=10&max_relations={}",
                        test_artists.taylor.0, max_relations
                    ))
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(
            response.status(),
            StatusCode::OK,
            "Failed for {}",
            description
        );

        let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
        let explore_response: GraphExploreResponse = serde_json::from_slice(&body).unwrap();

        // Higher max_relations should generally discover more artists (up to budget)
        assert!(
            !explore_response.nodes.is_empty(),
            "No nodes found for {}",
            description
        );
        assert!(
            !explore_response.edges.is_empty(),
            "No edges found for {}",
            description
        );
    }
}

/// Test graph structure integrity
#[tokio::test]
async fn test_explore_graph_integrity() {
    let (app, test_artists) = create_test_app_state().await;

    let response = app
        .oneshot(
            Request::builder()
                .uri(format!(
                    "/api/explore?artist_id={}&budget=10&max_relations=3",
                    test_artists.taylor.0
                ))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    let explore_response: GraphExploreResponse = serde_json::from_slice(&body).unwrap();

    // Collect all node IDs
    let node_ids: std::collections::HashSet<uuid::Uuid> =
        explore_response.nodes.iter().map(|n| n.id).collect();

    // Verify all edges connect valid nodes
    for edge in &explore_response.edges {
        assert!(
            node_ids.contains(&edge.from),
            "Edge from unknown node: {}",
            edge.from
        );
        assert!(
            node_ids.contains(&edge.to),
            "Edge to unknown node: {}",
            edge.to
        );
        assert!(
            edge.similarity >= 0.0 && edge.similarity <= 1.0,
            "Invalid similarity: {}",
            edge.similarity
        );
    }

    // Verify node structure
    for node in &explore_response.nodes {
        assert!(!node.name.is_empty(), "Empty node name");
        assert!(
            node.similarity >= 0.0 && node.similarity <= 1.0,
            "Invalid node similarity: {}",
            node.similarity
        );
        assert!(node.layer < 10, "Unreasonable layer depth: {}", node.layer); // Sanity check
    }

    // Center artist should be in layer 0
    let center_nodes: Vec<&GraphNode> = explore_response
        .nodes
        .iter()
        .filter(|n| n.layer == 0)
        .collect();
    assert_eq!(center_nodes.len(), 1, "Should have exactly one center node");
    assert_eq!(center_nodes[0].id, test_artists.taylor.0);
}

/// Test layer distribution
#[tokio::test]
async fn test_explore_layer_distribution() {
    let (app, test_artists) = create_test_app_state().await;

    let response = app
        .oneshot(
            Request::builder()
                .uri(format!(
                    "/api/explore?artist_id={}&budget=15&max_relations=3",
                    test_artists.taylor.0
                ))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    let explore_response: GraphExploreResponse = serde_json::from_slice(&body).unwrap();

    // Group nodes by layer
    let mut layer_counts: std::collections::BTreeMap<usize, usize> =
        std::collections::BTreeMap::new();
    for node in &explore_response.nodes {
        *layer_counts.entry(node.layer).or_insert(0) += 1;
    }

    // Should have center at layer 0
    assert_eq!(
        layer_counts.get(&0),
        Some(&1),
        "Should have exactly 1 node at layer 0"
    );

    // Should have reasonable layer progression
    let max_layer = *layer_counts.keys().max().unwrap();
    assert!(max_layer < 5, "Layers too deep: {}", max_layer);

    // Each layer should have some nodes (except possibly the deepest)
    for layer in 0..max_layer {
        assert!(layer_counts.contains_key(&layer), "Missing layer {}", layer);
    }
}

/// Test unknown artist handling
#[tokio::test]
async fn test_explore_unknown_artist() {
    let (app, _) = create_test_app_state().await;

    let unknown_id = uuid::Uuid::new_v4();
    let response = app
        .oneshot(
            Request::builder()
                .uri(format!(
                    "/api/explore?artist_id={}&budget=10&max_relations=3",
                    unknown_id
                ))
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::OK);

    let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    let explore_response: GraphExploreResponse = serde_json::from_slice(&body).unwrap();

    // Should handle gracefully
    assert_eq!(explore_response.center_artist.name, "Unknown Artist");
    assert_eq!(explore_response.nodes.len(), 0);
    assert_eq!(explore_response.edges.len(), 0);
    assert_eq!(explore_response.total_found, 0);
}

/// Test parameter validation
#[tokio::test]
async fn test_explore_parameter_validation() {
    let (app, test_artists) = create_test_app_state().await;

    // Test with missing required parameter
    let response = app
        .clone()
        .oneshot(
            Request::builder()
                .uri("/api/explore?budget=10&max_relations=3") // Missing artist_id
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::BAD_REQUEST);

    // Test with valid parameters
    let response = app
        .oneshot(
            Request::builder()
                .uri(format!("/api/explore?artist_id={}", test_artists.taylor.0)) // Only required param
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::OK);
}

/// Test performance and reasonable response times
#[tokio::test]
async fn test_explore_performance() {
    let (app, test_artists) = create_test_app_state().await;

    let start = std::time::Instant::now();

    let response = app
        .oneshot(
            Request::builder()
                .uri(format!(
                    "/api/explore?artist_id={}&budget=20&max_relations=5",
                    test_artists.taylor.0
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
    let explore_response: GraphExploreResponse = serde_json::from_slice(&body).unwrap();

    // Response should include timing information
    assert!(
        explore_response.search_stats.duration_ms < 1000,
        "Reported duration too slow: {}ms",
        explore_response.search_stats.duration_ms
    );
    assert!(
        explore_response.search_stats.artists_visited > 0,
        "Should visit some artists"
    );
}
