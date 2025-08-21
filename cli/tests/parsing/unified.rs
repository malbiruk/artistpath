use artistpath::{find_artist_id, parse_unified_metadata};
use byteorder::{LittleEndian, WriteBytesExt};
use std::io::{Seek, Write};
use tempfile::NamedTempFile;
use uuid::Uuid;

fn create_test_unified_binary() -> (NamedTempFile, Uuid, Uuid) {
    let mut file = NamedTempFile::new().unwrap();
    let alice_id = Uuid::new_v4();
    let bob_id = Uuid::new_v4();

    // Header: 3 uint32 offsets (placeholders for now)
    let header_pos = file.stream_position().unwrap();
    file.write_u32::<LittleEndian>(0).unwrap(); // lookup_offset placeholder
    file.write_u32::<LittleEndian>(0).unwrap(); // metadata_offset placeholder
    file.write_u32::<LittleEndian>(0).unwrap(); // index_offset placeholder

    // Section 1: Lookup
    let lookup_offset = file.stream_position().unwrap();
    file.write_u32::<LittleEndian>(2).unwrap(); // 2 entries

    // Entry 1: "alice" -> alice_id
    let alice_name = b"alice";
    file.write_u16::<LittleEndian>(alice_name.len() as u16)
        .unwrap();
    file.write_all(alice_name).unwrap();
    file.write_all(&alice_id.into_bytes()).unwrap();

    // Entry 2: "bob" -> bob_id
    let bob_name = b"bob";
    file.write_u16::<LittleEndian>(bob_name.len() as u16)
        .unwrap();
    file.write_all(bob_name).unwrap();
    file.write_all(&bob_id.into_bytes()).unwrap();

    // Section 2: Metadata
    let metadata_offset = file.stream_position().unwrap();
    file.write_u32::<LittleEndian>(2).unwrap(); // 2 entries

    // Entry 1: alice_id -> Alice + URL
    file.write_all(&alice_id.into_bytes()).unwrap();
    let alice_full_name = b"Alice";
    let alice_url = b"https://example.com/alice";
    file.write_u16::<LittleEndian>(alice_full_name.len() as u16)
        .unwrap();
    file.write_all(alice_full_name).unwrap();
    file.write_u16::<LittleEndian>(alice_url.len() as u16)
        .unwrap();
    file.write_all(alice_url).unwrap();

    // Entry 2: bob_id -> Bob + URL
    file.write_all(&bob_id.into_bytes()).unwrap();
    let bob_full_name = b"Bob";
    let bob_url = b"https://example.com/bob";
    file.write_u16::<LittleEndian>(bob_full_name.len() as u16)
        .unwrap();
    file.write_all(bob_full_name).unwrap();
    file.write_u16::<LittleEndian>(bob_url.len() as u16)
        .unwrap();
    file.write_all(bob_url).unwrap();

    // Section 3: Index
    let index_offset = file.stream_position().unwrap();
    file.write_u32::<LittleEndian>(2).unwrap(); // 2 entries

    // Entry 1: alice_id -> position 0
    file.write_all(&alice_id.into_bytes()).unwrap();
    file.write_u64::<LittleEndian>(0).unwrap();

    // Entry 2: bob_id -> position 100
    file.write_all(&bob_id.into_bytes()).unwrap();
    file.write_u64::<LittleEndian>(100).unwrap();

    // Update header with actual offsets
    let end_pos = file.stream_position().unwrap();
    file.seek(std::io::SeekFrom::Start(header_pos)).unwrap();
    file.write_u32::<LittleEndian>(lookup_offset as u32)
        .unwrap();
    file.write_u32::<LittleEndian>(metadata_offset as u32)
        .unwrap();
    file.write_u32::<LittleEndian>(index_offset as u32).unwrap();
    file.seek(std::io::SeekFrom::Start(end_pos)).unwrap();

    file.flush().unwrap();

    (file, alice_id, bob_id)
}

#[test]
fn test_parse_unified_metadata() {
    let (file, alice_id, bob_id) = create_test_unified_binary();

    let (lookup, metadata, index) = parse_unified_metadata(file.path());

    // Test lookup
    assert_eq!(lookup.len(), 2);
    assert_eq!(lookup.get("alice"), Some(&alice_id));
    assert_eq!(lookup.get("bob"), Some(&bob_id));

    // Test metadata
    assert_eq!(metadata.len(), 2);
    let alice_artist = metadata.get(&alice_id).unwrap();
    assert_eq!(alice_artist.name, "Alice");
    assert_eq!(alice_artist.url, "https://example.com/alice");

    let bob_artist = metadata.get(&bob_id).unwrap();
    assert_eq!(bob_artist.name, "Bob");
    assert_eq!(bob_artist.url, "https://example.com/bob");

    // Test index
    assert_eq!(index.len(), 2);
    assert_eq!(index.get(&alice_id), Some(&0));
    assert_eq!(index.get(&bob_id), Some(&100));
}

#[test]
fn test_find_artist_id_with_unified() {
    let (file, alice_id, _bob_id) = create_test_unified_binary();
    let (lookup, _metadata, _index) = parse_unified_metadata(file.path());

    // Test successful lookup
    let result = find_artist_id("alice", &lookup);
    assert_eq!(result, Ok(alice_id));

    // Test case insensitive
    let result = find_artist_id("ALICE", &lookup);
    assert_eq!(result, Ok(alice_id));

    // Test not found
    let result = find_artist_id("nonexistent", &lookup);
    assert!(result.is_err());
    assert!(result.unwrap_err().contains("not found"));
}

#[test]
fn test_parse_unified_empty() {
    let mut file = NamedTempFile::new().unwrap();

    // Header with offsets pointing to empty sections
    file.write_u32::<LittleEndian>(12).unwrap(); // lookup_offset
    file.write_u32::<LittleEndian>(16).unwrap(); // metadata_offset
    file.write_u32::<LittleEndian>(20).unwrap(); // index_offset

    // Empty sections
    file.write_u32::<LittleEndian>(0).unwrap(); // 0 lookup entries
    file.write_u32::<LittleEndian>(0).unwrap(); // 0 metadata entries
    file.write_u32::<LittleEndian>(0).unwrap(); // 0 index entries

    file.flush().unwrap();

    let (lookup, metadata, index) = parse_unified_metadata(file.path());

    assert!(lookup.is_empty());
    assert!(metadata.is_empty());
    assert!(index.is_empty());
}
