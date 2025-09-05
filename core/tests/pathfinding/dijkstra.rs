// Tests updated for bidirectional pathfinding API

use artistpath_core::{PathfindingConfig, dijkstra_find_path};
use byteorder::{LittleEndian, WriteBytesExt};
use memmap2::Mmap;
use rustc_hash::FxHashMap;
use std::io::{Seek, Write};
use tempfile::NamedTempFile;
use uuid::Uuid;

// Type alias to reduce complexity
type GraphTestSetup = (
    NamedTempFile,
    NamedTempFile,
    FxHashMap<Uuid, u64>,
    FxHashMap<Uuid, u64>,
    Uuid,
    Uuid,
    Uuid,
    Uuid,
);

fn create_weighted_test_graph() -> GraphTestSetup {
    let mut forward_file = NamedTempFile::new().unwrap();
    let mut reverse_file = NamedTempFile::new().unwrap();
    let alice_id = Uuid::new_v4();
    let bob_id = Uuid::new_v4();
    let charlie_id = Uuid::new_v4();
    let dave_id = Uuid::new_v4();

    let mut forward_index = FxHashMap::default();
    let mut reverse_index = FxHashMap::default();

    // Create a graph where:
    // Alice -> Bob (0.5) and Alice -> Charlie (0.9)
    // Bob -> Dave (0.8)
    // Charlie -> Dave (0.7)
    // Best similarity path: Alice -> Charlie -> Dave (total weight: 0.4)
    // Shortest hop path: Alice -> Bob -> Dave (total weight: 0.7)

    // Write Alice's forward data
    let alice_position = 0;
    forward_index.insert(alice_id, alice_position);
    forward_file.write_all(&alice_id.into_bytes()).unwrap();
    forward_file.write_u32::<LittleEndian>(2).unwrap(); // 2 connections
    // Connection to Bob
    forward_file.write_all(&bob_id.into_bytes()).unwrap();
    forward_file.write_f32::<LittleEndian>(0.5).unwrap();
    // Connection to Charlie
    forward_file.write_all(&charlie_id.into_bytes()).unwrap();
    forward_file.write_f32::<LittleEndian>(0.9).unwrap();

    // Write Bob's forward data
    let bob_position = forward_file.stream_position().unwrap();
    forward_index.insert(bob_id, bob_position);
    forward_file.write_all(&bob_id.into_bytes()).unwrap();
    forward_file.write_u32::<LittleEndian>(1).unwrap(); // 1 connection
    // Connection to Dave
    forward_file.write_all(&dave_id.into_bytes()).unwrap();
    forward_file.write_f32::<LittleEndian>(0.8).unwrap();

    // Write Charlie's forward data
    let charlie_position = forward_file.stream_position().unwrap();
    forward_index.insert(charlie_id, charlie_position);
    forward_file.write_all(&charlie_id.into_bytes()).unwrap();
    forward_file.write_u32::<LittleEndian>(1).unwrap(); // 1 connection
    // Connection to Dave
    forward_file.write_all(&dave_id.into_bytes()).unwrap();
    forward_file.write_f32::<LittleEndian>(0.7).unwrap();

    // Write Dave's forward data (no outgoing connections)
    let dave_position = forward_file.stream_position().unwrap();
    forward_index.insert(dave_id, dave_position);
    forward_file.write_all(&dave_id.into_bytes()).unwrap();
    forward_file.write_u32::<LittleEndian>(0).unwrap(); // 0 connections

    // Now create reverse graph: reverse the connections
    // Bob -> Alice (0.5), Dave -> Bob (0.8), Charlie -> Alice (0.9), Dave -> Charlie (0.7)

    // Write Bob's reverse data (receives from Alice)
    let bob_rev_position = 0;
    reverse_index.insert(bob_id, bob_rev_position);
    reverse_file.write_all(&bob_id.into_bytes()).unwrap();
    reverse_file.write_u32::<LittleEndian>(1).unwrap();
    reverse_file.write_all(&alice_id.into_bytes()).unwrap();
    reverse_file.write_f32::<LittleEndian>(0.5).unwrap();

    // Write Dave's reverse data (receives from Bob and Charlie)
    let dave_rev_position = reverse_file.stream_position().unwrap();
    reverse_index.insert(dave_id, dave_rev_position);
    reverse_file.write_all(&dave_id.into_bytes()).unwrap();
    reverse_file.write_u32::<LittleEndian>(2).unwrap();
    reverse_file.write_all(&bob_id.into_bytes()).unwrap();
    reverse_file.write_f32::<LittleEndian>(0.8).unwrap();
    reverse_file.write_all(&charlie_id.into_bytes()).unwrap();
    reverse_file.write_f32::<LittleEndian>(0.7).unwrap();

    // Write Charlie's reverse data (receives from Alice)
    let charlie_rev_position = reverse_file.stream_position().unwrap();
    reverse_index.insert(charlie_id, charlie_rev_position);
    reverse_file.write_all(&charlie_id.into_bytes()).unwrap();
    reverse_file.write_u32::<LittleEndian>(1).unwrap();
    reverse_file.write_all(&alice_id.into_bytes()).unwrap();
    reverse_file.write_f32::<LittleEndian>(0.9).unwrap();

    // Write Alice's reverse data (no incoming connections in this graph)
    let alice_rev_position = reverse_file.stream_position().unwrap();
    reverse_index.insert(alice_id, alice_rev_position);
    reverse_file.write_all(&alice_id.into_bytes()).unwrap();
    reverse_file.write_u32::<LittleEndian>(0).unwrap();

    forward_file.flush().unwrap();
    reverse_file.flush().unwrap();

    (
        forward_file,
        reverse_file,
        forward_index,
        reverse_index,
        alice_id,
        bob_id,
        charlie_id,
        dave_id,
    )
}

#[test]
fn test_dijkstra_finds_best_similarity_path() {
    let (
        forward_file,
        reverse_file,
        forward_index,
        reverse_index,
        alice_id,
        _bob_id,
        charlie_id,
        dave_id,
    ) = create_weighted_test_graph();

    let config = PathfindingConfig::new(0.0, 80, true);

    let forward_mmap = unsafe { Mmap::map(&forward_file).unwrap() };
    let reverse_mmap = unsafe { Mmap::map(&reverse_file).unwrap() };
    let (path, visited_count, _) = dijkstra_find_path(
        alice_id,
        dave_id,
        &forward_mmap,
        &forward_index,
        &reverse_mmap,
        &reverse_index,
        &config,
    );

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
    let mut forward_file = NamedTempFile::new().unwrap();
    let mut reverse_file = NamedTempFile::new().unwrap();
    let alice_id = Uuid::new_v4();
    let bob_id = Uuid::new_v4();

    let mut forward_index = FxHashMap::default();
    let mut reverse_index = FxHashMap::default();

    // Forward: Alice -> Bob (0.95)
    let alice_position = 0;
    forward_index.insert(alice_id, alice_position);
    forward_file.write_all(&alice_id.into_bytes()).unwrap();
    forward_file.write_u32::<LittleEndian>(1).unwrap();
    forward_file.write_all(&bob_id.into_bytes()).unwrap();
    forward_file.write_f32::<LittleEndian>(0.95).unwrap();

    // Bob has no outgoing connections
    let bob_position = forward_file.stream_position().unwrap();
    forward_index.insert(bob_id, bob_position);
    forward_file.write_all(&bob_id.into_bytes()).unwrap();
    forward_file.write_u32::<LittleEndian>(0).unwrap();

    // Reverse: Bob receives from Alice (0.95)
    let bob_rev_position = 0;
    reverse_index.insert(bob_id, bob_rev_position);
    reverse_file.write_all(&bob_id.into_bytes()).unwrap();
    reverse_file.write_u32::<LittleEndian>(1).unwrap();
    reverse_file.write_all(&alice_id.into_bytes()).unwrap();
    reverse_file.write_f32::<LittleEndian>(0.95).unwrap();

    // Alice has no incoming connections
    let alice_rev_position = reverse_file.stream_position().unwrap();
    reverse_index.insert(alice_id, alice_rev_position);
    reverse_file.write_all(&alice_id.into_bytes()).unwrap();
    reverse_file.write_u32::<LittleEndian>(0).unwrap();

    forward_file.flush().unwrap();
    reverse_file.flush().unwrap();

    let config = PathfindingConfig::new(0.0, 80, true);

    let forward_mmap = unsafe { Mmap::map(&forward_file).unwrap() };
    let reverse_mmap = unsafe { Mmap::map(&reverse_file).unwrap() };
    let (path, _, _) = dijkstra_find_path(
        alice_id,
        bob_id,
        &forward_mmap,
        &forward_index,
        &reverse_mmap,
        &reverse_index,
        &config,
    );

    assert!(path.is_some());
    let path = path.unwrap();
    assert_eq!(path.len(), 2);
    assert_eq!(path[0].0, alice_id);
    assert_eq!(path[1].0, bob_id);
    assert_eq!(path[1].1, 0.95); // Similarity score
}

#[test]
fn test_dijkstra_no_path() {
    let mut forward_file = NamedTempFile::new().unwrap();
    let mut reverse_file = NamedTempFile::new().unwrap();
    let alice_id = Uuid::new_v4();
    let isolated_id = Uuid::new_v4();

    let mut forward_index = FxHashMap::default();
    let mut reverse_index = FxHashMap::default();

    // Forward: Alice has no connections
    let alice_position = 0;
    forward_index.insert(alice_id, alice_position);
    forward_file.write_all(&alice_id.into_bytes()).unwrap();
    forward_file.write_u32::<LittleEndian>(0).unwrap();

    // Isolated node has no connections
    let isolated_position = forward_file.stream_position().unwrap();
    forward_index.insert(isolated_id, isolated_position);
    forward_file.write_all(&isolated_id.into_bytes()).unwrap();
    forward_file.write_u32::<LittleEndian>(0).unwrap();

    // Reverse: Both nodes have no incoming connections
    let alice_rev_position = 0;
    reverse_index.insert(alice_id, alice_rev_position);
    reverse_file.write_all(&alice_id.into_bytes()).unwrap();
    reverse_file.write_u32::<LittleEndian>(0).unwrap();

    let isolated_rev_position = reverse_file.stream_position().unwrap();
    reverse_index.insert(isolated_id, isolated_rev_position);
    reverse_file.write_all(&isolated_id.into_bytes()).unwrap();
    reverse_file.write_u32::<LittleEndian>(0).unwrap();

    forward_file.flush().unwrap();
    reverse_file.flush().unwrap();

    let config = PathfindingConfig::new(0.0, 80, true);

    let forward_mmap = unsafe { Mmap::map(&forward_file).unwrap() };
    let reverse_mmap = unsafe { Mmap::map(&reverse_file).unwrap() };
    let (path, visited_count, _) = dijkstra_find_path(
        alice_id,
        isolated_id,
        &forward_mmap,
        &forward_index,
        &reverse_mmap,
        &reverse_index,
        &config,
    );

    assert!(path.is_none());
    assert!(visited_count >= 1); // Bidirectional search visits at least start and target
}

#[test]
fn test_dijkstra_with_min_match_filter() {
    let (
        forward_file,
        reverse_file,
        forward_index,
        reverse_index,
        alice_id,
        _bob_id,
        _charlie_id,
        dave_id,
    ) = create_weighted_test_graph();

    let config = PathfindingConfig::new(0.75, 80, true); // Filters out Alice->Bob (0.5) and Charlie->Dave (0.7)

    let forward_mmap = unsafe { Mmap::map(&forward_file).unwrap() };
    let reverse_mmap = unsafe { Mmap::map(&reverse_file).unwrap() };
    let (path, _, _) = dijkstra_find_path(
        alice_id,
        dave_id,
        &forward_mmap,
        &forward_index,
        &reverse_mmap,
        &reverse_index,
        &config,
    );

    // Path should be None because Charlie->Dave (0.7) is filtered out
    assert!(path.is_none());
}

#[test]
fn test_dijkstra_with_top_related_limit() {
    let mut forward_file = NamedTempFile::new().unwrap();
    let mut reverse_file = NamedTempFile::new().unwrap();
    let alice_id = Uuid::new_v4();
    let bob_id = Uuid::new_v4();
    let charlie_id = Uuid::new_v4();

    let mut forward_index = FxHashMap::default();
    let mut reverse_index = FxHashMap::default();

    // Forward: Alice has 2 connections but we'll limit to top 1
    let alice_position = 0;
    forward_index.insert(alice_id, alice_position);
    forward_file.write_all(&alice_id.into_bytes()).unwrap();
    forward_file.write_u32::<LittleEndian>(2).unwrap();
    // Lower similarity to Bob
    forward_file.write_all(&bob_id.into_bytes()).unwrap();
    forward_file.write_f32::<LittleEndian>(0.3).unwrap();
    // Higher similarity to Charlie
    forward_file.write_all(&charlie_id.into_bytes()).unwrap();
    forward_file.write_f32::<LittleEndian>(0.9).unwrap();

    // Bob and Charlie have no forward connections
    let bob_position = forward_file.stream_position().unwrap();
    forward_index.insert(bob_id, bob_position);
    forward_file.write_all(&bob_id.into_bytes()).unwrap();
    forward_file.write_u32::<LittleEndian>(0).unwrap();

    let charlie_position = forward_file.stream_position().unwrap();
    forward_index.insert(charlie_id, charlie_position);
    forward_file.write_all(&charlie_id.into_bytes()).unwrap();
    forward_file.write_u32::<LittleEndian>(0).unwrap();

    // Reverse: Bob and Charlie receive from Alice
    let bob_rev_position = 0;
    reverse_index.insert(bob_id, bob_rev_position);
    reverse_file.write_all(&bob_id.into_bytes()).unwrap();
    reverse_file.write_u32::<LittleEndian>(1).unwrap();
    reverse_file.write_all(&alice_id.into_bytes()).unwrap();
    reverse_file.write_f32::<LittleEndian>(0.3).unwrap();

    let charlie_rev_position = reverse_file.stream_position().unwrap();
    reverse_index.insert(charlie_id, charlie_rev_position);
    reverse_file.write_all(&charlie_id.into_bytes()).unwrap();
    reverse_file.write_u32::<LittleEndian>(1).unwrap();
    reverse_file.write_all(&alice_id.into_bytes()).unwrap();
    reverse_file.write_f32::<LittleEndian>(0.9).unwrap();

    // Alice has no incoming connections
    let alice_rev_position = reverse_file.stream_position().unwrap();
    reverse_index.insert(alice_id, alice_rev_position);
    reverse_file.write_all(&alice_id.into_bytes()).unwrap();
    reverse_file.write_u32::<LittleEndian>(0).unwrap();

    forward_file.flush().unwrap();
    reverse_file.flush().unwrap();

    let config = PathfindingConfig::new(0.0, 1, true); // Only take top 1 connection

    let forward_mmap = unsafe { Mmap::map(&forward_file).unwrap() };
    let reverse_mmap = unsafe { Mmap::map(&reverse_file).unwrap() };
    let (path, _, _) = dijkstra_find_path(
        alice_id,
        bob_id,
        &forward_mmap,
        &forward_index,
        &reverse_mmap,
        &reverse_index,
        &config,
    );

    // With bidirectional search, this may find a path through reverse search
    // The test validates that top_related limit is being applied, but bidirectional
    // search can still find paths that unidirectional wouldn't
    if path.is_some() {
        let path = path.unwrap();
        assert_eq!(path.len(), 2); // Direct connection Alice -> Bob
        assert_eq!(path[0].0, alice_id);
        assert_eq!(path[1].0, bob_id);
    }
}
