use std::{path::PathBuf, error::Error};
use artistpath_core::{Artist, parse_unified_metadata};
use uuid::Uuid;

use crate::download;

pub type NameLookup = rustc_hash::FxHashMap<String, Vec<Uuid>>;
pub type ArtistMetadata = rustc_hash::FxHashMap<Uuid, Artist>;
pub type GraphIndex = rustc_hash::FxHashMap<Uuid, u64>;

pub struct ArtistPathApp {
    pub graph_path: PathBuf,
    pub reverse_graph_path: PathBuf,
    pub metadata_path: PathBuf,
}

impl ArtistPathApp {
    pub fn new(data_path: Option<String>) -> Result<Self, Box<dyn Error>> {
        let data_dir = if let Some(path) = data_path {
            // User specified a custom data path
            let path = PathBuf::from(path);
            if !path.exists() {
                return Err(format!("Data path does not exist: {:?}", path).into());
            }
            path
        } else {
            // Use default path and auto-download if needed
            download::ensure_data_downloaded()?
        };
        
        let graph_path = data_dir.join("graph.bin");
        let reverse_graph_path = data_dir.join("rev-graph.bin");
        let metadata_path = data_dir.join("metadata.bin");
        
        // Verify data files exist
        if !graph_path.exists() || !metadata_path.exists() {
            return Err(format!(
                "Data files not found in {:?}. Expected graph.bin and metadata.bin", 
                data_dir
            ).into());
        }
        
        if !reverse_graph_path.exists() {
            return Err(format!(
                "Reverse graph file not found: {:?}. Expected rev-graph.bin", 
                reverse_graph_path
            ).into());
        }
        
        Ok(Self {
            graph_path,
            reverse_graph_path,
            metadata_path,
        })
    }

    pub fn load_data(&self) -> (NameLookup, ArtistMetadata, GraphIndex, GraphIndex) {
        parse_unified_metadata(&self.metadata_path)
    }
}