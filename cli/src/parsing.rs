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

pub fn parse_unified_metadata(
    metadata_path: &Path,
) -> (
    FxHashMap<String, Uuid>,
    FxHashMap<Uuid, Artist>,
    FxHashMap<Uuid, u64>,
) {
    let data = std::fs::read(metadata_path).expect("Should be able to read metadata binary file");
    let mut cursor = Cursor::new(&data);

    // Read header: 3 uint32 offsets
    let lookup_offset = cursor
        .read_u32::<LittleEndian>()
        .expect("Should read lookup offset") as usize;
    let metadata_offset = cursor
        .read_u32::<LittleEndian>()
        .expect("Should read metadata offset") as usize;
    let index_offset = cursor
        .read_u32::<LittleEndian>()
        .expect("Should read index offset") as usize;

    // Parse Section 1: Lookup (clean_name -> UUID)
    let mut cursor = Cursor::new(&data[lookup_offset..]);
    let lookup_count = cursor
        .read_u32::<LittleEndian>()
        .expect("Should read lookup count") as usize;
    let mut lookup = FxHashMap::with_capacity_and_hasher(lookup_count, Default::default());

    for _ in 0..lookup_count {
        // Read name length and name
        let name_len = cursor
            .read_u16::<LittleEndian>()
            .expect("Should read name length") as usize;
        let mut name_bytes = vec![0u8; name_len];
        cursor
            .read_exact(&mut name_bytes)
            .expect("Should read name");
        let name = String::from_utf8(name_bytes).expect("Should parse name as UTF-8");

        // Read UUID
        let mut uuid_bytes = [0u8; 16];
        cursor
            .read_exact(&mut uuid_bytes)
            .expect("Should read UUID");
        let uuid = Uuid::from_bytes(uuid_bytes);

        lookup.insert(name, uuid);
    }

    // Parse Section 2: Metadata (UUID -> Artist)
    let mut cursor = Cursor::new(&data[metadata_offset..]);
    let metadata_count = cursor
        .read_u32::<LittleEndian>()
        .expect("Should read metadata count") as usize;
    let mut metadata = FxHashMap::with_capacity_and_hasher(metadata_count, Default::default());

    for _ in 0..metadata_count {
        // Read UUID
        let mut uuid_bytes = [0u8; 16];
        cursor
            .read_exact(&mut uuid_bytes)
            .expect("Should read UUID");
        let uuid = Uuid::from_bytes(uuid_bytes);

        // Read name length and name
        let name_len = cursor
            .read_u16::<LittleEndian>()
            .expect("Should read name length") as usize;
        let mut name_bytes = vec![0u8; name_len];
        cursor
            .read_exact(&mut name_bytes)
            .expect("Should read name");
        let name = String::from_utf8(name_bytes).expect("Should parse name as UTF-8");

        // Read URL length and URL
        let url_len = cursor
            .read_u16::<LittleEndian>()
            .expect("Should read URL length") as usize;
        let mut url_bytes = vec![0u8; url_len];
        cursor.read_exact(&mut url_bytes).expect("Should read URL");
        let url = String::from_utf8(url_bytes).expect("Should parse URL as UTF-8");

        metadata.insert(
            uuid,
            Artist {
                id: uuid,
                name,
                url,
            },
        );
    }

    // Parse Section 3: Index (UUID -> file position)
    let mut cursor = Cursor::new(&data[index_offset..]);
    let index_count = cursor
        .read_u32::<LittleEndian>()
        .expect("Should read index count") as usize;
    let mut index = FxHashMap::with_capacity_and_hasher(index_count, Default::default());

    for _ in 0..index_count {
        // Read UUID
        let mut uuid_bytes = [0u8; 16];
        cursor
            .read_exact(&mut uuid_bytes)
            .expect("Should read UUID");
        let uuid = Uuid::from_bytes(uuid_bytes);

        // Read position
        let position = cursor
            .read_u64::<LittleEndian>()
            .expect("Should read position");

        index.insert(uuid, position);
    }

    (lookup, metadata, index)
}

pub fn find_artist_id(name: &str, lookup: &FxHashMap<String, Uuid>) -> Result<Uuid, String> {
    let clean_name = clean_str(name);
    lookup
        .get(&clean_name)
        .copied()
        .ok_or_else(|| format!("Artist '{}' not found in database", name))
}
