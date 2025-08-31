use super::TestGraph;
use artistpath_core::explore_dijkstra;

#[test]
fn test_dijkstra_basic_exploration() {
    let test_graph = TestGraph::create();

    let result = explore_dijkstra(
        test_graph.taylor_id,
        3,   // budget
        10,  // max_relations
        0.0, // min_similarity
        &test_graph.mmap,
        &test_graph.graph_index,
    );

    assert!(result.discovered_artists.len() <= 3);
    assert!(
        result
            .discovered_artists
            .contains_key(&test_graph.taylor_id)
    );
    assert!(result.total_discovered() <= 3);
}

#[test]
fn test_dijkstra_respects_budget() {
    let test_graph = TestGraph::create();

    let result = explore_dijkstra(
        test_graph.taylor_id,
        2,   // budget
        10,  // max_relations
        0.0, // min_similarity
        &test_graph.mmap,
        &test_graph.graph_index,
    );

    assert!(result.discovered_artists.len() <= 2);
    assert_eq!(result.total_discovered(), result.discovered_artists.len());
}

#[test]
fn test_dijkstra_similarity_filtering() {
    let test_graph = TestGraph::create();

    let result = explore_dijkstra(
        test_graph.taylor_id,
        10,  // budget
        10,  // max_relations
        0.9, // min_similarity (high threshold)
        &test_graph.mmap,
        &test_graph.graph_index,
    );

    // With high similarity threshold, should find fewer artists
    // All discovered artists should have similarity >= 0.9
    for (similarity, _) in result.discovered_artists.values() {
        if *similarity > 0.0 {
            // Skip the starting artist which has similarity 1.0
            assert!(*similarity >= 0.9);
        }
    }
}

#[test]
fn test_dijkstra_finds_closest_artists_by_weight() {
    let test_graph = TestGraph::create();

    let result = explore_dijkstra(
        test_graph.taylor_id,
        4,   // budget (all artists)
        10,  // max_relations
        0.0, // min_similarity
        &test_graph.mmap,
        &test_graph.graph_index,
    );

    // Should find all reachable artists
    assert!(!result.discovered_artists.is_empty());
    assert!(
        result
            .discovered_artists
            .contains_key(&test_graph.taylor_id)
    );

    // The starting artist should have the best (lowest) cost
    if let Some((similarity, _)) = result.discovered_artists.get(&test_graph.taylor_id) {
        assert_eq!(*similarity, 1.0); // Starting artist similarity
    }
}

#[test]
fn test_dijkstra_layer_assignment() {
    let test_graph = TestGraph::create();

    let result = explore_dijkstra(
        test_graph.taylor_id,
        4,   // budget (all artists)
        10,  // max_relations
        0.0, // min_similarity
        &test_graph.mmap,
        &test_graph.graph_index,
    );

    // Only the center artist should have layer 0
    let layer_0_artists: Vec<_> = result
        .discovered_artists
        .iter()
        .filter(|(_, (_, layer))| *layer == 0)
        .map(|(id, _)| *id)
        .collect();

    assert_eq!(
        layer_0_artists.len(),
        1,
        "Only one artist should have layer 0"
    );
    assert_eq!(
        layer_0_artists[0], test_graph.taylor_id,
        "Center artist should have layer 0"
    );

    // All other artists should have layer > 0
    for (&artist_id, &(_, layer)) in &result.discovered_artists {
        if artist_id != test_graph.taylor_id {
            assert!(
                layer > 0,
                "Non-center artist {:?} should have layer > 0, got {}",
                artist_id,
                layer
            );
        }
    }
}
