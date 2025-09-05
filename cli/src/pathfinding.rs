use std::{fs::File, path::Path};
use memmap2::Mmap;
use artistpath_core::{bfs_find_path, dijkstra_find_path, PathfindingConfig, BiDirectionalGraphs};

use crate::app::GraphIndex;
use crate::search::{SearchRequest, SearchResult};

pub fn execute_pathfinding_search(
    request: SearchRequest,
    graph_path: &Path,
    reverse_graph_path: &Path,
    graph_index: &GraphIndex,
    reverse_graph_index: &GraphIndex,
) -> SearchResult {
    let config = PathfindingConfig::new(
        request.search_args.min_match,
        request.search_args.top_related,
        request.search_args.weighted,
    );
    
    // Open the memory-mapped files
    let graph_file = File::open(graph_path).expect("Failed to open graph file");
    let graph_mmap = unsafe { Mmap::map(&graph_file).expect("Failed to map graph file") };
    
    let reverse_graph_file = File::open(reverse_graph_path).expect("Failed to open reverse graph file");
    let reverse_graph_mmap = unsafe { Mmap::map(&reverse_graph_file).expect("Failed to map reverse graph file") };
    
    // Create BiDirectionalGraphs struct for cleaner API
    let graphs = BiDirectionalGraphs {
        forward: (&graph_mmap, graph_index),
        reverse: (&reverse_graph_mmap, reverse_graph_index),
    };
    
    let (path, visited_count, elapsed_time) = if request.search_args.weighted {
        dijkstra_find_path(
            request.from_artist,
            request.to_artist,
            graphs.forward.0,
            graphs.forward.1,
            graphs.reverse.0,
            graphs.reverse.1,
            &config,
        )
    } else {
        bfs_find_path(
            request.from_artist,
            request.to_artist,
            graphs.forward.0,
            graphs.forward.1,
            graphs.reverse.0,
            graphs.reverse.1,
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