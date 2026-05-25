use crate::cache::MetadataCache;
use artistpath_core::{Artist, parse_unified_metadata, string_normalization::extract_trigrams};
use memmap2::Mmap;
use rustc_hash::{FxHashMap, FxHashSet};
use std::fs::File;
use std::path::{Path, PathBuf};
use std::time::Instant;
use uuid::Uuid;

pub struct AppState {
    /// Ordered list of unique normalized names with their artist IDs.
    /// Indices into this vec are referenced by `trigram_index`.
    pub lookup_entries: Vec<(String, Vec<Uuid>)>,
    /// Trigram → sorted indices into `lookup_entries`.
    /// Sorted so intersection can use a linear merge.
    pub trigram_index: FxHashMap<[u8; 3], Vec<u32>>,
    pub artist_metadata: FxHashMap<Uuid, Artist>,
    /// All artist IDs in `artist_metadata`, for O(1) random selection.
    pub artist_ids: Vec<Uuid>,
    pub graph_index: FxHashMap<Uuid, u64>,
    pub reverse_graph_index: FxHashMap<Uuid, u64>,
    pub graph_mmap: Mmap,
    pub reverse_graph_mmap: Mmap,
    pub metadata_cache: MetadataCache,
}

impl AppState {
    pub async fn new() -> Result<Self, Box<dyn std::error::Error>> {
        let metadata_path_str = std::env::var("METADATA_PATH")
            .unwrap_or_else(|_| "../../data/metadata.bin".to_string());
        let graph_path_str =
            std::env::var("GRAPH_PATH").unwrap_or_else(|_| "../../data/graph.bin".to_string());
        let reverse_graph_path_str = std::env::var("REVERSE_GRAPH_PATH")
            .unwrap_or_else(|_| "../../data/rev-graph.bin".to_string());

        let metadata_path = Path::new(&metadata_path_str);
        let graph_path = Path::new(&graph_path_str);
        let reverse_graph_path = Path::new(&reverse_graph_path_str);

        let (name_lookup, artist_metadata, graph_index, reverse_graph_index) =
            parse_unified_metadata(metadata_path);

        // Convert HashMap to ordered Vec so we can reference entries by index.
        let lookup_entries: Vec<(String, Vec<Uuid>)> = name_lookup.into_iter().collect();

        let trigram_index = build_trigram_index(&lookup_entries);

        let artist_ids: Vec<Uuid> = artist_metadata.keys().copied().collect();

        let graph_file = File::open(graph_path)?;
        let graph_mmap = unsafe { Mmap::map(&graph_file)? };

        let reverse_graph_file = File::open(reverse_graph_path)?;
        let reverse_graph_mmap = unsafe { Mmap::map(&reverse_graph_file)? };

        let api_key = std::env::var("LASTFM_API_KEY")
            .expect("LASTFM_API_KEY environment variable must be set");

        let cache_path_str = std::env::var("LASTFM_CACHE_PATH")
            .unwrap_or_else(|_| "../../data/artist_metadata.bin".to_string());
        let cache_path = PathBuf::from(cache_path_str);

        let metadata_cache = MetadataCache::new(api_key, cache_path).await?;

        println!("Loaded {} artists", artist_metadata.len());
        println!("Lookup entries: {}", lookup_entries.len());
        println!("Trigram index: {} unique trigrams", trigram_index.len());
        println!("Forward graph file: {} MB", graph_mmap.len() / 1_000_000);
        println!("Reverse graph file: {} MB", reverse_graph_mmap.len() / 1_000_000);

        Ok(Self {
            lookup_entries,
            trigram_index,
            artist_metadata,
            artist_ids,
            graph_index,
            reverse_graph_index,
            graph_mmap,
            reverse_graph_mmap,
            metadata_cache,
        })
    }
}

/// Build a trigram → entry-indices postings list, deduplicating trigrams
/// per entry. Postings lists are kept sorted so search-time intersection
/// can use a linear merge.
fn build_trigram_index(entries: &[(String, Vec<Uuid>)]) -> FxHashMap<[u8; 3], Vec<u32>> {
    let t0 = Instant::now();
    let mut index: FxHashMap<[u8; 3], Vec<u32>> = FxHashMap::default();
    let mut per_entry_seen: FxHashSet<[u8; 3]> = FxHashSet::default();

    for (idx, (name, _)) in entries.iter().enumerate() {
        per_entry_seen.clear();
        for trigram in extract_trigrams(name) {
            if per_entry_seen.insert(trigram) {
                index.entry(trigram).or_default().push(idx as u32);
            }
        }
    }

    // Entries are pushed in ascending idx order, so postings are already sorted.
    println!("Trigram index built in {:.2}s", t0.elapsed().as_secs_f64());
    index
}
