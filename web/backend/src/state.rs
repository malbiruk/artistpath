use crate::itunes::ITunesClient;
use crate::lastfm::LastFmClient;
use crate::models::CachedArtistMetadata;
use artistpath_core::{Artist, parse_unified_metadata};
use memmap2::Mmap;
use rustc_hash::FxHashMap;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::Path;
use uuid::Uuid;

pub struct AppState {
    pub name_lookup: FxHashMap<String, Vec<Uuid>>,
    pub artist_metadata: FxHashMap<Uuid, Artist>,
    pub graph_index: FxHashMap<Uuid, u64>,
    pub reverse_graph_index: FxHashMap<Uuid, u64>,
    pub graph_mmap: Mmap,
    pub reverse_graph_mmap: Mmap,
    pub lastfm_client: LastFmClient,
    pub itunes_client: ITunesClient,
    pub cached_metadata: FxHashMap<Uuid, CachedArtistMetadata>,
}

impl AppState {
    pub fn new() -> Result<Self, Box<dyn std::error::Error>> {
        let metadata_path_str = std::env::var("METADATA_PATH")
            .unwrap_or_else(|_| "../../data/metadata.bin".to_string());
        let graph_path_str =
            std::env::var("GRAPH_PATH").unwrap_or_else(|_| "../../data/graph.bin".to_string());
        let reverse_graph_path_str = std::env::var("REVERSE_GRAPH_PATH")
            .unwrap_or_else(|_| "../../data/rev-graph.bin".to_string());
        let cached_metadata_path_str = std::env::var("CACHED_METADATA_PATH")
            .unwrap_or_else(|_| "../../data/artist_metadata.ndjson".to_string());

        let metadata_path = Path::new(&metadata_path_str);
        let graph_path = Path::new(&graph_path_str);
        let reverse_graph_path = Path::new(&reverse_graph_path_str);
        let cached_metadata_path = Path::new(&cached_metadata_path_str);

        let (name_lookup, artist_metadata, graph_index, reverse_graph_index) = parse_unified_metadata(metadata_path);

        let graph_file = File::open(graph_path)?;
        let graph_mmap = unsafe { Mmap::map(&graph_file)? };
        
        let reverse_graph_file = File::open(reverse_graph_path)?;
        let reverse_graph_mmap = unsafe { Mmap::map(&reverse_graph_file)? };

        // Load cached metadata if available
        let mut cached_metadata = FxHashMap::default();
        if cached_metadata_path.exists() {
            let file = File::open(cached_metadata_path)?;
            let reader = BufReader::new(file);

            for line in reader.lines().map_while(Result::ok) {
                if line.trim().is_empty() {
                    continue;
                }

                if let Ok(metadata) = serde_json::from_str::<CachedArtistMetadata>(&line) {
                    if let Ok(uuid) = Uuid::parse_str(&metadata.id) {
                        cached_metadata.insert(uuid, metadata);
                    }
                }
            }

            println!(
                "Loaded {} cached artist metadata entries",
                cached_metadata.len()
            );
        } else {
            println!(
                "No cached metadata file found at {}",
                cached_metadata_path.display()
            );
        }

        // Read Last.fm API key from environment or config
        let api_key = std::env::var("LASTFM_API_KEY")
            .or_else(|_| std::env::var("API_KEY"))
            .expect("LASTFM_API_KEY or API_KEY environment variable must be set");

        let lastfm_client = LastFmClient::new(api_key);
        let itunes_client = ITunesClient::new();

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
            lastfm_client,
            itunes_client,
            cached_metadata,
        })
    }
}
