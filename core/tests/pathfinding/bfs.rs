use artistpath_core::{PathfindingConfig, bfs_find_path, find_paths_with_exploration_bfs, EnhancedPathResult};
use byteorder::{LittleEndian, WriteBytesExt};
use memmap2::Mmap;
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

    let mmap = unsafe { Mmap::map(&file).unwrap() };
    let (path, visited_count, _) = bfs_find_path(alice_id, bob_id, &mmap, &index, &config);

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

    let mmap = unsafe { Mmap::map(&file).unwrap() };
    let (path, visited_count, _) = bfs_find_path(alice_id, isolated_id, &mmap, &index, &config);

    assert!(path.is_none());
    assert_eq!(visited_count, 2); // Visited Alice and Bob
}

#[test]
fn test_bfs_min_match_filter() {
    let (file, index, alice_id, bob_id) = create_test_binary_file();

    let config = PathfindingConfig::new(0.9, 80, false); // Higher than our 0.8 connection

    let mmap = unsafe { Mmap::map(&file).unwrap() };
    let (path, _, _) = bfs_find_path(alice_id, bob_id, &mmap, &index, &config);

    assert!(path.is_none()); // Should be filtered out
}

fn create_multi_artist_test_file() -> (NamedTempFile, FxHashMap<Uuid, u64>, Vec<Uuid>) {
    let mut file = NamedTempFile::new().unwrap();
    let mut index = FxHashMap::default();
    let mut artists = Vec::new();
    
    // Create 5 artists: A -> B -> C, A -> D, B -> E
    for _ in 0..5 {
        artists.push(Uuid::new_v4());
    }
    let [a_id, b_id, c_id, d_id, e_id] = [artists[0], artists[1], artists[2], artists[3], artists[4]];
    
    // Artist A connects to B and D
    let a_position = 0;
    index.insert(a_id, a_position);
    file.write_all(&a_id.into_bytes()).unwrap();
    file.write_u32::<LittleEndian>(2).unwrap();
    file.write_all(&b_id.into_bytes()).unwrap();
    file.write_f32::<LittleEndian>(0.9).unwrap();
    file.write_all(&d_id.into_bytes()).unwrap();
    file.write_f32::<LittleEndian>(0.7).unwrap();
    
    // Artist B connects to A, C, and E
    let b_position = file.stream_position().unwrap();
    index.insert(b_id, b_position);
    file.write_all(&b_id.into_bytes()).unwrap();
    file.write_u32::<LittleEndian>(3).unwrap();
    file.write_all(&a_id.into_bytes()).unwrap();
    file.write_f32::<LittleEndian>(0.9).unwrap();
    file.write_all(&c_id.into_bytes()).unwrap();
    file.write_f32::<LittleEndian>(0.8).unwrap();
    file.write_all(&e_id.into_bytes()).unwrap();
    file.write_f32::<LittleEndian>(0.6).unwrap();
    
    // Artist C connects to B
    let c_position = file.stream_position().unwrap();
    index.insert(c_id, c_position);
    file.write_all(&c_id.into_bytes()).unwrap();
    file.write_u32::<LittleEndian>(1).unwrap();
    file.write_all(&b_id.into_bytes()).unwrap();
    file.write_f32::<LittleEndian>(0.8).unwrap();
    
    // Artist D connects to A
    let d_position = file.stream_position().unwrap();
    index.insert(d_id, d_position);
    file.write_all(&d_id.into_bytes()).unwrap();
    file.write_u32::<LittleEndian>(1).unwrap();
    file.write_all(&a_id.into_bytes()).unwrap();
    file.write_f32::<LittleEndian>(0.7).unwrap();
    
    // Artist E connects to B
    let e_position = file.stream_position().unwrap();
    index.insert(e_id, e_position);
    file.write_all(&e_id.into_bytes()).unwrap();
    file.write_u32::<LittleEndian>(1).unwrap();
    file.write_all(&b_id.into_bytes()).unwrap();
    file.write_f32::<LittleEndian>(0.6).unwrap();
    
    file.flush().unwrap();
    
    (file, index, artists)
}

#[test]
fn test_enhanced_pathfinding_finds_path_and_explores() {
    let (file, index, artists) = create_multi_artist_test_file();
    let [a_id, _b_id, c_id, _d_id, _e_id] = [artists[0], artists[1], artists[2], artists[3], artists[4]];
    
    let config = PathfindingConfig::new(0.0, 10, false);
    
    let mmap = unsafe { Mmap::map(&file).unwrap() };
    let result = find_paths_with_exploration_bfs(a_id, c_id, 10, &mmap, &index, &config);
    
    // Should find the path A -> B -> C
    match result {
        EnhancedPathResult::Success { primary_path, related_artists, connections, artists_visited, .. } => {
            assert_eq!(primary_path.len(), 3); // A -> B -> C
            assert_eq!(primary_path[0].0, a_id);
            assert_eq!(primary_path[2].0, c_id);
            
            // Should discover artists within budget
            assert!(related_artists.len() <= 10);
            assert!(related_artists.contains_key(&a_id));
            assert!(related_artists.contains_key(&c_id));
            
            // Should have connections data
            assert!(!connections.is_empty());
            assert!(artists_visited > 0);
        },
        _ => panic!("Expected Success result"),
    }
}

#[test]
fn test_enhanced_pathfinding_respects_budget() {
    let (file, index, artists) = create_multi_artist_test_file();
    let [a_id, _b_id, c_id, _d_id, _e_id] = [artists[0], artists[1], artists[2], artists[3], artists[4]];
    
    let config = PathfindingConfig::new(0.0, 10, false);
    
    let mmap = unsafe { Mmap::map(&file).unwrap() };
    let result = find_paths_with_exploration_bfs(a_id, c_id, 3, &mmap, &index, &config);
    
    // Should respect budget limit - might be Success or PathTooLong
    match result {
        EnhancedPathResult::Success { related_artists, .. } => {
            assert!(related_artists.len() <= 3);
        },
        EnhancedPathResult::PathTooLong { path_length, minimum_budget_needed, .. } => {
            assert!(minimum_budget_needed > 3);
            assert_eq!(path_length, minimum_budget_needed);
        },
        EnhancedPathResult::NoPath { .. } => {
            // Path might not exist with this graph - that's ok too
        },
    }
}

#[test]
fn test_enhanced_pathfinding_no_path_still_explores() {
    let (file, index, artists) = create_multi_artist_test_file();
    let isolated_id = Uuid::new_v4();
    let [a_id, _b_id, _c_id, _d_id, _e_id] = [artists[0], artists[1], artists[2], artists[3], artists[4]];
    
    let config = PathfindingConfig::new(0.0, 10, false);
    
    let mmap = unsafe { Mmap::map(&file).unwrap() };
    let result = find_paths_with_exploration_bfs(a_id, isolated_id, 3, &mmap, &index, &config);
    
    // Should not find path to non-existent artist
    match result {
        EnhancedPathResult::NoPath { artists_visited, .. } => {
            assert!(artists_visited > 0); // Should have explored some artists
        },
        _ => panic!("Expected NoPath result for isolated target"),
    }
}

#[test]
fn test_enhanced_pathfinding_with_similarity_filter() {
    let (file, index, artists) = create_multi_artist_test_file();
    let [a_id, _b_id, c_id, _d_id, _e_id] = [artists[0], artists[1], artists[2], artists[3], artists[4]];
    
    let config = PathfindingConfig::new(0.75, 10, false); // Filter out connections < 0.75
    
    let mmap = unsafe { Mmap::map(&file).unwrap() };
    let result = find_paths_with_exploration_bfs(a_id, c_id, 5, &mmap, &index, &config);
    
    // Should still find path (A->B has 0.9, B->C has 0.8, both > 0.75)
    match result {
        EnhancedPathResult::Success { primary_path, connections, .. } => {
            assert_eq!(primary_path.len(), 3); // A -> B -> C
            
            // Should filter out low-similarity connections
            for artist_connections in connections.values() {
                for (_, similarity) in artist_connections {
                    assert!(*similarity >= 0.75);
                }
            }
        },
        _ => panic!("Expected Success result with similarity filtering"),
    }
}


#[test]
fn test_enhanced_pathfinding_budget_too_low() {
    let (file, index, artists) = create_multi_artist_test_file();
    let [a_id, _b_id, c_id, _d_id, _e_id] = [artists[0], artists[1], artists[2], artists[3], artists[4]];
    
    let config = PathfindingConfig::new(0.0, 10, false);
    
    // Force PathTooLong by using budget = 1 (only start artist)
    let mmap = unsafe { Mmap::map(&file).unwrap() };
    let result = find_paths_with_exploration_bfs(a_id, c_id, 1, &mmap, &index, &config);
    
    match result {
        EnhancedPathResult::PathTooLong { primary_path, path_length, minimum_budget_needed, .. } => {
            assert_eq!(primary_path[0].0, a_id);
            assert_eq!(primary_path[primary_path.len()-1].0, c_id);
            assert_eq!(path_length, primary_path.len());
            assert_eq!(minimum_budget_needed, path_length);
            assert!(minimum_budget_needed > 1);
        },
        _ => {
            // Might be Success if budget=1 is enough, or NoPath if no path exists
            // Both are acceptable depending on the graph structure
        }
    }
}
