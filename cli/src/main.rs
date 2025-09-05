mod app;
mod args;
mod colors;
mod display;
mod download;
mod json_output;
mod pathfinding;
mod search;
mod utils;

use app::ArtistPathApp;
use args::Args;
use clap::Parser;
use colors::ColorScheme;
use display::{display_search_info, display_search_results};
use json_output::{create_json_output, print_json_output};
use pathfinding::execute_pathfinding_search;
use search::create_search_request;

fn main() {
    let search_args = Args::parse();
    let json_mode = search_args.json;
    let data_path = search_args.data_path.clone();
    let colors = ColorScheme::new(!search_args.no_color);

    // Initialize application
    let app = match ArtistPathApp::new(data_path) {
        Ok(app) => app,
        Err(e) => {
            eprintln!("Failed to initialize: {}", e);
            std::process::exit(1);
        }
    };

    // Load data
    let (name_lookup, artist_metadata, graph_index, reverse_graph_index) = app.load_data();

    // Create search request
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

    // Display search info if verbose
    if search_request.search_args.verbose && !search_request.search_args.json {
        display_search_info(&search_request, &colors);
    }

    // Execute pathfinding search
    let search_result = execute_pathfinding_search(
        search_request,
        &app.graph_path,
        &app.reverse_graph_path,
        &graph_index,
        &reverse_graph_index,
    );

    // Display results
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
