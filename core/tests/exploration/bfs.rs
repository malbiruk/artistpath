use super::TestGraph;
use artistpath_core::explore_bfs;

#[test]
fn test_bfs_basic_exploration() {
    let graph = TestGraph::create();
    
    let result = explore_bfs(
        graph.taylor_id,
        5,
        2,
        0.0,
        &graph.mmap,
        &graph.graph_index,
    );
    
    assert!(result.discovered_artists.contains_key(&graph.taylor_id));
    assert!(result.total_discovered() > 0);
    assert!(result.total_discovered() <= 5);
    assert!(result.stats.artists_visited > 0);
}

#[test]
fn test_bfs_respects_budget() {
    let graph = TestGraph::create();
    
    let result = explore_bfs(
        graph.taylor_id,
        2,
        5,
        0.0,
        &graph.mmap,
        &graph.graph_index,
    );
    
    assert_eq!(result.total_discovered(), 2);
}

#[test]
fn test_bfs_layer_structure() {
    let graph = TestGraph::create();
    
    let result = explore_bfs(
        graph.taylor_id,
        4,
        2,
        0.0,
        &graph.mmap,
        &graph.graph_index,
    );
    
    let taylor_layer = result.discovered_artists.get(&graph.taylor_id).map(|(_, layer)| *layer);
    assert_eq!(taylor_layer, Some(0));
    
    let has_layer_1 = result.discovered_artists.values().any(|(_, layer)| *layer == 1);
    assert!(has_layer_1, "Should have artists at layer 1");
}

#[test]
fn test_bfs_similarity_filtering() {
    let graph = TestGraph::create();
    
    let high_sim_result = explore_bfs(
        graph.taylor_id,
        10,
        5,
        0.9,
        &graph.mmap,
        &graph.graph_index,
    );
    
    let low_sim_result = explore_bfs(
        graph.taylor_id,
        10,
        5,
        0.1,
        &graph.mmap,
        &graph.graph_index,
    );
    
    assert!(low_sim_result.total_discovered() >= high_sim_result.total_discovered());
}

#[test]
fn test_bfs_max_relations_limiting() {
    let graph = TestGraph::create();
    
    let limited_result = explore_bfs(
        graph.taylor_id,
        10,
        1,
        0.0,
        &graph.mmap,
        &graph.graph_index,
    );
    
    let unlimited_result = explore_bfs(
        graph.taylor_id,
        10,
        5,
        0.0,
        &graph.mmap,
        &graph.graph_index,
    );
    
    assert!(unlimited_result.total_discovered() >= limited_result.total_discovered());
}