use artistpath::*;
use clap::Parser;
use std::path::Path;

fn main() {
    let args = Args::parse();

    let graph_path = Path::new("../data/graph.bin");
    let metadata_path = Path::new("../data/metadata.bin");

    let (lookup, metadata, binary_index) = parse_unified_metadata(metadata_path);

    let artist1_id = match find_artist_id(&args.artist1, &lookup) {
        Ok(id) => id,
        Err(e) => {
            eprintln!("❌ Error: {}", e);
            std::process::exit(1);
        }
    };

    let artist2_id = match find_artist_id(&args.artist2, &lookup) {
        Ok(id) => id,
        Err(e) => {
            eprintln!("❌ Error: {}", e);
            std::process::exit(1);
        }
    };


    // Get correct artist names from metadata
    let artist1_name = &metadata[&artist1_id].name;
    let artist2_name = &metadata[&artist2_id].name;

    println!(
        r#"🎵 Finding path from "{}" to "{}""#,
        artist1_name, artist2_name
    );

    if args.weighted {
        println!("⚙️ Using weighted pathfinding (Dijkstra)");
    } else {
        println!("⚙️ Using shortest hop pathfinding (BFS)");
    }

    if args.min_match > 0.0 {
        println!(
            "⚡ Filtering connections with similarity >= {:.2}",
            args.min_match
        );
    }
    if args.top_related != 80 {
        println!("🔝 Using top {} connections per artist", args.top_related);
    }

    println!("🔍 Searching...");

    let (path, visited_count, elapsed_time) = if args.weighted {
        todo!("Weighted pathfinding not yet implemented")
    } else {
        bfs_find_path(artist1_id, artist2_id, graph_path, &binary_index, &args)
    };

    display_results(
        args,
        &metadata,
        path,
        artist1_name,
        artist2_name,
        visited_count,
        elapsed_time,
    );
}

fn display_results(
    args: Args,
    metadata: &rustc_hash::FxHashMap<uuid::Uuid, Artist>,
    path: Option<Vec<(uuid::Uuid, f32)>>,
    artist1_name: &str,
    artist2_name: &str,
    visited_count: usize,
    elapsed_time: f64,
) {
    println!("\n---\n");

    match path {
        Some(path) => {
            println!("✅ Found path with {} steps:\n", path.len() - 1);

            for (i, (id, similarity)) in path.iter().enumerate() {
                let artist = &metadata[id];
                let number = format!("{}.", i + 1);

                let mut line = format!(r#"{:3} "{}""#, number, artist.name);

                if args.show_similarity && i > 0 {
                    line.push_str(&format!(" [similarity: {:.3}]", similarity));
                }

                if !args.hide_urls {
                    line.push_str(&format!(" - {}", artist.url));
                }

                println!("{}", line);
            }

            println!("\n---\n");
            println!(
                "📊 Explored {} artists in {:.3} sec",
                format_number(visited_count),
                elapsed_time
            );
        }

        None => {
            println!(
                r#"❌ No path found between "{}" and "{}""#,
                artist1_name, artist2_name
            );
            println!("\n---\n");
            println!(
                "📊 Explored {} artists in {:.3} sec",
                format_number(visited_count),
                elapsed_time
            );
        }
    }
}
