use crate::args::Args;
use byteorder::{LittleEndian, ReadBytesExt};
use memmap2::Mmap;
use rustc_hash::{FxHashMap, FxHashSet};
use std::{
    cmp::Ordering,
    collections::{BinaryHeap, VecDeque},
    fs::File,
    io::{Cursor, Read},
    path::Path,
    time::Instant,
};
use uuid::Uuid;

type PathStep = (Uuid, f32);
type PathResult = (Option<Vec<PathStep>>, usize, f64);

#[derive(Clone)]
struct DijkstraNode {
    cost: f32,
    artist: Uuid,
}

impl PartialEq for DijkstraNode {
    fn eq(&self, other: &Self) -> bool {
        self.cost == other.cost
    }
}

impl Eq for DijkstraNode {}

impl PartialOrd for DijkstraNode {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        other.cost.partial_cmp(&self.cost)
    }
}

impl Ord for DijkstraNode {
    fn cmp(&self, other: &Self) -> Ordering {
        self.partial_cmp(other).unwrap_or(Ordering::Equal)
    }
}

struct DijkstraState {
    heap: BinaryHeap<DijkstraNode>,
    distances: FxHashMap<Uuid, f32>,
    parent_map: FxHashMap<Uuid, (Uuid, f32)>,
    visited: FxHashSet<Uuid>,
}

impl DijkstraState {
    fn new(start: Uuid) -> Self {
        let mut heap = BinaryHeap::new();
        let mut distances = FxHashMap::default();
        
        heap.push(DijkstraNode { cost: 0.0, artist: start });
        distances.insert(start, 0.0);
        
        Self {
            heap,
            distances,
            parent_map: FxHashMap::default(),
            visited: FxHashSet::default(),
        }
    }
    
    fn visit_neighbor(&mut self, neighbor: Uuid, current: Uuid, similarity: f32, current_cost: f32) {
        let edge_weight = 1.0 - similarity;
        let new_cost = current_cost + edge_weight;
        
        if let Some(&existing_cost) = self.distances.get(&neighbor) {
            if new_cost >= existing_cost {
                return;
            }
        }
        
        self.distances.insert(neighbor, new_cost);
        self.parent_map.insert(neighbor, (current, similarity));
        self.heap.push(DijkstraNode { cost: new_cost, artist: neighbor });
    }
    
    fn reconstruct_path(&self, start: Uuid, target: Uuid) -> Vec<PathStep> {
        let mut path = Vec::new();
        let mut current_node = target;
        
        while current_node != start {
            let (parent_node, similarity) = self.parent_map[&current_node];
            path.push((current_node, similarity));
            current_node = parent_node;
        }
        
        path.push((start, 0.0));
        path.reverse();
        path
    }
}

struct BfsState {
    queue: VecDeque<Uuid>,
    visited: FxHashSet<Uuid>,
    parent_map: FxHashMap<Uuid, (Uuid, f32)>,
}

impl BfsState {
    fn new(start: Uuid) -> Self {
        let mut queue = VecDeque::new();
        let mut visited = FxHashSet::default();
        
        queue.push_back(start);
        visited.insert(start);
        
        Self {
            queue,
            visited,
            parent_map: FxHashMap::default(),
        }
    }
    
    fn visit_neighbor(&mut self, neighbor: Uuid, current: Uuid, similarity: f32) {
        if !self.visited.contains(&neighbor) {
            self.visited.insert(neighbor);
            self.parent_map.insert(neighbor, (current, similarity));
            self.queue.push_back(neighbor);
        }
    }
    
    fn reconstruct_path(&self, start: Uuid, target: Uuid) -> Vec<PathStep> {
        let mut path = Vec::new();
        let mut current_node = target;
        
        while current_node != start {
            let (parent_node, similarity) = self.parent_map[&current_node];
            path.push((current_node, similarity));
            current_node = parent_node;
        }
        
        path.push((start, 0.0));
        path.reverse();
        path
    }
}

pub fn dijkstra_find_path(
    start: Uuid,
    target: Uuid,
    graph_binary_path: &Path,
    graph_index: &FxHashMap<Uuid, u64>,
    search_args: &Args,
) -> PathResult {
    let search_timer = Instant::now();
    
    let graph_data = match open_memory_mapped_file(graph_binary_path) {
        Ok(data) => data,
        Err(_) => return (None, 0, 0.0),
    };
    
    let mut dijkstra_state = DijkstraState::new(start);
    
    while let Some(DijkstraNode { cost, artist: current_artist }) = dijkstra_state.heap.pop() {
        if current_artist == target {
            let path = dijkstra_state.reconstruct_path(start, target);
            let elapsed_time = search_timer.elapsed().as_secs_f64();
            return (Some(path), dijkstra_state.visited.len(), elapsed_time);
        }
        
        if dijkstra_state.visited.contains(&current_artist) {
            continue;
        }
        dijkstra_state.visited.insert(current_artist);
        
        let artist_connections = get_artist_connections(current_artist, &graph_data, graph_index, search_args);
        
        for (neighbor_artist, similarity_score) in artist_connections {
            dijkstra_state.visit_neighbor(neighbor_artist, current_artist, similarity_score, cost);
        }
    }
    
    let elapsed_time = search_timer.elapsed().as_secs_f64();
    (None, dijkstra_state.visited.len(), elapsed_time)
}

pub fn bfs_find_path(
    start: Uuid,
    target: Uuid,
    graph_binary_path: &Path,
    graph_index: &FxHashMap<Uuid, u64>,
    search_args: &Args,
) -> PathResult {
    let search_timer = Instant::now();
    
    let graph_data = match open_memory_mapped_file(graph_binary_path) {
        Ok(data) => data,
        Err(_) => return (None, 0, 0.0),
    };
    
    let mut bfs_state = BfsState::new(start);
    
    while let Some(current_artist) = bfs_state.queue.pop_front() {
        if current_artist == target {
            let path = bfs_state.reconstruct_path(start, target);
            let elapsed_time = search_timer.elapsed().as_secs_f64();
            return (Some(path), bfs_state.visited.len(), elapsed_time);
        }
        
        let artist_connections = get_artist_connections(current_artist, &graph_data, graph_index, search_args);
        
        for (neighbor_artist, similarity_score) in artist_connections {
            bfs_state.visit_neighbor(neighbor_artist, current_artist, similarity_score);
        }
    }
    
    let elapsed_time = search_timer.elapsed().as_secs_f64();
    (None, bfs_state.visited.len(), elapsed_time)
}

fn open_memory_mapped_file(file_path: &Path) -> Result<Mmap, std::io::Error> {
    let file = File::open(file_path)?;
    unsafe { Mmap::map(&file) }
}

fn get_artist_connections(
    artist_id: Uuid,
    graph_data: &Mmap,
    graph_index: &FxHashMap<Uuid, u64>,
    search_args: &Args,
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
        Ok(raw_connections) => filter_and_sort_connections(raw_connections, search_args),
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

fn filter_and_sort_connections(mut connections: Vec<(Uuid, f32)>, search_args: &Args) -> Vec<(Uuid, f32)> {
    if search_args.min_match > 0.0 {
        connections.retain(|(_, similarity)| *similarity >= search_args.min_match);
    }
    
    connections.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    connections.truncate(search_args.top_related);
    
    connections
}