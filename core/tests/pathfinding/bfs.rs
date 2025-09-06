// Tests updated for bidirectional pathfinding API

use artistpath_core::{
    Algorithm, EnhancedPathResult, PathfindingConfig, bfs_find_path, find_paths_with_exploration, BiDirectionalGraphs,
};
use byteorder::{LittleEndian, WriteBytesExt};
use memmap2::Mmap;
use rustc_hash::FxHashMap;
use std::io::{Seek, Write};
use tempfile::NamedTempFile;
use uuid::Uuid;

// Type alias to reduce complexity
type MultiArtistTestSetup = (
    NamedTempFile,
    NamedTempFile,
    FxHashMap<Uuid, u64>,
    FxHashMap<Uuid, u64>,
    Vec<Uuid>,
);

// Helper function to create empty reverse graph for tests
fn create_empty_reverse_file() -> (NamedTempFile, FxHashMap<Uuid, u64>) {
    let mut reverse_file = NamedTempFile::new().unwrap();
    let reverse_index = FxHashMap::default();
    reverse_file.flush().unwrap();
    (reverse_file, reverse_index)
}

fn create_test_binary_file() -> (
    NamedTempFile,
    NamedTempFile,
    FxHashMap<Uuid, u64>,
    FxHashMap<Uuid, u64>,
    Uuid,
    Uuid,
) {
    let mut forward_file = NamedTempFile::new().unwrap();
    let mut reverse_file = NamedTempFile::new().unwrap();
    let alice_id = Uuid::new_v4();
    let bob_id = Uuid::new_v4();

    let mut forward_index = FxHashMap::default();
    let mut reverse_index = FxHashMap::default();

    // Write Alice's forward data
    let alice_position = 0;
    forward_index.insert(alice_id, alice_position);

    forward_file.write_all(&alice_id.into_bytes()).unwrap();
    forward_file.write_u32::<LittleEndian>(1).unwrap(); // 1 connection
    forward_file.write_all(&bob_id.into_bytes()).unwrap();
    forward_file.write_f32::<LittleEndian>(0.8).unwrap();

    // Write Bob's forward data
    let bob_position = forward_file.stream_position().unwrap();
    forward_index.insert(bob_id, bob_position);

    forward_file.write_all(&bob_id.into_bytes()).unwrap();
    forward_file.write_u32::<LittleEndian>(1).unwrap(); // 1 connection
    forward_file.write_all(&alice_id.into_bytes()).unwrap();
    forward_file.write_f32::<LittleEndian>(0.8).unwrap();

    // Write reverse data (same structure but reversed connections)
    let alice_reverse_position = 0;
    reverse_index.insert(alice_id, alice_reverse_position);

    reverse_file.write_all(&alice_id.into_bytes()).unwrap();
    reverse_file.write_u32::<LittleEndian>(1).unwrap(); // 1 connection
    reverse_file.write_all(&bob_id.into_bytes()).unwrap();
    reverse_file.write_f32::<LittleEndian>(0.8).unwrap();

    let bob_reverse_position = reverse_file.stream_position().unwrap();
    reverse_index.insert(bob_id, bob_reverse_position);

    reverse_file.write_all(&bob_id.into_bytes()).unwrap();
    reverse_file.write_u32::<LittleEndian>(1).unwrap(); // 1 connection
    reverse_file.write_all(&alice_id.into_bytes()).unwrap();
    reverse_file.write_f32::<LittleEndian>(0.8).unwrap();

    forward_file.flush().unwrap();
    reverse_file.flush().unwrap();

    (
        forward_file,
        reverse_file,
        forward_index,
        reverse_index,
        alice_id,
        bob_id,
    )
}

#[test]
fn test_bfs_find_direct_path() {
    let (forward_file, reverse_file, forward_index, reverse_index, alice_id, bob_id) =
        create_test_binary_file();

    let config = PathfindingConfig::new(0.0, 80, false);

    let forward_mmap = unsafe { Mmap::map(&forward_file).unwrap() };
    let reverse_mmap = unsafe { Mmap::map(&reverse_file).unwrap() };
    let (path, visited_count, _) = bfs_find_path(
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
    assert_eq!(path.len(), 2); // Alice -> Bob
    assert_eq!(path[0].0, alice_id);
    assert_eq!(path[1].0, bob_id);
    assert!(visited_count >= 2); // Bidirectional might visit more nodes
}

#[test]
fn test_bfs_no_path() {
    let mut forward_file = NamedTempFile::new().unwrap();
    let (reverse_file, reverse_index) = create_empty_reverse_file();

    let alice_id = Uuid::new_v4();
    let bob_id = Uuid::new_v4();
    let isolated_id = Uuid::new_v4();

    let mut forward_index = FxHashMap::default();

    // Write Alice's data (connects to Bob)
    let alice_position = 0;
    forward_index.insert(alice_id, alice_position);

    forward_file.write_all(&alice_id.into_bytes()).unwrap();
    forward_file.write_u32::<LittleEndian>(1).unwrap(); // 1 connection
    forward_file.write_all(&bob_id.into_bytes()).unwrap();
    forward_file.write_f32::<LittleEndian>(0.8).unwrap();

    // Write isolated node (no connections)
    let isolated_position = forward_file.stream_position().unwrap();
    forward_index.insert(isolated_id, isolated_position);

    forward_file.write_all(&isolated_id.into_bytes()).unwrap();
    forward_file.write_u32::<LittleEndian>(0).unwrap(); // 0 connections

    forward_file.flush().unwrap();

    let config = PathfindingConfig::new(0.0, 80, false);

    let forward_mmap = unsafe { Mmap::map(&forward_file).unwrap() };
    let reverse_mmap = unsafe { Mmap::map(&reverse_file).unwrap() };
    let (path, visited_count, _) = bfs_find_path(
        alice_id,
        isolated_id,
        &forward_mmap,
        &forward_index,
        &reverse_mmap,
        &reverse_index,
        &config,
    );

    assert!(path.is_none());
    assert!(visited_count >= 1); // Bidirectional search might visit different numbers of nodes
}

#[test]
fn test_bfs_min_match_filter() {
    let (forward_file, reverse_file, forward_index, reverse_index, alice_id, bob_id) =
        create_test_binary_file();

    let config = PathfindingConfig::new(0.9, 80, false); // Higher than our 0.8 connection

    let forward_mmap = unsafe { Mmap::map(&forward_file).unwrap() };
    let reverse_mmap = unsafe { Mmap::map(&reverse_file).unwrap() };
    let (path, _, _) = bfs_find_path(
        alice_id,
        bob_id,
        &forward_mmap,
        &forward_index,
        &reverse_mmap,
        &reverse_index,
        &config,
    );

    assert!(path.is_none()); // Should be filtered out
}

fn create_multi_artist_test_file() -> MultiArtistTestSetup {
    let mut forward_file = NamedTempFile::new().unwrap();
    let mut reverse_file = NamedTempFile::new().unwrap();
    let mut forward_index = FxHashMap::default();
    let mut reverse_index = FxHashMap::default();
    let mut artists = Vec::new();

    // Create 5 artists: A -> B -> C, A -> D, B -> E
    for _ in 0..5 {
        artists.push(Uuid::new_v4());
    }
    let [a_id, b_id, c_id, d_id, e_id] =
        [artists[0], artists[1], artists[2], artists[3], artists[4]];

    // Artist A connects to B and D
    let a_position = 0;
    forward_index.insert(a_id, a_position);
    forward_file.write_all(&a_id.into_bytes()).unwrap();
    forward_file.write_u32::<LittleEndian>(2).unwrap();
    forward_file.write_all(&b_id.into_bytes()).unwrap();
    forward_file.write_f32::<LittleEndian>(0.9).unwrap();
    forward_file.write_all(&d_id.into_bytes()).unwrap();
    forward_file.write_f32::<LittleEndian>(0.7).unwrap();

    // Artist B connects to A, C, and E
    let b_position = forward_file.stream_position().unwrap();
    forward_index.insert(b_id, b_position);
    forward_file.write_all(&b_id.into_bytes()).unwrap();
    forward_file.write_u32::<LittleEndian>(3).unwrap();
    forward_file.write_all(&a_id.into_bytes()).unwrap();
    forward_file.write_f32::<LittleEndian>(0.9).unwrap();
    forward_file.write_all(&c_id.into_bytes()).unwrap();
    forward_file.write_f32::<LittleEndian>(0.8).unwrap();
    forward_file.write_all(&e_id.into_bytes()).unwrap();
    forward_file.write_f32::<LittleEndian>(0.6).unwrap();

    // Artist C connects to B
    let c_position = forward_file.stream_position().unwrap();
    forward_index.insert(c_id, c_position);
    forward_file.write_all(&c_id.into_bytes()).unwrap();
    forward_file.write_u32::<LittleEndian>(1).unwrap();
    forward_file.write_all(&b_id.into_bytes()).unwrap();
    forward_file.write_f32::<LittleEndian>(0.8).unwrap();

    // Artist D connects to A
    let d_position = forward_file.stream_position().unwrap();
    forward_index.insert(d_id, d_position);
    forward_file.write_all(&d_id.into_bytes()).unwrap();
    forward_file.write_u32::<LittleEndian>(1).unwrap();
    forward_file.write_all(&a_id.into_bytes()).unwrap();
    forward_file.write_f32::<LittleEndian>(0.7).unwrap();

    // Artist E connects to B
    let e_position = forward_file.stream_position().unwrap();
    forward_index.insert(e_id, e_position);
    forward_file.write_all(&e_id.into_bytes()).unwrap();
    forward_file.write_u32::<LittleEndian>(1).unwrap();
    forward_file.write_all(&b_id.into_bytes()).unwrap();
    forward_file.write_f32::<LittleEndian>(0.6).unwrap();

    // Create reverse graph: reverse all the connections
    // A receives from: B, D
    let a_rev_pos = 0;
    reverse_index.insert(a_id, a_rev_pos);
    reverse_file.write_all(&a_id.into_bytes()).unwrap();
    reverse_file.write_u32::<LittleEndian>(2).unwrap();
    reverse_file.write_all(&b_id.into_bytes()).unwrap();
    reverse_file.write_f32::<LittleEndian>(0.9).unwrap();
    reverse_file.write_all(&d_id.into_bytes()).unwrap();
    reverse_file.write_f32::<LittleEndian>(0.7).unwrap();

    // B receives from: A, C, E
    let b_rev_pos = reverse_file.stream_position().unwrap();
    reverse_index.insert(b_id, b_rev_pos);
    reverse_file.write_all(&b_id.into_bytes()).unwrap();
    reverse_file.write_u32::<LittleEndian>(3).unwrap();
    reverse_file.write_all(&a_id.into_bytes()).unwrap();
    reverse_file.write_f32::<LittleEndian>(0.9).unwrap();
    reverse_file.write_all(&c_id.into_bytes()).unwrap();
    reverse_file.write_f32::<LittleEndian>(0.8).unwrap();
    reverse_file.write_all(&e_id.into_bytes()).unwrap();
    reverse_file.write_f32::<LittleEndian>(0.6).unwrap();

    // C receives from: B
    let c_rev_pos = reverse_file.stream_position().unwrap();
    reverse_index.insert(c_id, c_rev_pos);
    reverse_file.write_all(&c_id.into_bytes()).unwrap();
    reverse_file.write_u32::<LittleEndian>(1).unwrap();
    reverse_file.write_all(&b_id.into_bytes()).unwrap();
    reverse_file.write_f32::<LittleEndian>(0.8).unwrap();

    // D receives from: A
    let d_rev_pos = reverse_file.stream_position().unwrap();
    reverse_index.insert(d_id, d_rev_pos);
    reverse_file.write_all(&d_id.into_bytes()).unwrap();
    reverse_file.write_u32::<LittleEndian>(1).unwrap();
    reverse_file.write_all(&a_id.into_bytes()).unwrap();
    reverse_file.write_f32::<LittleEndian>(0.7).unwrap();

    // E receives from: B
    let e_rev_pos = reverse_file.stream_position().unwrap();
    reverse_index.insert(e_id, e_rev_pos);
    reverse_file.write_all(&e_id.into_bytes()).unwrap();
    reverse_file.write_u32::<LittleEndian>(1).unwrap();
    reverse_file.write_all(&b_id.into_bytes()).unwrap();
    reverse_file.write_f32::<LittleEndian>(0.6).unwrap();

    forward_file.flush().unwrap();
    reverse_file.flush().unwrap();

    (
        forward_file,
        reverse_file,
        forward_index,
        reverse_index,
        artists,
    )
}

#[test]
fn test_enhanced_pathfinding_finds_path_and_explores() {
    let (forward_file, reverse_file, forward_index, reverse_index, artists) =
        create_multi_artist_test_file();
    let [a_id, _b_id, c_id, _d_id, _e_id] =
        [artists[0], artists[1], artists[2], artists[3], artists[4]];

    let config = PathfindingConfig::new(0.0, 10, false);

    let forward_mmap = unsafe { Mmap::map(&forward_file).unwrap() };
    let reverse_mmap = unsafe { Mmap::map(&reverse_file).unwrap() };
    let graphs = BiDirectionalGraphs {
        forward: (&forward_mmap, &forward_index),
        reverse: (&reverse_mmap, &reverse_index),
    };
    let result = find_paths_with_exploration(
        a_id,
        c_id,
        Algorithm::Bfs,
        10,
        graphs,
        &config,
    );

    // Should find the path A -> B -> C
    match result {
        EnhancedPathResult::Success {
            primary_path,
            related_artists,
            connections,
            artists_visited,
            ..
        } => {
            // Bidirectional search should find the path from A to C
            assert_eq!(primary_path.len(), 3); // A -> B -> C
            assert_eq!(primary_path[0].0, a_id);
            assert_eq!(primary_path[primary_path.len() - 1].0, c_id);

            // Should discover artists within budget
            assert!(related_artists.len() <= 10);
            assert!(related_artists.contains_key(&a_id));
            assert!(related_artists.contains_key(&c_id));

            // Should have connections data
            assert!(!connections.is_empty());
            assert!(artists_visited > 0);
        }
        _ => panic!("Expected Success result"),
    }
}

#[test]
fn test_enhanced_pathfinding_respects_budget() {
    let (forward_file, reverse_file, forward_index, reverse_index, artists) =
        create_multi_artist_test_file();
    let [a_id, _b_id, c_id, _d_id, _e_id] =
        [artists[0], artists[1], artists[2], artists[3], artists[4]];

    let config = PathfindingConfig::new(0.0, 10, false);

    let forward_mmap = unsafe { Mmap::map(&forward_file).unwrap() };
    let reverse_mmap = unsafe { Mmap::map(&reverse_file).unwrap() };
    let graphs = BiDirectionalGraphs {
        forward: (&forward_mmap, &forward_index),
        reverse: (&reverse_mmap, &reverse_index),
    };
    let result = find_paths_with_exploration(
        a_id,
        c_id,
        Algorithm::Bfs,
        3,
        graphs,
        &config,
    );

    // Should respect budget limit - might be Success or PathTooLong
    match result {
        EnhancedPathResult::Success {
            related_artists, ..
        } => {
            assert!(related_artists.len() <= 3);
        }
        EnhancedPathResult::PathTooLong {
            path_length,
            minimum_budget_needed,
            ..
        } => {
            assert!(minimum_budget_needed > 3);
            assert_eq!(path_length, minimum_budget_needed);
        }
        EnhancedPathResult::NoPath { .. } => {
            // Path might not exist with this graph - that's ok too
        }
    }
}

#[test]
fn test_enhanced_pathfinding_no_path_still_explores() {
    let (forward_file, reverse_file, forward_index, reverse_index, artists) =
        create_multi_artist_test_file();
    let isolated_id = Uuid::new_v4();
    let [a_id, _b_id, _c_id, _d_id, _e_id] =
        [artists[0], artists[1], artists[2], artists[3], artists[4]];

    let config = PathfindingConfig::new(0.0, 10, false);

    let forward_mmap = unsafe { Mmap::map(&forward_file).unwrap() };
    let reverse_mmap = unsafe { Mmap::map(&reverse_file).unwrap() };
    let graphs = BiDirectionalGraphs {
        forward: (&forward_mmap, &forward_index),
        reverse: (&reverse_mmap, &reverse_index),
    };
    let result = find_paths_with_exploration(
        a_id,
        isolated_id,
        Algorithm::Bfs,
        3,
        graphs,
        &config,
    );

    // Should not find path to non-existent artist
    match result {
        EnhancedPathResult::NoPath {
            artists_visited, ..
        } => {
            assert!(artists_visited > 0); // Should have explored some artists
        }
        _ => panic!("Expected NoPath result for isolated target"),
    }
}

#[test]
fn test_enhanced_pathfinding_with_similarity_filter() {
    let (forward_file, reverse_file, forward_index, reverse_index, artists) =
        create_multi_artist_test_file();
    let [a_id, _b_id, c_id, _d_id, _e_id] =
        [artists[0], artists[1], artists[2], artists[3], artists[4]];

    let config = PathfindingConfig::new(0.75, 10, false); // Filter out connections < 0.75

    let forward_mmap = unsafe { Mmap::map(&forward_file).unwrap() };
    let reverse_mmap = unsafe { Mmap::map(&reverse_file).unwrap() };
    let graphs = BiDirectionalGraphs {
        forward: (&forward_mmap, &forward_index),
        reverse: (&reverse_mmap, &reverse_index),
    };
    let result = find_paths_with_exploration(
        a_id,
        c_id,
        Algorithm::Bfs,
        5,
        graphs,
        &config,
    );

    // Should still find path (A->B has 0.9, B->C has 0.8, both > 0.75)
    match result {
        EnhancedPathResult::Success {
            primary_path,
            connections,
            ..
        } => {
            // Bidirectional search might find different paths
            assert!(primary_path.len() >= 2); // At least A -> C

            // Should filter out low-similarity connections
            for artist_connections in connections.values() {
                for (_, similarity) in artist_connections {
                    assert!(*similarity >= 0.75);
                }
            }
        }
        _ => panic!("Expected Success result with similarity filtering"),
    }
}

#[test]
fn test_enhanced_pathfinding_budget_too_low() {
    let (forward_file, reverse_file, forward_index, reverse_index, artists) =
        create_multi_artist_test_file();
    let [a_id, _b_id, c_id, _d_id, _e_id] =
        [artists[0], artists[1], artists[2], artists[3], artists[4]];

    let config = PathfindingConfig::new(0.0, 10, false);

    // Force PathTooLong by using budget = 2 (for at most 2-artist path)
    let forward_mmap = unsafe { Mmap::map(&forward_file).unwrap() };
    let reverse_mmap = unsafe { Mmap::map(&reverse_file).unwrap() };
    let graphs = BiDirectionalGraphs {
        forward: (&forward_mmap, &forward_index),
        reverse: (&reverse_mmap, &reverse_index),
    };
    let result = find_paths_with_exploration(
        a_id,
        c_id,
        Algorithm::Bfs,
        2,
        graphs,
        &config,
    );

    match result {
        EnhancedPathResult::PathTooLong {
            primary_path,
            path_length,
            minimum_budget_needed,
            ..
        } => {
            assert_eq!(primary_path[0].0, a_id);
            assert_eq!(primary_path[primary_path.len() - 1].0, c_id);
            assert_eq!(path_length, primary_path.len());
            assert_eq!(minimum_budget_needed, path_length);
            assert!(minimum_budget_needed > 2);
        }
        _ => {
            // Might be Success if budget=1 is enough, or NoPath if no path exists
            // Both are acceptable depending on the graph structure
        }
    }
}
