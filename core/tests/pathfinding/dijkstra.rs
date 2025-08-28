use artistpath_core::{PathfindingConfig, dijkstra_find_path};
use byteorder::{LittleEndian, WriteBytesExt};
use rustc_hash::FxHashMap;
use std::io::{Seek, Write};
use tempfile::NamedTempFile;
use uuid::Uuid;

fn create_weighted_test_graph() -> (NamedTempFile, FxHashMap<Uuid, u64>, Uuid, Uuid, Uuid, Uuid) {
    let mut file = NamedTempFile::new().unwrap();
    let alice_id = Uuid::new_v4();
    let bob_id = Uuid::new_v4();
    let charlie_id = Uuid::new_v4();
    let dave_id = Uuid::new_v4();

    let mut index = FxHashMap::default();

    // Create a graph where:
    // Alice -> Bob (0.5) and Alice -> Charlie (0.9)
    // Bob -> Dave (0.8)
    // Charlie -> Dave (0.7)
    // Best similarity path: Alice -> Charlie -> Dave (total weight: 0.4)
    // Shortest hop path: Alice -> Bob -> Dave (total weight: 0.7)

    // Write Alice's data
    let alice_position = 0;
    index.insert(alice_id, alice_position);
    file.write_all(&alice_id.into_bytes()).unwrap();
    file.write_u32::<LittleEndian>(2).unwrap(); // 2 connections
    // Connection to Bob
    file.write_all(&bob_id.into_bytes()).unwrap();
    file.write_f32::<LittleEndian>(0.5).unwrap();
    // Connection to Charlie
    file.write_all(&charlie_id.into_bytes()).unwrap();
    file.write_f32::<LittleEndian>(0.9).unwrap();

    // Write Bob's data
    let bob_position = file.stream_position().unwrap();
    index.insert(bob_id, bob_position);
    file.write_all(&bob_id.into_bytes()).unwrap();
    file.write_u32::<LittleEndian>(1).unwrap(); // 1 connection
    // Connection to Dave
    file.write_all(&dave_id.into_bytes()).unwrap();
    file.write_f32::<LittleEndian>(0.8).unwrap();

    // Write Charlie's data
    let charlie_position = file.stream_position().unwrap();
    index.insert(charlie_id, charlie_position);
    file.write_all(&charlie_id.into_bytes()).unwrap();
    file.write_u32::<LittleEndian>(1).unwrap(); // 1 connection
    // Connection to Dave
    file.write_all(&dave_id.into_bytes()).unwrap();
    file.write_f32::<LittleEndian>(0.7).unwrap();

    // Write Dave's data (no outgoing connections)
    let dave_position = file.stream_position().unwrap();
    index.insert(dave_id, dave_position);
    file.write_all(&dave_id.into_bytes()).unwrap();
    file.write_u32::<LittleEndian>(0).unwrap(); // 0 connections

    file.flush().unwrap();

    (file, index, alice_id, bob_id, charlie_id, dave_id)
}

#[test]
fn test_dijkstra_finds_best_similarity_path() {
    let (file, index, alice_id, _bob_id, charlie_id, dave_id) = create_weighted_test_graph();

    let config = PathfindingConfig::new(0.0, 80, true);

    let (path, visited_count, _) = dijkstra_find_path(alice_id, dave_id, file.path(), &index, &config);

    assert!(path.is_some());
    let path = path.unwrap();
    assert_eq!(path.len(), 3); // Alice -> Charlie -> Dave
    assert_eq!(path[0].0, alice_id);
    assert_eq!(path[1].0, charlie_id);
    assert_eq!(path[2].0, dave_id);
    assert!(visited_count > 0);
}

#[test]
fn test_dijkstra_direct_connection() {
    let mut file = NamedTempFile::new().unwrap();
    let alice_id = Uuid::new_v4();
    let bob_id = Uuid::new_v4();

    let mut index = FxHashMap::default();

    // Direct connection: Alice -> Bob (0.95)
    let alice_position = 0;
    index.insert(alice_id, alice_position);
    file.write_all(&alice_id.into_bytes()).unwrap();
    file.write_u32::<LittleEndian>(1).unwrap();
    file.write_all(&bob_id.into_bytes()).unwrap();
    file.write_f32::<LittleEndian>(0.95).unwrap();

    // Bob has no outgoing connections
    let bob_position = file.stream_position().unwrap();
    index.insert(bob_id, bob_position);
    file.write_all(&bob_id.into_bytes()).unwrap();
    file.write_u32::<LittleEndian>(0).unwrap();

    file.flush().unwrap();

    let config = PathfindingConfig::new(0.0, 80, true);

    let (path, _, _) = dijkstra_find_path(alice_id, bob_id, file.path(), &index, &config);

    assert!(path.is_some());
    let path = path.unwrap();
    assert_eq!(path.len(), 2);
    assert_eq!(path[0].0, alice_id);
    assert_eq!(path[1].0, bob_id);
    assert_eq!(path[1].1, 0.95); // Similarity score
}

#[test]
fn test_dijkstra_no_path() {
    let mut file = NamedTempFile::new().unwrap();
    let alice_id = Uuid::new_v4();
    let isolated_id = Uuid::new_v4();

    let mut index = FxHashMap::default();

    // Alice has no connections
    let alice_position = 0;
    index.insert(alice_id, alice_position);
    file.write_all(&alice_id.into_bytes()).unwrap();
    file.write_u32::<LittleEndian>(0).unwrap();

    // Isolated node has no connections
    let isolated_position = file.stream_position().unwrap();
    index.insert(isolated_id, isolated_position);
    file.write_all(&isolated_id.into_bytes()).unwrap();
    file.write_u32::<LittleEndian>(0).unwrap();

    file.flush().unwrap();

    let config = PathfindingConfig::new(0.0, 80, true);

    let (path, visited_count, _) = dijkstra_find_path(alice_id, isolated_id, file.path(), &index, &config);

    assert!(path.is_none());
    assert_eq!(visited_count, 1); // Only visited Alice
}

#[test]
fn test_dijkstra_with_min_match_filter() {
    let (file, index, alice_id, _bob_id, _charlie_id, dave_id) = create_weighted_test_graph();

    let config = PathfindingConfig::new(0.75, 80, true); // Filters out Alice->Bob (0.5) and Charlie->Dave (0.7)

    let (path, _, _) = dijkstra_find_path(alice_id, dave_id, file.path(), &index, &config);

    // Path should be None because Charlie->Dave (0.7) is filtered out
    assert!(path.is_none());
}

#[test]
fn test_dijkstra_with_top_related_limit() {
    let mut file = NamedTempFile::new().unwrap();
    let alice_id = Uuid::new_v4();
    let bob_id = Uuid::new_v4();
    let charlie_id = Uuid::new_v4();

    let mut index = FxHashMap::default();

    // Alice has 2 connections but we'll limit to top 1
    let alice_position = 0;
    index.insert(alice_id, alice_position);
    file.write_all(&alice_id.into_bytes()).unwrap();
    file.write_u32::<LittleEndian>(2).unwrap();
    // Lower similarity to Bob
    file.write_all(&bob_id.into_bytes()).unwrap();
    file.write_f32::<LittleEndian>(0.3).unwrap();
    // Higher similarity to Charlie
    file.write_all(&charlie_id.into_bytes()).unwrap();
    file.write_f32::<LittleEndian>(0.9).unwrap();

    // Bob and Charlie have no connections
    let bob_position = file.stream_position().unwrap();
    index.insert(bob_id, bob_position);
    file.write_all(&bob_id.into_bytes()).unwrap();
    file.write_u32::<LittleEndian>(0).unwrap();

    let charlie_position = file.stream_position().unwrap();
    index.insert(charlie_id, charlie_position);
    file.write_all(&charlie_id.into_bytes()).unwrap();
    file.write_u32::<LittleEndian>(0).unwrap();

    file.flush().unwrap();

    let config = PathfindingConfig::new(0.0, 1, true); // Only take top 1 connection

    let (path, _, _) = dijkstra_find_path(alice_id, bob_id, file.path(), &index, &config);

    // Should be None because only Charlie (top connection) is kept
    assert!(path.is_none());
}