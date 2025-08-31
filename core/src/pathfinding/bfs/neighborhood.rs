use super::super::utils::get_artist_connections;
use crate::pathfinding_config::PathfindingConfig;
use rustc_hash::{FxHashMap, FxHashSet};
use uuid::Uuid;

struct NeighborInfo {
    similarity: f32,
    path_connections: usize,
}

pub type DiscoveredArtists = FxHashMap<Uuid, (f32, usize)>;
pub type ArtistConnections = FxHashMap<Uuid, Vec<(Uuid, f32)>>;

pub fn explore_path_neighborhood(
    path: &[(Uuid, f32)],
    budget: usize,
    graph_data: &memmap2::Mmap,
    graph_index: &FxHashMap<Uuid, u64>,
    config: &PathfindingConfig,
) -> (DiscoveredArtists, ArtistConnections) {
    let mut discovered_artists = FxHashMap::default();

    // Add path artists to discovered set
    for (idx, &(artist_id, similarity)) in path.iter().enumerate() {
        discovered_artists.insert(artist_id, (similarity, idx));
    }

    // Collect all connections for path artists
    let mut all_connections = collect_path_connections(path, graph_data, graph_index, config);

    let remaining_budget = budget.saturating_sub(path.len());
    if remaining_budget == 0 {
        return (discovered_artists, all_connections);
    }

    // Analyze and prioritize neighbors
    let neighbor_info = analyze_neighbor_connectivity(path, &all_connections);
    let prioritized_neighbors = prioritize_neighbors(neighbor_info);

    // Add neighbors up to budget
    let context = NeighborContext {
        graph_data,
        graph_index,
        config,
        budget,
        path_length: path.len(),
    };

    add_neighbors_to_discovered(
        prioritized_neighbors,
        &mut discovered_artists,
        &mut all_connections,
        &context,
    );

    (discovered_artists, all_connections)
}

fn collect_path_connections(
    path: &[(Uuid, f32)],
    graph_data: &memmap2::Mmap,
    graph_index: &FxHashMap<Uuid, u64>,
    config: &PathfindingConfig,
) -> ArtistConnections {
    let mut connections = FxHashMap::default();

    for &(artist_id, _) in path {
        let artist_connections = get_artist_connections(artist_id, graph_data, graph_index, config);
        connections.insert(artist_id, artist_connections);
    }

    connections
}

fn analyze_neighbor_connectivity(
    path: &[(Uuid, f32)],
    path_connections: &ArtistConnections,
) -> FxHashMap<Uuid, NeighborInfo> {
    let path_set: FxHashSet<Uuid> = path.iter().map(|(id, _)| *id).collect();
    let mut neighbor_info = FxHashMap::default();

    for connections in path_connections.values() {
        for &(neighbor, similarity) in connections {
            if !path_set.contains(&neighbor) {
                let entry = neighbor_info.entry(neighbor).or_insert(NeighborInfo {
                    similarity: 0.0,
                    path_connections: 0,
                });
                entry.similarity = entry.similarity.max(similarity);
                entry.path_connections += 1;
            }
        }
    }

    neighbor_info
}

fn prioritize_neighbors(neighbor_info: FxHashMap<Uuid, NeighborInfo>) -> Vec<(Uuid, f32, usize)> {
    let mut neighbors: Vec<(Uuid, f32, usize)> = neighbor_info
        .into_iter()
        .map(|(id, info)| (id, info.similarity, info.path_connections))
        .collect();

    // Sort by connection count (desc), then similarity (desc)
    neighbors.sort_by(|a, b| {
        b.2.cmp(&a.2)
            .then_with(|| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal))
    });

    neighbors
}

struct NeighborContext<'a> {
    graph_data: &'a memmap2::Mmap,
    graph_index: &'a FxHashMap<Uuid, u64>,
    config: &'a PathfindingConfig,
    budget: usize,
    path_length: usize,
}

fn add_neighbors_to_discovered(
    neighbors: Vec<(Uuid, f32, usize)>,
    discovered_artists: &mut DiscoveredArtists,
    all_connections: &mut ArtistConnections,
    context: &NeighborContext,
) {
    for (neighbor, similarity, _) in neighbors {
        if discovered_artists.len() >= context.budget {
            break;
        }

        if let std::collections::hash_map::Entry::Vacant(e) = discovered_artists.entry(neighbor) {
            e.insert((similarity, context.path_length));

            let connections = get_artist_connections(
                neighbor,
                context.graph_data,
                context.graph_index,
                context.config,
            );
            all_connections.insert(neighbor, connections);
        }
    }
}
