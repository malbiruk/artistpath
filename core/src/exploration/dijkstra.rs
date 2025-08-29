use super::ExplorationResult;
use memmap2::Mmap;
use rustc_hash::FxHashMap;
use uuid::Uuid;

pub fn explore_dijkstra(
    _center_id: Uuid,
    _budget: usize,
    _max_relations: usize,
    _min_similarity: f32,
    _graph_mmap: &Mmap,
    _graph_index: &FxHashMap<Uuid, u64>,
) -> ExplorationResult {
    todo!("Dijkstra-based exploration: find minimum weight subgraph with budget nodes")
}
