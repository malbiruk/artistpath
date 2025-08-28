use artistpath_core::{find_artist_id};
use rustc_hash::FxHashMap;
use uuid::Uuid;

#[test]
fn test_find_artist_fuzzy_match() {
    let mut lookup = FxHashMap::default();
    let id1 = Uuid::new_v4();
    let id2 = Uuid::new_v4();
    
    lookup.insert("taylor swift".to_string(), id1);
    lookup.insert("the beatles".to_string(), id2);
    
    // Test various case variations
    assert_eq!(find_artist_id("TAYLOR SWIFT", &lookup), Ok(id1));
    assert_eq!(find_artist_id("Taylor Swift", &lookup), Ok(id1));
    assert_eq!(find_artist_id("taylor swift", &lookup), Ok(id1));
    assert_eq!(find_artist_id("TaYlOr SwIfT", &lookup), Ok(id1));
    
    // Test with extra spaces
    assert_eq!(find_artist_id("  taylor  swift  ", &lookup), Ok(id1));
    assert_eq!(find_artist_id("\ttaylor\tswift\t", &lookup), Ok(id1));
}

#[test]
fn test_find_artist_unicode_normalization() {
    let mut lookup = FxHashMap::default();
    let id = Uuid::new_v4();
    
    // Store normalized version
    lookup.insert("bjork".to_string(), id);
    
    // Should find with unicode input
    assert_eq!(find_artist_id("Björk", &lookup), Ok(id));
    assert_eq!(find_artist_id("BJÖRK", &lookup), Ok(id));
}

#[test]
fn test_find_artist_not_found_message() {
    let lookup = FxHashMap::default();
    
    let result = find_artist_id("Nonexistent Artist", &lookup);
    assert!(result.is_err());
    assert!(result.unwrap_err().contains("Artist 'Nonexistent Artist' not found"));
}

#[test]
fn test_find_artist_empty_lookup() {
    let lookup = FxHashMap::default();
    
    let result = find_artist_id("Any Artist", &lookup);
    assert!(result.is_err());
}

#[test]
fn test_find_artist_empty_name() {
    let mut lookup = FxHashMap::default();
    let id = Uuid::new_v4();
    lookup.insert("test".to_string(), id);
    
    let result = find_artist_id("", &lookup);
    assert!(result.is_err());
    
    let result = find_artist_id("   ", &lookup);
    assert!(result.is_err());
}