use crate::string_normalization::clean_str;
use byteorder::{LittleEndian, ReadBytesExt};
use rustc_hash::FxHashMap;
use std::{
    io::{Cursor, Read},
    path::Path,
};
use uuid::Uuid;

pub struct Artist {
    pub id: Uuid,
    pub name: String,
    pub url: String,
}

struct SectionOffsets {
    lookup: usize,
    metadata: usize,
    forward_index: usize,
    reverse_index: usize,
}

type NameLookup = FxHashMap<String, Vec<Uuid>>;
type ArtistMetadata = FxHashMap<Uuid, Artist>;
type GraphIndex = FxHashMap<Uuid, u64>;

pub fn parse_unified_metadata(metadata_path: &Path) -> (NameLookup, ArtistMetadata, GraphIndex, GraphIndex) {
    let binary_data = read_binary_file(metadata_path);
    let section_offsets = read_section_offsets(&binary_data);
    
    let name_lookup = parse_name_lookup_section(&binary_data, section_offsets.lookup);
    let artist_metadata = parse_artist_metadata_section(&binary_data, section_offsets.metadata);
    let forward_index = parse_graph_index_section(&binary_data, section_offsets.forward_index);
    let reverse_index = parse_graph_index_section(&binary_data, section_offsets.reverse_index);
    
    (name_lookup, artist_metadata, forward_index, reverse_index)
}

fn read_binary_file(file_path: &Path) -> Vec<u8> {
    std::fs::read(file_path).expect("Should be able to read metadata binary file")
}

fn read_section_offsets(data: &[u8]) -> SectionOffsets {
    let mut cursor = Cursor::new(data);
    
    SectionOffsets {
        lookup: cursor.read_u32::<LittleEndian>().expect("Should read lookup offset") as usize,
        metadata: cursor.read_u32::<LittleEndian>().expect("Should read metadata offset") as usize,
        forward_index: cursor.read_u32::<LittleEndian>().expect("Should read forward index offset") as usize,
        reverse_index: cursor.read_u32::<LittleEndian>().expect("Should read reverse index offset") as usize,
    }
}

fn parse_name_lookup_section(data: &[u8], offset: usize) -> NameLookup {
    let mut cursor = Cursor::new(&data[offset..]);
    let entry_count = cursor.read_u32::<LittleEndian>().expect("Should read lookup count") as usize;
    let mut name_lookup = FxHashMap::with_capacity_and_hasher(entry_count, Default::default());
    
    for _ in 0..entry_count {
        let clean_name = read_length_prefixed_string(&mut cursor);
        let uuid_count = cursor.read_u16::<LittleEndian>().expect("Should read UUID count") as usize;
        let mut uuids = Vec::with_capacity(uuid_count);
        for _ in 0..uuid_count {
            uuids.push(read_uuid(&mut cursor));
        }
        name_lookup.insert(clean_name, uuids);
    }
    
    name_lookup
}

fn parse_artist_metadata_section(data: &[u8], offset: usize) -> ArtistMetadata {
    let mut cursor = Cursor::new(&data[offset..]);
    let entry_count = cursor.read_u32::<LittleEndian>().expect("Should read metadata count") as usize;
    let mut artist_metadata = FxHashMap::with_capacity_and_hasher(entry_count, Default::default());
    
    for _ in 0..entry_count {
        let artist_uuid = read_uuid(&mut cursor);
        let artist_name = read_length_prefixed_string(&mut cursor);
        let artist_url = read_length_prefixed_string(&mut cursor);
        
        let artist = Artist {
            id: artist_uuid,
            name: artist_name,
            url: artist_url,
        };
        
        artist_metadata.insert(artist_uuid, artist);
    }
    
    artist_metadata
}

fn parse_graph_index_section(data: &[u8], offset: usize) -> GraphIndex {
    let mut cursor = Cursor::new(&data[offset..]);
    let entry_count = cursor.read_u32::<LittleEndian>().expect("Should read index count") as usize;
    let mut graph_index = FxHashMap::with_capacity_and_hasher(entry_count, Default::default());
    
    for _ in 0..entry_count {
        let artist_uuid = read_uuid(&mut cursor);
        let file_position = cursor.read_u64::<LittleEndian>().expect("Should read position");
        graph_index.insert(artist_uuid, file_position);
    }
    
    graph_index
}

fn read_length_prefixed_string(cursor: &mut Cursor<&[u8]>) -> String {
    let string_length = cursor.read_u16::<LittleEndian>().expect("Should read string length") as usize;
    let mut string_bytes = vec![0u8; string_length];
    cursor.read_exact(&mut string_bytes).expect("Should read string bytes");
    String::from_utf8(string_bytes).expect("Should parse string as UTF-8")
}

fn read_uuid(cursor: &mut Cursor<&[u8]>) -> Uuid {
    let mut uuid_bytes = [0u8; 16];
    cursor.read_exact(&mut uuid_bytes).expect("Should read UUID bytes");
    Uuid::from_bytes(uuid_bytes)
}

pub fn find_artist_id(name: &str, lookup: &FxHashMap<String, Vec<Uuid>>) -> Result<Uuid, String> {
    let clean_name = clean_str(name);
    lookup
        .get(&clean_name)
        .and_then(|uuids| uuids.first().copied())
        .ok_or_else(|| format!("Artist '{}' not found in database", name))
}
