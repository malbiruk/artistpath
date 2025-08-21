use crate::string_normalization::clean_str;
use rustc_hash::FxHashMap;
use serde::Deserialize;
use std::{fs, path::Path};
use uuid::Uuid;

#[derive(Deserialize)]
pub struct Artist {
    pub id: Uuid,
    pub name: String,
    pub url: String,
}

pub fn parse_metadata(metadata_path: &Path) -> FxHashMap<Uuid, Artist> {
    let data = fs::read_to_string(metadata_path).expect("Should be able to read metadata file");
    data.lines()
        .filter(|line| !line.trim().is_empty())
        .map(|line| {
            let artist: Artist =
                serde_json::from_str(line).expect("Should be able to parse metadata");
            (artist.id, artist)
        })
        .collect()
}

pub fn parse_lookup(lookup_path: &Path) -> FxHashMap<String, Uuid> {
    let data = fs::read_to_string(lookup_path).expect("Should be able to read lookup file");
    serde_json::from_str(&data).expect("Should be able to parse lookup")
}

pub fn parse_index(index_path: &Path) -> FxHashMap<Uuid, u64> {
    let data = fs::read_to_string(index_path).expect("Should be able to read binary index file");
    let string_index: FxHashMap<String, u64> =
        serde_json::from_str(&data).expect("Should be able to parse binary index");

    // Convert string UUIDs to Uuid objects
    string_index
        .into_iter()
        .map(|(uuid_str, position)| {
            let uuid = Uuid::parse_str(&uuid_str).expect("Should be able to parse UUID");
            (uuid, position)
        })
        .collect()
}

pub fn find_artist_id(name: &str, lookup: &FxHashMap<String, Uuid>) -> Result<Uuid, String> {
    let clean_name = clean_str(name);
    lookup
        .get(&clean_name)
        .copied()
        .ok_or_else(|| format!("Artist '{}' not found in database", name))
}
