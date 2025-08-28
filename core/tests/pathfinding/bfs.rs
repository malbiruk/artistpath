use artistpath_core::{PathfindingConfig, bfs_find_path};
use byteorder::{LittleEndian, WriteBytesExt};
use rustc_hash::FxHashMap;
use std::io::{Seek, Write};
use tempfile::NamedTempFile;
use uuid::Uuid;

fn create_test_binary_file() -> (NamedTempFile, FxHashMap<Uuid, u64>, Uuid, Uuid) {
    let mut file = NamedTempFile::new().unwrap();
    let alice_id = Uuid::new_v4();
    let bob_id = Uuid::new_v4();

    let mut index = FxHashMap::default();

    // Write Alice's data to binary file
    let alice_position = 0;
    index.insert(alice_id, alice_position);

    // Alice UUID (16 bytes)
    file.write_all(&alice_id.into_bytes()).unwrap();
    // Connection count (4 bytes)
    file.write_u32::<LittleEndian>(1).unwrap(); // 1 connection
    // Bob's UUID (16 bytes) + weight (4 bytes)
    file.write_all(&bob_id.into_bytes()).unwrap();
    file.write_f32::<LittleEndian>(0.8).unwrap();

    // Write Bob's data to binary file
    let bob_position = file.stream_position().unwrap();
    index.insert(bob_id, bob_position);

    // Bob UUID (16 bytes)
    file.write_all(&bob_id.into_bytes()).unwrap();
    // Connection count (4 bytes)
    file.write_u32::<LittleEndian>(1).unwrap(); // 1 connection
    // Alice's UUID (16 bytes) + weight (4 bytes)
    file.write_all(&alice_id.into_bytes()).unwrap();
    file.write_f32::<LittleEndian>(0.8).unwrap();

    file.flush().unwrap();

    (file, index, alice_id, bob_id)
}

#[test]
fn test_bfs_find_direct_path() {
    let (file, index, alice_id, bob_id) = create_test_binary_file();

    let config = PathfindingConfig::new(0.0, 80, false);

    let (path, visited_count, _) = bfs_find_path(alice_id, bob_id, file.path(), &index, &config);

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

    let mut index = FxHashMap::default();

    // Write Alice's data (connects to Bob)
    let alice_position = 0;
    index.insert(alice_id, alice_position);

    file.write_all(&alice_id.into_bytes()).unwrap();
    file.write_u32::<LittleEndian>(1).unwrap(); // 1 connection
    file.write_all(&bob_id.into_bytes()).unwrap();
    file.write_f32::<LittleEndian>(0.8).unwrap();

    // Write isolated node (no connections)
    let isolated_position = file.stream_position().unwrap();
    index.insert(isolated_id, isolated_position);

    file.write_all(&isolated_id.into_bytes()).unwrap();
    file.write_u32::<LittleEndian>(0).unwrap(); // 0 connections

    file.flush().unwrap();

    let config = PathfindingConfig::new(0.0, 80, false);

    let (path, visited_count, _) = bfs_find_path(alice_id, isolated_id, file.path(), &index, &config);

    assert!(path.is_none());
    assert_eq!(visited_count, 2); // Visited Alice and Bob
}

#[test]
fn test_bfs_min_match_filter() {
    let (file, index, alice_id, bob_id) = create_test_binary_file();

    let config = PathfindingConfig::new(0.9, 80, false); // Higher than our 0.8 connection

    let (path, _, _) = bfs_find_path(alice_id, bob_id, file.path(), &index, &config);

    assert!(path.is_none()); // Should be filtered out
}
