use artistpath::parse_metadata;
use std::io::Write;
use tempfile::NamedTempFile;
use uuid::Uuid;

#[test]
fn test_parse_metadata_empty() {
    let file = NamedTempFile::new().unwrap();

    let metadata = parse_metadata(file.path());
    assert!(metadata.is_empty());
}

#[test]
fn test_parse_metadata_single_artist() {
    let mut file = NamedTempFile::new().unwrap();
    let uuid = Uuid::new_v4();

    writeln!(
        file,
        r#"{{"id": "{}", "name": "Test Artist", "url": "https://example.com"}}"#,
        uuid
    )
    .unwrap();

    let metadata = parse_metadata(file.path());
    assert_eq!(metadata.len(), 1);

    let artist = metadata.get(&uuid).unwrap();
    assert_eq!(artist.name, "Test Artist");
    assert_eq!(artist.url, "https://example.com");
}

#[test]
fn test_parse_metadata_multiple_artists() {
    let mut file = NamedTempFile::new().unwrap();
    let uuid1 = Uuid::new_v4();
    let uuid2 = Uuid::new_v4();

    writeln!(
        file,
        r#"{{"id": "{}", "name": "Artist One", "url": "https://example.com/1"}}"#,
        uuid1
    )
    .unwrap();
    writeln!(
        file,
        r#"{{"id": "{}", "name": "Artist Two", "url": "https://example.com/2"}}"#,
        uuid2
    )
    .unwrap();

    let metadata = parse_metadata(file.path());
    assert_eq!(metadata.len(), 2);

    assert_eq!(metadata.get(&uuid1).unwrap().name, "Artist One");
    assert_eq!(metadata.get(&uuid2).unwrap().name, "Artist Two");
}

#[test]
fn test_parse_metadata_ignores_empty_lines() {
    let mut file = NamedTempFile::new().unwrap();
    let uuid = Uuid::new_v4();

    writeln!(file).unwrap();
    writeln!(
        file,
        r#"{{"id": "{}", "name": "Test Artist", "url": "https://example.com"}}"#,
        uuid
    )
    .unwrap();
    writeln!(file, "   ").unwrap();

    let metadata = parse_metadata(file.path());
    assert_eq!(metadata.len(), 1);
}
