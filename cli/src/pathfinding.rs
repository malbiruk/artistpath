use crate::args::Args;
use byteorder::{LittleEndian, ReadBytesExt};
use memmap2::Mmap;
use rustc_hash::{FxHashMap, FxHashSet};
use std::{
    collections::VecDeque,
    fs::File,
    io::{Cursor, Read},
    path::Path,
    time::Instant,
};
use uuid::Uuid;

pub fn bfs_find_path(
    start: Uuid,
    target: Uuid,
    binary_path: &Path,
    binary_index: &FxHashMap<Uuid, u64>,
    args: &Args,
) -> (Option<Vec<(Uuid, f32)>>, usize, f64) {
    let start_time = Instant::now();
    let mut queue = VecDeque::new();
    let mut visited = FxHashSet::default();
    let mut parent: FxHashMap<Uuid, (Uuid, f32)> = FxHashMap::default();

    // Memory map the binary file
    let binary_file = match File::open(binary_path) {
        Ok(f) => f,
        Err(_) => return (None, 0, 0.0),
    };
    let mmap = match unsafe { Mmap::map(&binary_file) } {
        Ok(m) => m,
        Err(_) => return (None, 0, 0.0),
    };

    queue.push_back(start);
    visited.insert(start);

    while let Some(current) = queue.pop_front() {
        if current == target {
            let mut path = Vec::new();
            let mut node = target;

            while node != start {
                let (parent_node, similarity) = parent[&node];
                path.push((node, similarity));
                node = parent_node;
            }
            path.push((start, 0.0));
            path.reverse();

            let elapsed = start_time.elapsed().as_secs_f64();
            return (Some(path), visited.len(), elapsed);
        }

        let connections = get_artist_connections_mmap(current, &mmap, binary_index, args);

        for (neighbor, weight) in connections {
            if !visited.contains(&neighbor) {
                visited.insert(neighbor);
                parent.insert(neighbor, (current, weight));
                queue.push_back(neighbor);
            }
        }
    }

    let elapsed = start_time.elapsed().as_secs_f64();
    (None, visited.len(), elapsed)
}

fn get_artist_connections_mmap(
    artist_id: Uuid,
    mmap: &Mmap,
    binary_index: &FxHashMap<Uuid, u64>,
    args: &Args,
) -> Vec<(Uuid, f32)> {
    let position = match binary_index.get(&artist_id) {
        Some(&pos) => pos as usize,
        None => return vec![], // Artist not in index, return empty connections
    };

    if position >= mmap.len() {
        return vec![];
    }

    let mut cursor = Cursor::new(&mmap[position..]);

    // Read binary format:
    // - UUID (16 bytes) - artist ID
    // - Connection count (4 bytes, uint32)
    // - Each connection: UUID (16 bytes) + weight (4 bytes, float32)

    // Read and verify artist UUID (16 bytes)
    let mut uuid_bytes = [0u8; 16];
    if cursor.read_exact(&mut uuid_bytes).is_err() {
        return vec![];
    }
    let read_uuid = Uuid::from_bytes(uuid_bytes);
    if read_uuid != artist_id {
        return vec![];
    }

    // Read connection count (4 bytes)
    let connection_count = match cursor.read_u32::<LittleEndian>() {
        Ok(count) => count,
        Err(_) => return vec![],
    };

    let mut connections = Vec::with_capacity(connection_count as usize);

    // Read each connection
    for _ in 0..connection_count {
        // Read connected artist UUID (16 bytes)
        let mut conn_uuid_bytes = [0u8; 16];
        if cursor.read_exact(&mut conn_uuid_bytes).is_err() {
            break;
        }
        let conn_uuid = Uuid::from_bytes(conn_uuid_bytes);

        // Read weight (4 bytes)
        let weight = match cursor.read_f32::<LittleEndian>() {
            Ok(w) => w,
            Err(_) => break,
        };

        connections.push((conn_uuid, weight));
    }

    // Apply filters and sorting
    if args.min_match > 0.0 {
        connections.retain(|(_, similarity)| *similarity >= args.min_match);
    }

    connections.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    connections.truncate(args.top_related);

    connections
}