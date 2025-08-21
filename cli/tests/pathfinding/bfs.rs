use artistpath::{bfs_find_path, Args};
use rustc_hash::FxHashMap;
use std::io::Write;
use tempfile::NamedTempFile;
use uuid::Uuid;

fn create_test_graph_file() -> (NamedTempFile, FxHashMap<String, u64>, Uuid, Uuid) {
    let mut file = NamedTempFile::new().unwrap();
    let alice_id = Uuid::new_v4();
    let bob_id = Uuid::new_v4();
    
    // Alice -> Bob
    let alice_line = format!(
        r#"{{"id": "{}", "connections": [["{}", 0.8]]}}"#,
        alice_id, bob_id
    );
    writeln!(file, "{}", alice_line).unwrap();
    
    // Bob -> Alice
    let bob_line = format!(
        r#"{{"id": "{}", "connections": [["{}", 0.8]]}}"#,
        bob_id, alice_id
    );
    writeln!(file, "{}", bob_line).unwrap();
    
    let mut index = FxHashMap::default();
    index.insert(alice_id.to_string(), 0);
    index.insert(bob_id.to_string(), alice_line.len() as u64 + 1);
    
    (file, index, alice_id, bob_id)
}

#[test]
fn test_bfs_find_direct_path() {
    let (file, index, alice_id, bob_id) = create_test_graph_file();
    
    let args = Args {
        artist1: "alice".to_string(),
        artist2: "bob".to_string(),
        min_match: 0.0,
        top_related: 80,
        weighted: false,
        show_similarity: false,
        hide_urls: false,
        show_ids: false,
    };
    
    let (path, visited_count, _) = bfs_find_path(
        alice_id, 
        bob_id, 
        file.path(), 
        &index, 
        &args
    );
    
    assert!(path.is_some());
    let path = path.unwrap();
    assert_eq!(path.len(), 2); // Alice -> Bob
    assert_eq!(path[0].0, alice_id);
    assert_eq!(path[1].0, bob_id);
    assert_eq!(visited_count, 2);
}

#[test]
fn test_bfs_no_path() {
    let mut file = NamedTempFile::new().unwrap();
    let alice_id = Uuid::new_v4();
    let bob_id = Uuid::new_v4();
    let isolated_id = Uuid::new_v4();
    
    // Alice -> Bob (but no connection to isolated)
    writeln!(
        file, 
        r#"{{"id": "{}", "connections": [["{}", 0.8]]}}"#,
        alice_id, bob_id
    ).unwrap();
    
    // Isolated node with no connections
    writeln!(
        file, 
        r#"{{"id": "{}", "connections": []}}"#,
        isolated_id
    ).unwrap();
    
    let mut index = FxHashMap::default();
    index.insert(alice_id.to_string(), 0);
    index.insert(isolated_id.to_string(), 100);
    
    let args = Args {
        artist1: "alice".to_string(),
        artist2: "isolated".to_string(),
        min_match: 0.0,
        top_related: 80,
        weighted: false,
        show_similarity: false,
        hide_urls: false,
        show_ids: false,
    };
    
    let (path, visited_count, _) = bfs_find_path(
        alice_id, 
        isolated_id, 
        file.path(), 
        &index, 
        &args
    );
    
    assert!(path.is_none());
    assert_eq!(visited_count, 2); // Visited Alice and Bob
}

#[test]
fn test_bfs_min_match_filter() {
    let (file, index, alice_id, bob_id) = create_test_graph_file();
    
    let args = Args {
        artist1: "alice".to_string(),
        artist2: "bob".to_string(),
        min_match: 0.9, // Higher than our 0.8 connection
        top_related: 80,
        weighted: false,
        show_similarity: false,
        hide_urls: false,
        show_ids: false,
    };
    
    let (path, _, _) = bfs_find_path(
        alice_id, 
        bob_id, 
        file.path(), 
        &index, 
        &args
    );
    
    assert!(path.is_none()); // Should be filtered out
}