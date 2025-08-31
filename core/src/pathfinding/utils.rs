use crate::pathfinding_config::PathfindingConfig;
use byteorder::{LittleEndian, ReadBytesExt};
use memmap2::Mmap;
use rustc_hash::FxHashMap;
use std::{
    fs::File,
    io::{Cursor, Read},
    path::Path,
};
use uuid::Uuid;

pub type PathStep = (Uuid, f32);
pub type PathResult = (Option<Vec<PathStep>>, usize, f64);

#[derive(Debug, Clone)]
pub enum EnhancedPathResult {
    Success {
        primary_path: Vec<PathStep>,
        related_artists: FxHashMap<Uuid, (f32, usize)>,
        connections: FxHashMap<Uuid, Vec<(Uuid, f32)>>,
        artists_visited: usize,
        duration_ms: u64,
    },
    PathTooLong {
        primary_path: Vec<PathStep>,
        path_length: usize,
        minimum_budget_needed: usize,
        artists_visited: usize,
        duration_ms: u64,
    },
    NoPath {
        artists_visited: usize,
        duration_ms: u64,
    },
}

pub fn open_memory_mapped_file(file_path: &Path) -> Result<Mmap, std::io::Error> {
    let file = File::open(file_path)?;
    unsafe { Mmap::map(&file) }
}

pub fn get_artist_connections(
    artist_id: Uuid,
    graph_data: &Mmap,
    graph_index: &FxHashMap<Uuid, u64>,
    config: &PathfindingConfig,
) -> Vec<(Uuid, f32)> {
    let file_position = match find_artist_position(artist_id, graph_index) {
        Some(pos) => pos,
        None => return vec![],
    };
    
    if file_position >= graph_data.len() {
        return vec![];
    }
    
    let artist_data_cursor = create_cursor_at_position(graph_data, file_position);
    
    match parse_artist_connections(artist_id, artist_data_cursor) {
        Ok(raw_connections) => filter_and_sort_connections(raw_connections, config),
        Err(_) => vec![],
    }
}

fn find_artist_position(artist_id: Uuid, graph_index: &FxHashMap<Uuid, u64>) -> Option<usize> {
    graph_index.get(&artist_id).map(|&pos| pos as usize)
}

fn create_cursor_at_position(graph_data: &Mmap, position: usize) -> Cursor<&[u8]> {
    Cursor::new(&graph_data[position..])
}

fn parse_artist_connections(expected_artist_id: Uuid, mut cursor: Cursor<&[u8]>) -> Result<Vec<(Uuid, f32)>, std::io::Error> {
    let stored_artist_id = read_uuid_from_cursor(&mut cursor)?;
    
    if stored_artist_id != expected_artist_id {
        return Err(std::io::Error::new(std::io::ErrorKind::InvalidData, "Artist ID mismatch"));
    }
    
    let connection_count = cursor.read_u32::<LittleEndian>()? as usize;
    let mut connections = Vec::with_capacity(connection_count);
    
    for _ in 0..connection_count {
        let connected_artist_id = read_uuid_from_cursor(&mut cursor)?;
        let similarity_score = cursor.read_f32::<LittleEndian>()?;
        connections.push((connected_artist_id, similarity_score));
    }
    
    Ok(connections)
}

fn read_uuid_from_cursor(cursor: &mut Cursor<&[u8]>) -> Result<Uuid, std::io::Error> {
    let mut uuid_bytes = [0u8; 16];
    cursor.read_exact(&mut uuid_bytes)?;
    Ok(Uuid::from_bytes(uuid_bytes))
}

fn filter_and_sort_connections(mut connections: Vec<(Uuid, f32)>, config: &PathfindingConfig) -> Vec<(Uuid, f32)> {
    if config.min_match > 0.0 {
        connections.retain(|(_, similarity)| *similarity >= config.min_match);
    }
    
    connections.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    connections.truncate(config.top_related);
    
    connections
}

pub fn reconstruct_path(
    parent_map: &FxHashMap<Uuid, (Uuid, f32)>,
    start: Uuid,
    target: Uuid,
) -> Vec<PathStep> {
    let mut path = Vec::new();
    let mut current_node = target;
    
    while current_node != start {
        let (parent_node, similarity) = parent_map[&current_node];
        path.push((current_node, similarity));
        current_node = parent_node;
    }
    
    path.push((start, 0.0));
    path.reverse();
    path
}