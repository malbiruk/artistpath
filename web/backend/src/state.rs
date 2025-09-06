use crate::metadata_cache::MetadataCache;
use artistpath_core::{Artist, parse_unified_metadata};
use memmap2::Mmap;
use rustc_hash::FxHashMap;
use std::fs::File;
use std::path::Path;
use uuid::Uuid;

pub struct AppState {
    pub name_lookup: FxHashMap<String, Vec<Uuid>>,
    pub artist_metadata: FxHashMap<Uuid, Artist>,
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

        let (name_lookup, artist_metadata, graph_index, reverse_graph_index) = parse_unified_metadata(metadata_path);

        let graph_file = File::open(graph_path)?;
        let graph_mmap = unsafe { Mmap::map(&graph_file)? };
        
        let reverse_graph_file = File::open(reverse_graph_path)?;
        let reverse_graph_mmap = unsafe { Mmap::map(&reverse_graph_file)? };

        // Read Last.fm API key from environment or config
        let api_key = std::env::var("LASTFM_API_KEY")
            .or_else(|_| std::env::var("API_KEY"))
            .expect("LASTFM_API_KEY or API_KEY environment variable must be set");

        let metadata_cache = MetadataCache::new(api_key).await?;

        println!("Loaded {} artists", artist_metadata.len());
        println!("Forward graph file: {} MB", graph_mmap.len() / 1_000_000);
        println!("Reverse graph file: {} MB", reverse_graph_mmap.len() / 1_000_000);

        Ok(Self {
            name_lookup,
            artist_metadata,
            graph_index,
            reverse_graph_index,
            graph_mmap,
            reverse_graph_mmap,
            metadata_cache,
        })
    }
}
