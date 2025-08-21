use artistpath::*;
use clap::Parser;
use std::path::Path;
use uuid::Uuid;

type NameLookup = rustc_hash::FxHashMap<String, Uuid>;
type ArtistMetadata = rustc_hash::FxHashMap<Uuid, Artist>;
type GraphIndex = rustc_hash::FxHashMap<Uuid, u64>;

struct ArtistPathApp {
    graph_path: &'static Path,
    metadata_path: &'static Path,
}

impl ArtistPathApp {
    fn new() -> Self {
        Self {
            graph_path: Path::new("../data/graph.bin"),
            metadata_path: Path::new("../data/metadata.bin"),
        }
    }
    
    fn load_data(&self) -> (NameLookup, ArtistMetadata, GraphIndex) {
        parse_unified_metadata(self.metadata_path)
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
    let app = ArtistPathApp::new();
    let (name_lookup, artist_metadata, graph_index) = app.load_data();
    
    let search_request = match create_search_request(search_args, &name_lookup, &artist_metadata) {
        Ok(request) => request,
        Err(error_message) => {
            eprintln!("❌ Error: {}", error_message);
            std::process::exit(1);
        }
    };
    
    display_search_info(&search_request);
    
    let search_result = execute_pathfinding_search(search_request, app.graph_path, &graph_index);
    display_search_results(search_result, &artist_metadata);
}

fn create_search_request(
    args: Args,
    name_lookup: &NameLookup,
    artist_metadata: &ArtistMetadata,
) -> Result<SearchRequest, String> {
    let from_artist_id = find_artist_id(&args.artist1, name_lookup)?;
    let to_artist_id = find_artist_id(&args.artist2, name_lookup)?;
    
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

fn display_search_info(request: &SearchRequest) {
    println!(r#"🎵 Finding path from "{}" to "{}""#, request.from_name, request.to_name);
    
    if request.search_args.weighted {
        println!("⚙️ Using weighted pathfinding (Dijkstra)");
    } else {
        println!("⚙️ Using shortest hop pathfinding (BFS)");
    }
    
    if request.search_args.min_match > 0.0 {
        println!("⚡ Filtering connections with similarity >= {:.2}", request.search_args.min_match);
    }
    
    if request.search_args.top_related != 80 {
        println!("🔝 Using top {} connections per artist", request.search_args.top_related);
    }
    
    println!("🔍 Searching...");
}

fn execute_pathfinding_search(
    request: SearchRequest,
    graph_path: &Path,
    graph_index: &GraphIndex,
) -> SearchResult {
    let (path, visited_count, elapsed_time) = if request.search_args.weighted {
        todo!("Weighted pathfinding not yet implemented")
    } else {
        bfs_find_path(request.from_artist, request.to_artist, graph_path, graph_index, &request.search_args)
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

fn display_search_results(result: SearchResult, artist_metadata: &ArtistMetadata) {
    println!("\n---\n");
    
    match result.path {
        Some(path) => {
            display_successful_path(&path, &result.display_options, artist_metadata);
            display_search_statistics(result.artists_visited, result.search_duration);
        }
        None => {
            println!(r#"❌ No path found between "{}" and "{}""#, result.from_name, result.to_name);
            display_search_statistics(result.artists_visited, result.search_duration);
        }
    }
}

fn display_successful_path(path: &Vec<(Uuid, f32)>, display_options: &Args, artist_metadata: &ArtistMetadata) {
    let step_count = path.len() - 1;
    println!("✅ Found path with {} steps:\n", step_count);
    
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
        );
        
        println!("{}", formatted_line);
    }
}

fn format_path_step(
    step_number: String,
    artist_name: &str,
    artist_url: &str,
    similarity: f32,
    step_index: usize,
    display_options: &Args,
) -> String {
    let mut formatted_line = format!(r#"{:3} "{}""#, step_number, artist_name);
    
    if display_options.show_similarity && step_index > 0 {
        formatted_line.push_str(&format!(" [similarity: {:.3}]", similarity));
    }
    
    if !display_options.hide_urls {
        formatted_line.push_str(&format!(" - {}", artist_url));
    }
    
    formatted_line
}

fn display_search_statistics(artists_visited: usize, search_duration: f64) {
    println!("\n---\n");
    println!(
        "📊 Explored {} artists in {:.3} sec",
        format_number(artists_visited),
        search_duration
    );
}