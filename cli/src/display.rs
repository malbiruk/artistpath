use uuid::Uuid;

use crate::args::Args;
use crate::app::ArtistMetadata;
use crate::colors::ColorScheme;
use crate::search::{SearchRequest, SearchResult};
use crate::utils::format_number;

pub fn display_search_info(request: &SearchRequest, colors: &ColorScheme) {
    println!(
        "🎵 Finding path from {} to {}",
        colors.artist_name(&format!("\"{}\"", request.from_name)),
        colors.artist_name(&format!("\"{}\"", request.to_name))
    );

    if request.search_args.weighted {
        println!("⚙️  Using weighted pathfinding (Dijkstra)");
    } else {
        println!("⚙️  Using shortest hop pathfinding (BFS)");
    }

    if request.search_args.min_match > 0.0 {
        println!(
            "⚡ Filtering connections with similarity >= {}",
            colors.number(&format!("{:.2}", request.search_args.min_match))
        );
    }

    if request.search_args.top_related != 80 {
        println!(
            "🔝 Using top {} connections per artist",
            colors.number(&request.search_args.top_related.to_string())
        );
    }

    println!("🔍 Searching...");
}

pub fn display_search_results(
    result: SearchResult,
    artist_metadata: &ArtistMetadata,
    colors: &ColorScheme,
) {
    let is_verbose = result.display_options.verbose;

    if is_verbose {
        println!("\n---\n");
    }

    match result.path {
        Some(path) => {
            display_successful_path(&path, &result.display_options, artist_metadata, colors);
            if is_verbose {
                display_search_statistics(result.artists_visited, result.search_duration, colors);
            }
        }
        None => {
            println!(
                "{} {} and {}",
                colors.error("❌ No path found between"),
                colors.artist_name(&format!("\"{}\"", result.from_name)),
                colors.artist_name(&format!("\"{}\"", result.to_name))
            );
            if is_verbose {
                display_search_statistics(result.artists_visited, result.search_duration, colors);
            }
        }
    }
}

fn display_successful_path(
    path: &[(Uuid, f32)],
    display_options: &Args,
    artist_metadata: &ArtistMetadata,
    colors: &ColorScheme,
) {
    if display_options.verbose {
        let step_count = path.len() - 1;
        println!(
            "{} Found path with {} steps:\n",
            colors.success("✅"),
            colors.number(&step_count.to_string())
        );
    }

    // Show path flow first
    let path_flow = path
        .iter()
        .map(|(artist_id, _)| {
            colors
                .artist_name(&format!("\"{}\"", &artist_metadata[artist_id].name))
                .to_string()
        })
        .collect::<Vec<_>>()
        .join(" → ");
    println!("{}", path_flow);

    // Show detailed list only if not in quiet mode
    if !display_options.quiet {
        println!(); // Add blank line before detailed list
        for (step_index, (artist_id, similarity)) in path.iter().enumerate() {
            let artist_info = &artist_metadata[artist_id];
            let step_number = format!("{}.", step_index + 1);

            let formatted_line = format_path_step(
                step_number,
                &artist_info.name,
                &artist_info.url,
                *similarity,
                step_index,
                display_options,
                colors,
            );

            println!("{}", formatted_line);
        }
    }
}

fn format_path_step(
    step_number: String,
    artist_name: &str,
    artist_url: &str,
    similarity: f32,
    step_index: usize,
    display_options: &Args,
    colors: &ColorScheme,
) -> String {
    let mut formatted_line = format!(
        "{:2} {}",
        colors.step_number(&step_number),
        colors.artist_name(&format!("\"{}\"", artist_name))
    );

    if display_options.show_similarity && step_index > 0 {
        formatted_line.push_str(&format!(
            " {}{}{}",
            colors.similarity("["),
            colors.number(&format!("{:.3}", similarity)),
            colors.similarity("]")
        ));
    }

    if !display_options.hide_urls {
        formatted_line.push_str(&format!(" - {}", colors.url(artist_url)));
    }

    formatted_line
}

fn display_search_statistics(artists_visited: usize, search_duration: f64, colors: &ColorScheme) {
    println!("\n---\n");
    println!(
        "{} Explored {} artists in {} sec",
        colors.stats("📊"),
        colors.number(&format_number(artists_visited)),
        colors.number(&format!("{:.3}", search_duration))
    );
}