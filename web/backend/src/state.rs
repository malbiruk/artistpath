use artistpath_core::{Artist, parse_unified_metadata};
use memmap2::Mmap;
use rustc_hash::FxHashMap;
use std::fs::File;
use std::path::Path;
use uuid::Uuid;

pub struct AppState {
    pub name_lookup: FxHashMap<String, Uuid>,
    pub artist_metadata: FxHashMap<Uuid, Artist>,
    pub graph_index: FxHashMap<Uuid, u64>,
    pub graph_mmap: Mmap,
}

impl AppState {
    pub fn new() -> Result<Self, Box<dyn std::error::Error>> {
        let metadata_path = Path::new("../../data/metadata.bin");
        let graph_path = Path::new("../../data/graph.bin");
        
        let (name_lookup, artist_metadata, graph_index) = 
            parse_unified_metadata(metadata_path);
        
        let graph_file = File::open(graph_path)?;
        let graph_mmap = unsafe { Mmap::map(&graph_file)? };
        
        println!("Loaded {} artists", artist_metadata.len());
        println!("Graph file: {} MB", graph_mmap.len() / 1_000_000);
        
        Ok(Self {
            name_lookup,
            artist_metadata,
            graph_index,
            graph_mmap,
        })
    }
}