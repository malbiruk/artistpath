use artistpath::json_output::{JsonOutput, create_json_output};
use artistpath::{Args, Artist};
use rustc_hash::FxHashMap;
use uuid::Uuid;

#[test]
fn test_json_output_with_path() {
    let alice_id = Uuid::new_v4();
    let bob_id = Uuid::new_v4();
    let charlie_id = Uuid::new_v4();

    let mut artist_metadata = FxHashMap::default();
    artist_metadata.insert(
        alice_id,
        Artist {
            id: alice_id,
            name: "Alice".to_string(),
            url: "https://last.fm/alice".to_string(),
        },
    );
    artist_metadata.insert(
        bob_id,
        Artist {
            id: bob_id,
            name: "Bob".to_string(),
            url: "https://last.fm/bob".to_string(),
        },
    );
    artist_metadata.insert(
        charlie_id,
        Artist {
            id: charlie_id,
            name: "Charlie".to_string(),
            url: "https://last.fm/charlie".to_string(),
        },
    );

    let path = Some(vec![(alice_id, 0.0), (bob_id, 0.8), (charlie_id, 0.6)]);

    let args = Args {
        artist1: "Alice".to_string(),
        artist2: "Charlie".to_string(),
        min_match: 0.5,
        top_related: 100,
        weighted: true,
        show_similarity: false,
        hide_urls: false,
        show_ids: false,
        no_color: false,
        verbose: false,
        quiet: false,
        json: true,
    };

    let json_output = create_json_output(
        path,
        1234,
        1.567,
        "Alice".to_string(),
        "Charlie".to_string(),
        &args,
        &artist_metadata,
    );

    assert_eq!(json_output.query.from, "Alice");
    assert_eq!(json_output.query.to, "Charlie");
    assert!(json_output.query.options.weighted);
    assert_eq!(json_output.query.options.min_match, 0.5);
    assert_eq!(json_output.query.options.top_related, 100);

    assert!(json_output.result.found);
    let path = json_output.result.path.unwrap();
    assert_eq!(path.len(), 3);

    assert_eq!(path[0].name, "Alice");
    assert_eq!(path[0].url, "https://last.fm/alice");
    assert!(path[0].similarity_to_previous.is_none());

    assert_eq!(path[1].name, "Bob");
    assert_eq!(path[1].url, "https://last.fm/bob");
    assert_eq!(path[1].similarity_to_previous, Some(0.8));

    assert_eq!(path[2].name, "Charlie");
    assert_eq!(path[2].url, "https://last.fm/charlie");
    assert_eq!(path[2].similarity_to_previous, Some(0.6));

    assert_eq!(json_output.stats.search_time_ms, 1567);
    assert_eq!(json_output.stats.nodes_explored, 1234);
}

#[test]
fn test_json_output_no_path() {
    let artist_metadata = FxHashMap::default();

    let args = Args {
        artist1: "Alice".to_string(),
        artist2: "Bob".to_string(),
        min_match: 0.0,
        top_related: 80,
        weighted: false,
        show_similarity: false,
        hide_urls: false,
        show_ids: false,
        no_color: false,
        verbose: false,
        quiet: false,
        json: true,
    };

    let json_output = create_json_output(
        None,
        5678,
        0.234,
        "Alice".to_string(),
        "Bob".to_string(),
        &args,
        &artist_metadata,
    );

    assert_eq!(json_output.query.from, "Alice");
    assert_eq!(json_output.query.to, "Bob");
    assert!(!json_output.result.found);
    assert!(json_output.result.path.is_none());
    assert_eq!(json_output.stats.search_time_ms, 234);
    assert_eq!(json_output.stats.nodes_explored, 5678);
}

#[test]
fn test_json_serialization() {
    let alice_id = Uuid::new_v4();
    let bob_id = Uuid::new_v4();

    let mut artist_metadata = FxHashMap::default();
    artist_metadata.insert(
        alice_id,
        Artist {
            id: alice_id,
            name: "Alice".to_string(),
            url: "https://last.fm/alice".to_string(),
        },
    );
    artist_metadata.insert(
        bob_id,
        Artist {
            id: bob_id,
            name: "Bob".to_string(),
            url: "https://last.fm/bob".to_string(),
        },
    );

    let path = Some(vec![(alice_id, 0.0), (bob_id, 0.9)]);

    let args = Args {
        artist1: "Alice".to_string(),
        artist2: "Bob".to_string(),
        min_match: 0.0,
        top_related: 80,
        weighted: false,
        show_similarity: false,
        hide_urls: false,
        show_ids: false,
        no_color: false,
        verbose: false,
        quiet: false,
        json: true,
    };

    let json_output = create_json_output(
        path,
        100,
        0.1,
        "Alice".to_string(),
        "Bob".to_string(),
        &args,
        &artist_metadata,
    );

    let json_string = serde_json::to_string(&json_output).unwrap();
    assert!(json_string.contains("\"from\":\"Alice\""));
    assert!(json_string.contains("\"to\":\"Bob\""));
    assert!(json_string.contains("\"found\":true"));
    assert!(json_string.contains("\"similarity_to_previous\":0.9"));

    // Verify it can be deserialized back
    let deserialized: JsonOutput = serde_json::from_str(&json_string).unwrap();
    assert_eq!(deserialized.query.from, "Alice");
    assert_eq!(deserialized.query.to, "Bob");
}
