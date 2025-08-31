use artistpath_core::Algorithm;

#[test]
fn test_algorithm_enum_default() {
    assert_eq!(Algorithm::default(), Algorithm::Bfs);
}

#[test]
fn test_algorithm_from_str() {
    assert_eq!(Algorithm::from("bfs"), Algorithm::Bfs);
    assert_eq!(Algorithm::from("BFS"), Algorithm::Bfs);
    assert_eq!(Algorithm::from("dijkstra"), Algorithm::Dijkstra);
    assert_eq!(Algorithm::from("DIJKSTRA"), Algorithm::Dijkstra);
    assert_eq!(Algorithm::from("unknown"), Algorithm::Bfs); // Default to BFS
}

#[test]
fn test_algorithm_from_string() {
    assert_eq!(Algorithm::from("bfs".to_string()), Algorithm::Bfs);
    assert_eq!(Algorithm::from("dijkstra".to_string()), Algorithm::Dijkstra);
}

#[test]
fn test_algorithm_as_str() {
    assert_eq!(Algorithm::Bfs.as_str(), "bfs");
    assert_eq!(Algorithm::Dijkstra.as_str(), "dijkstra");
}

#[test]
fn test_algorithm_serde_serialization() {
    let bfs = Algorithm::Bfs;
    let dijkstra = Algorithm::Dijkstra;
    
    let bfs_json = serde_json::to_string(&bfs).unwrap();
    let dijkstra_json = serde_json::to_string(&dijkstra).unwrap();
    
    assert_eq!(bfs_json, r#""bfs""#);
    assert_eq!(dijkstra_json, r#""dijkstra""#);
}

#[test]
fn test_algorithm_serde_deserialization() {
    let bfs_result: Algorithm = serde_json::from_str(r#""bfs""#).unwrap();
    let dijkstra_result: Algorithm = serde_json::from_str(r#""dijkstra""#).unwrap();
    
    assert_eq!(bfs_result, Algorithm::Bfs);
    assert_eq!(dijkstra_result, Algorithm::Dijkstra);
}