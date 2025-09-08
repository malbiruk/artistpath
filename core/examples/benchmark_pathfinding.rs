use artistpath_core::benchmark::run_memory_aware_benchmark;
use std::path::Path;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Update these paths to match your actual data location
    let forward_graph_path = Path::new("../data/graph.bin");
    let reverse_graph_path = Path::new("../data/rev-graph.bin");
    let metadata_path = Path::new("../data/metadata.bin");

    // Check if files exist
    if !forward_graph_path.exists() {
        eprintln!("Error: {} not found", forward_graph_path.display());
        eprintln!(
            "Please update the paths in examples/benchmark_pathfinding.rs to match your data location"
        );
        std::process::exit(1);
    }

    if !reverse_graph_path.exists() {
        eprintln!("Error: {} not found", reverse_graph_path.display());
        std::process::exit(1);
    }

    if !metadata_path.exists() {
        eprintln!("Error: {} not found", metadata_path.display());
        std::process::exit(1);
    }

    println!("🚀 Running memory-aware pathfinding benchmark...");
    println!(
        "This will test the hypothesis that bidirectional search suffers from memory cache effects.\n"
    );

    // Run with 3 test pairs - adjust this number based on how long you want the test to run
    run_memory_aware_benchmark(
        forward_graph_path,
        reverse_graph_path,
        metadata_path,
        3, // Number of artist pairs to test
    )?;

    println!("\n✅ Benchmark completed!");
    println!("\n📊 Key metrics to look for:");
    println!("- If Memory I/O > 50% of total time → Memory mapping is the bottleneck");
    println!("- If 'Cold Cache' is significantly slower → Cache effects are real");
    println!(
        "- If bidirectional explores fewer nodes but takes longer → Algorithm is better but I/O bound"
    );

    Ok(())
}
