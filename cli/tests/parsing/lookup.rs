use artistpath::{find_artist_id, parse_lookup};
use rustc_hash::FxHashMap;
use std::io::Write;
use tempfile::NamedTempFile;
use uuid::Uuid;

#[test]
fn test_find_artist_id_success() {
    let mut lookup = FxHashMap::default();
    let uuid = Uuid::new_v4();
    lookup.insert("test artist".to_string(), uuid);
    
    let result = find_artist_id("test artist", &lookup);
    assert_eq!(result, Ok(uuid));
}

#[test] 
fn test_find_artist_id_not_found() {
    let lookup = FxHashMap::default();
    
    let result = find_artist_id("nonexistent", &lookup);
    assert!(result.is_err());
    assert!(result.unwrap_err().contains("not found"));
}

#[test]
fn test_find_artist_id_case_insensitive() {
    let mut lookup = FxHashMap::default();
    let uuid = Uuid::new_v4();
    lookup.insert("test artist".to_string(), uuid);
    
    let result = find_artist_id("TEST ARTIST", &lookup);
    assert_eq!(result, Ok(uuid));
}

#[test]
fn test_parse_lookup_empty() {
    let mut file = NamedTempFile::new().unwrap();
    writeln!(file, "{{}}").unwrap();
    
    let lookup = parse_lookup(file.path());
    assert!(lookup.is_empty());
}

#[test]
fn test_parse_lookup_valid() {
    let mut file = NamedTempFile::new().unwrap();
    let uuid = Uuid::new_v4();
    writeln!(file, r#"{{"test": "{}"}}"#, uuid).unwrap();
    
    let lookup = parse_lookup(file.path());
    assert_eq!(lookup.len(), 1);
    assert_eq!(lookup.get("test"), Some(&uuid));
}