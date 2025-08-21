use crate::args::Args;
use crate::parsing::GraphNode;
use rustc_hash::{FxHashMap, FxHashSet};
use std::{
    collections::VecDeque,
    fs::File,
    io::{BufRead, BufReader, Seek, SeekFrom},
    path::Path,
    time::Instant,
};
use uuid::Uuid;

pub fn bfs_find_path(
    start: Uuid,
    target: Uuid,
    graph_path: &Path,
    graph_index: &FxHashMap<String, u64>,
    args: &Args,
) -> (Option<Vec<(Uuid, f32)>>, usize, f64) {
    let start_time = Instant::now();
    let mut queue = VecDeque::new();
    let mut visited = FxHashSet::default();
    let mut parent: FxHashMap<Uuid, (Uuid, f32)> = FxHashMap::default();

    // Open the file once with buffered reader for reuse
    let graph_file = match File::open(graph_path) {
        Ok(f) => f,
        Err(_) => return (None, 0, 0.0),
    };
    let mut reader = BufReader::with_capacity(8192, graph_file);

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

        let connections = get_artist_connections(current, &mut reader, graph_index, args);

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

fn get_artist_connections<R: BufRead + Seek>(
    artist_id: Uuid,
    reader: &mut R,
    graph_index: &FxHashMap<String, u64>,
    args: &Args,
) -> Vec<(Uuid, f32)> {
    let artist_id_str = artist_id.to_string();

    let position = match graph_index.get(&artist_id_str) {
        Some(&pos) => pos,
        None => return vec![], // Artist not in index
    };

    if reader.seek(SeekFrom::Start(position)).is_err() {
        return vec![];
    }

    let mut line = String::new();
    if reader.read_line(&mut line).is_err() {
        return vec![];
    }

    let node: GraphNode = match serde_json::from_str(line.trim()) {
        Ok(node) => node,
        Err(_) => return vec![],
    };

    if node.id != artist_id {
        return vec![];
    }

    let mut connections = node.connections;

    if args.min_match > 0.0 {
        connections.retain(|(_, similarity)| *similarity >= args.min_match);
    }

    connections.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    connections.truncate(args.top_related);

    connections
}