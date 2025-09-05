use artistpath_core::{Artist, parse_unified_metadata, bfs_find_path, dijkstra_find_path, PathfindingConfig, string_normalization::clean_str};
mod args;
mod colors;
mod json_output;
mod utils;
mod download;

use args::Args;
use colors::ColorScheme;
use json_output::{create_json_output, print_json_output};
use utils::format_number;
use clap::Parser;
use memmap2::Mmap;
use std::{fs::File, path::{Path, PathBuf}};
use uuid::Uuid;

type NameLookup = rustc_hash::FxHashMap<String, Vec<Uuid>>;
type ArtistMetadata = rustc_hash::FxHashMap<Uuid, Artist>;
type GraphIndex = rustc_hash::FxHashMap<Uuid, u64>;

struct ArtistPathApp {
    graph_path: PathBuf,
    metadata_path: PathBuf,
}

impl ArtistPathApp {
    fn new(data_path: Option<String>) -> Result<Self, Box<dyn std::error::Error>> {
        let data_dir = if let Some(path) = data_path {
            // User specified a custom data path
            let path = PathBuf::from(path);
            if !path.exists() {
                return Err(format!("Data path does not exist: {:?}", path).into());
            }
            path
        } else {
            // Use default path and auto-download if needed
            download::ensure_data_downloaded()?
        };
        
        let graph_path = data_dir.join("graph.bin");
        let metadata_path = data_dir.join("metadata.bin");
        
        // Verify data files exist
        if !graph_path.exists() || !metadata_path.exists() {
            return Err(format!(
                "Data files not found in {:?}. Expected graph.bin and metadata.bin", 
                data_dir
            ).into());
        }
        
        Ok(Self {
            graph_path,
            metadata_path,
        })
    }

    fn load_data(&self) -> (NameLookup, ArtistMetadata, GraphIndex, GraphIndex) {
        parse_unified_metadata(&self.metadata_path)
    }
}

struct SearchRequest {
    from_artist: Uuid,
    to_artist: Uuid,
    from_name: String,
    to_name: String,
    search_args: Args,
}

struct SearchResult {
    path: Option<Vec<(Uuid, f32)>>,
    artists_visited: usize,
    search_duration: f64,
    from_name: String,
    to_name: String,
    display_options: Args,
}

fn main() {
    let search_args = Args::parse();
    let json_mode = search_args.json;
    let data_path = search_args.data_path.clone();
    let colors = ColorScheme::new(!search_args.no_color);
    let app = match ArtistPathApp::new(data_path) {
        Ok(app) => app,
        Err(e) => {
            eprintln!("Failed to initialize: {}", e);
            std::process::exit(1);
        }
    };
    let (name_lookup, artist_metadata, graph_index, _reverse_index) = app.load_data();

    let search_request = match create_search_request(search_args, &name_lookup, &artist_metadata) {
        Ok(request) => request,
        Err(error_message) => {
            if json_mode {
                eprintln!(
                    "{}",
                    serde_json::json!({
                        "error": error_message
                    })
                );
            } else {
                eprintln!("{}", colors.error(&format!("❌ Error: {}", error_message)));
            }
            std::process::exit(1);
        }
    };

    if search_request.search_args.verbose && !search_request.search_args.json {
        display_search_info(&search_request, &colors);
    }

    let search_result = execute_pathfinding_search(search_request, &app.graph_path, &graph_index);
    
    if search_result.display_options.json {
        let json_output = create_json_output(
            search_result.path,
            search_result.artists_visited,
            search_result.search_duration,
            search_result.from_name,
            search_result.to_name,
            &search_result.display_options,
            &artist_metadata,
        );
        print_json_output(&json_output);
    } else {
        display_search_results(search_result, &artist_metadata, &colors);
    }
}

fn find_best_artist_match(
    name: &str,
    name_lookup: &NameLookup,
    artist_metadata: &ArtistMetadata,
) -> Result<Uuid, String> {
    let lowercase_query = name.to_lowercase();
    let clean_query = clean_str(name);
    
    // Try to get all potential matches from the lookup
    if let Some(artist_ids) = name_lookup.get(&clean_query) {
        if artist_ids.is_empty() {
            return Err(format!("Artist '{}' not found in database", name));
        }
        
        // If only one match, return it
        if artist_ids.len() == 1 {
            return Ok(artist_ids[0]);
        }
        
        // Multiple matches - prioritize exact match (case-insensitive)
        for &artist_id in artist_ids {
            if let Some(artist) = artist_metadata.get(&artist_id) {
                if artist.name.to_lowercase() == lowercase_query {
                    return Ok(artist_id);
                }
            }
        }
        
        // No exact match found, return the first one
        return Ok(artist_ids[0]);
    }
    
    Err(format!("Artist '{}' not found in database", name))
}

fn create_search_request(
    args: Args,
    name_lookup: &NameLookup,
    artist_metadata: &ArtistMetadata,
) -> Result<SearchRequest, String> {
    let from_artist_id = find_best_artist_match(&args.artist1, name_lookup, artist_metadata)?;
    let to_artist_id = find_best_artist_match(&args.artist2, name_lookup, artist_metadata)?;

    let from_name = artist_metadata[&from_artist_id].name.clone();
    let to_name = artist_metadata[&to_artist_id].name.clone();

    Ok(SearchRequest {
        from_artist: from_artist_id,
        to_artist: to_artist_id,
        from_name,
        to_name,
        search_args: args,
    })
}

fn display_search_info(request: &SearchRequest, colors: &ColorScheme) {
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

fn execute_pathfinding_search(
    request: SearchRequest,
    graph_path: &Path,
    graph_index: &GraphIndex,
) -> SearchResult {
    let config = PathfindingConfig::new(
        request.search_args.min_match,
        request.search_args.top_related,
        request.search_args.weighted,
    );
    
    // Open the memory-mapped file
    let graph_file = File::open(graph_path).expect("Failed to open graph file");
    let graph_mmap = unsafe { Mmap::map(&graph_file).expect("Failed to map graph file") };
    
    let (path, visited_count, elapsed_time) = if request.search_args.weighted {
        dijkstra_find_path(
            request.from_artist,
            request.to_artist,
            &graph_mmap,
            graph_index,
            &config,
        )
    } else {
        bfs_find_path(
            request.from_artist,
            request.to_artist,
            &graph_mmap,
            graph_index,
            &config,
        )
    };

    SearchResult {
        path,
        artists_visited: visited_count,
        search_duration: elapsed_time,
        from_name: request.from_name,
        to_name: request.to_name,
        display_options: request.search_args,
    }
}

fn display_search_results(
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
