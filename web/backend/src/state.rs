use artistpath_core::{Artist, parse_unified_metadata};
use memmap2::Mmap;
use rustc_hash::FxHashMap;
use std::fs::File;
use std::path::Path;
use uuid::Uuid;
use crate::lastfm::LastFmClient;
use crate::itunes::ITunesClient;

pub struct AppState {
    pub name_lookup: FxHashMap<String, Vec<Uuid>>,
    pub artist_metadata: FxHashMap<Uuid, Artist>,
    pub graph_index: FxHashMap<Uuid, u64>,
    pub graph_mmap: Mmap,
    pub lastfm_client: LastFmClient,
    pub itunes_client: ITunesClient,
}

impl AppState {
    pub fn new() -> Result<Self, Box<dyn std::error::Error>> {
        let metadata_path_str = std::env::var("METADATA_PATH").unwrap_or_else(|_| "../../data/metadata.bin".to_string());
        let graph_path_str = std::env::var("GRAPH_PATH").unwrap_or_else(|_| "../../data/graph.bin".to_string());
        let metadata_path = Path::new(&metadata_path_str);
        let graph_path = Path::new(&graph_path_str);
        
        let (name_lookup, artist_metadata, graph_index) = 
            parse_unified_metadata(metadata_path);
        
        let graph_file = File::open(graph_path)?;
        let graph_mmap = unsafe { Mmap::map(&graph_file)? };
        
        // Read Last.fm API key from environment or config
        let api_key = std::env::var("LASTFM_API_KEY")
            .or_else(|_| std::env::var("API_KEY"))
            .expect("LASTFM_API_KEY or API_KEY environment variable must be set");
        
        let lastfm_client = LastFmClient::new(api_key);
        let itunes_client = ITunesClient::new();
        
        println!("Loaded {} artists", artist_metadata.len());
        println!("Graph file: {} MB", graph_mmap.len() / 1_000_000);
        
        Ok(Self {
            name_lookup,
            artist_metadata,
            graph_index,
            graph_mmap,
            lastfm_client,
            itunes_client,
        })
    }
}