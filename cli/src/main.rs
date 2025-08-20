mod string_normalization;
use clap::Parser;
use serde::Deserialize;
use std::{collections::HashMap, fs, path::Path};
use uuid::Uuid;

#[derive(Parser)]
#[command(name = "artistpath")]
#[command(about = "Find the shortest connection path between any two music artists")]
struct Args {
    /// First artist name
    artist1: String,

    /// Second artist name
    artist2: String,

    /// Only use connections with similarity >= threshold (0.0-1.0)
    #[arg(short = 'm', long, value_name = "SIMILARITY", default_value = "0.0")]
    min_match: f32,

    /// Limit to top N connections per artist
    #[arg(short = 't', long, value_name = "COUNT", default_value = "80")]
    top_related: usize,

    /// Use weighted pathfinding (considers similarity scores)
    #[arg(short, long)]
    weighted: bool,

    /// Hide artist URLs from output (URLs shown by default)
    #[arg(short = 'u', long)]
    hide_urls: bool,

    /// Show artist UUIDs in output
    #[arg(short = 'i', long)]
    show_ids: bool,

    /// Show similarity scores between connected artists
    #[arg(short = 'W', long)]
    show_weights: bool,
}

#[derive(Deserialize)]
struct GraphNode {
    id: Uuid,
    connections: Vec<(Uuid, f32)>,
}

#[derive(Deserialize)]
struct Artist {
    id: Uuid,
    name: String,
    url: String,
}

fn main() {
    let args = Args::parse();

    let graph_path = Path::new("../data/graph.ndjson");
    let metadata_path = Path::new("../data/metadata.ndjson");
    let lookup_path = Path::new("../data/lookup.json");

    println!(
        "🎵 Finding path from '{}' to '{}'",
        args.artist1, args.artist2
    );

    if args.weighted {
        println!("📊 Using weighted pathfinding (Dijkstra)");
    } else {
        println!("🔍 Using shortest hop pathfinding (BFS)");
    }

    // Print active filters
    if args.min_match > 0.0 {
        println!(
            "⚡ Filtering connections with similarity >= {:.2}",
            args.min_match
        );
    }
    if args.top_related != 80 {
        println!("🔝 Using top {} connections per artist", args.top_related);
    }

    // println!("\n📖 Loading lookup table...");
    // let lookup = parse_lookup(lookup_path);
    // println!("✅ Loaded {} artist names", lookup.len());

    // TODO: Convert artist names to UUIDs
    // TODO: Implement streaming pathfinding
    // TODO: Format and display results

    println!("🎉 Done!");
}

fn parse_metadata(metadata_path: &Path) -> HashMap<Uuid, Artist> {
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

fn parse_lookup(lookup_path: &Path) -> HashMap<String, Uuid> {
    let data = fs::read_to_string(lookup_path).expect("Should be able to read lookup file");
    serde_json::from_str(&data).expect("Should be able to parse lookup")
}
