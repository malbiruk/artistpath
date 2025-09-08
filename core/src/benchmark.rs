use crate::parsing::parse_unified_metadata;
use crate::pathfinding::{
    profiled_bfs::{ProfilingMetrics, profiled_bidirectional_bfs, profiled_unidirectional_bfs},
    utils::open_memory_mapped_file,
};
use crate::pathfinding_config::PathfindingConfig;
use rustc_hash::FxHashMap;
use std::path::Path;
use uuid::Uuid;

#[derive(Debug, Clone)]
pub struct BenchmarkResult {
    pub algorithm: String,
    pub path_found: bool,
    pub path_length: usize,
    pub nodes_explored: usize,
    pub total_time_ms: u128,
    pub memory_access_time_ms: u128,
    pub queue_operations_time_ms: u128,
    pub hash_operations_time_ms: u128,
    pub memory_accesses: usize,
    pub queue_operations: usize,
    pub hash_lookups: usize,
    pub cache_state: String,
}

impl From<(&str, &ProfilingMetrics, Option<&Vec<(Uuid, f32)>>, &str)> for BenchmarkResult {
    fn from(
        (algorithm, metrics, path, cache_state): (
            &str,
            &ProfilingMetrics,
            Option<&Vec<(Uuid, f32)>>,
            &str,
        ),
    ) -> Self {
        Self {
            algorithm: algorithm.to_string(),
            path_found: path.is_some(),
            path_length: path.map(|p| p.len()).unwrap_or(0),
            nodes_explored: metrics.nodes_explored_forward + metrics.nodes_explored_reverse,
            total_time_ms: metrics.total_time_ms,
            memory_access_time_ms: metrics.memory_access_time_ms,
            queue_operations_time_ms: metrics.queue_operations_time_ms,
            hash_operations_time_ms: metrics.hash_operations_time_ms,
            memory_accesses: metrics.memory_accesses,
            queue_operations: metrics.queue_operations,
            hash_lookups: metrics.hash_lookups,
            cache_state: cache_state.to_string(),
        }
    }
}

pub struct PathfindingBenchmark {
    forward_graph_data: memmap2::Mmap,
    forward_graph_index: FxHashMap<Uuid, u64>,
    reverse_graph_data: memmap2::Mmap,
    reverse_graph_index: FxHashMap<Uuid, u64>,
    config: PathfindingConfig,
}

impl PathfindingBenchmark {
    pub fn new(
        forward_graph_path: &Path,
        reverse_graph_path: &Path,
        metadata_path: &Path,
    ) -> Result<Self, Box<dyn std::error::Error>> {
        let forward_graph_data = open_memory_mapped_file(forward_graph_path)?;
        let reverse_graph_data = open_memory_mapped_file(reverse_graph_path)?;

        // Parse unified metadata to get indices
        let (_name_lookup, _artist_metadata, forward_graph_index, reverse_graph_index) =
            parse_unified_metadata(metadata_path);

        let config = PathfindingConfig {
            min_match: 0.0,
            top_related: 50,
            weighted: false,
        };

        Ok(Self {
            forward_graph_data,
            forward_graph_index,
            reverse_graph_data,
            reverse_graph_index,
            config,
        })
    }

    /// Benchmark algorithms accounting for memory cache effects
    /// Runs unidirectional first to warm cache, then bidirectional
    pub fn benchmark_cache_aware(&self, start: Uuid, target: Uuid) -> Vec<BenchmarkResult> {
        let mut results = Vec::new();

        println!("Running unidirectional BFS (forward) first to warm up forward graph cache...");
        let (uni_forward_path, uni_forward_metrics) = profiled_unidirectional_bfs(
            start,
            target,
            &self.forward_graph_data,
            &self.forward_graph_index,
            &self.config,
        );
        results.push(BenchmarkResult::from((
            "Unidirectional BFS (Forward)",
            &uni_forward_metrics,
            uni_forward_path.as_ref(),
            "Cold Cache",
        )));

        println!("Running unidirectional BFS (reverse) to warm up reverse graph cache...");
        let (uni_reverse_path, uni_reverse_metrics) = profiled_unidirectional_bfs(
            target, // Start from target
            start,  // Search for start
            &self.reverse_graph_data,
            &self.reverse_graph_index,
            &self.config,
        );
        results.push(BenchmarkResult::from((
            "Unidirectional BFS (Reverse)",
            &uni_reverse_metrics,
            uni_reverse_path.as_ref(),
            "Cold Cache",
        )));

        println!("Running bidirectional BFS with warmed caches...");
        let (bi_path, bi_metrics) = profiled_bidirectional_bfs(
            start,
            target,
            &self.forward_graph_data,
            &self.forward_graph_index,
            &self.reverse_graph_data,
            &self.reverse_graph_index,
            &self.config,
        );
        results.push(BenchmarkResult::from((
            "Bidirectional BFS",
            &bi_metrics,
            bi_path.as_ref(),
            "Warm Cache",
        )));

        results
    }

    /// Benchmark with bidirectional first (suffers cold cache penalty)
    pub fn benchmark_cold_cache_penalty(&self, start: Uuid, target: Uuid) -> Vec<BenchmarkResult> {
        let mut results = Vec::new();

        println!("Running bidirectional BFS with cold cache (worst case)...");
        let (bi_path, bi_metrics) = profiled_bidirectional_bfs(
            start,
            target,
            &self.forward_graph_data,
            &self.forward_graph_index,
            &self.reverse_graph_data,
            &self.reverse_graph_index,
            &self.config,
        );
        results.push(BenchmarkResult::from((
            "Bidirectional BFS",
            &bi_metrics,
            bi_path.as_ref(),
            "Cold Cache",
        )));

        println!("Running unidirectional BFS with now-warm cache...");
        let (uni_forward_path, uni_forward_metrics) = profiled_unidirectional_bfs(
            start,
            target,
            &self.forward_graph_data,
            &self.forward_graph_index,
            &self.config,
        );
        results.push(BenchmarkResult::from((
            "Unidirectional BFS (Forward)",
            &uni_forward_metrics,
            uni_forward_path.as_ref(),
            "Warm Cache",
        )));

        results
    }

    pub fn analyze_memory_access_patterns(&self, results: &[BenchmarkResult]) {
        println!("\n=== Memory Access Pattern Analysis ===");

        for result in results {
            let total_time = result.total_time_ms as f64;
            let memory_pct = if total_time > 0.0 {
                (result.memory_access_time_ms as f64 / total_time) * 100.0
            } else {
                0.0
            };

            println!("\n{} ({}):", result.algorithm, result.cache_state);
            println!("  Total time: {}ms", result.total_time_ms);
            println!("  Nodes explored: {}", result.nodes_explored);
            println!("  Memory accesses: {}", result.memory_accesses);
            println!(
                "  Memory access time: {}ms ({:.1}%)",
                result.memory_access_time_ms, memory_pct
            );

            if result.memory_accesses > 0 {
                let avg_memory_time =
                    result.memory_access_time_ms as f64 / result.memory_accesses as f64;
                let nodes_per_access = result.nodes_explored as f64 / result.memory_accesses as f64;

                println!("  Avg memory access time: {:.2}ms", avg_memory_time);
                println!(
                    "  Nodes explored per memory access: {:.2}",
                    nodes_per_access
                );

                // Analyze cache behavior
                if avg_memory_time > 1.0 {
                    println!(
                        "  → High memory access latency suggests cache misses or mmap penalties"
                    );
                } else {
                    println!("  → Low memory access latency suggests good cache locality");
                }
            }
        }

        // Compare cache effects
        let cold_results: Vec<_> = results
            .iter()
            .filter(|r| r.cache_state == "Cold Cache")
            .collect();
        let warm_results: Vec<_> = results
            .iter()
            .filter(|r| r.cache_state == "Warm Cache")
            .collect();

        if !cold_results.is_empty() && !warm_results.is_empty() {
            println!("\n=== Cache Effect Analysis ===");
            for cold in &cold_results {
                if let Some(warm) = warm_results.iter().find(|w| w.algorithm == cold.algorithm) {
                    let speedup = cold.total_time_ms as f64 / warm.total_time_ms as f64;
                    let memory_speedup =
                        cold.memory_access_time_ms as f64 / warm.memory_access_time_ms as f64;

                    println!("\n{}: Cache warming effect", cold.algorithm);
                    println!(
                        "  Total time speedup: {:.2}x ({} → {}ms)",
                        speedup, cold.total_time_ms, warm.total_time_ms
                    );
                    println!(
                        "  Memory access speedup: {:.2}x ({} → {}ms)",
                        memory_speedup, cold.memory_access_time_ms, warm.memory_access_time_ms
                    );
                }
            }
        }
    }

    pub fn compare_algorithm_efficiency(&self, results: &[BenchmarkResult]) {
        println!("\n=== Algorithm Efficiency Comparison ===");

        // Group by cache state for fair comparison
        let mut by_cache_state: FxHashMap<String, Vec<&BenchmarkResult>> = FxHashMap::default();
        for result in results {
            by_cache_state
                .entry(result.cache_state.clone())
                .or_default()
                .push(result);
        }

        for (cache_state, results_group) in &by_cache_state {
            println!("\n--- {} Results ---", cache_state);

            // Find the best algorithm for this cache state
            if let Some(fastest) = results_group.iter().min_by_key(|r| r.total_time_ms) {
                println!(
                    "Fastest: {} ({}ms, {} nodes)",
                    fastest.algorithm, fastest.total_time_ms, fastest.nodes_explored
                );

                for result in results_group {
                    if result.algorithm != fastest.algorithm {
                        let slowdown = result.total_time_ms as f64 / fastest.total_time_ms as f64;
                        let node_ratio =
                            result.nodes_explored as f64 / fastest.nodes_explored as f64;

                        println!(
                            "  {} is {:.2}x slower, explored {:.2}x nodes",
                            result.algorithm, slowdown, node_ratio
                        );
                    }
                }
            }
        }
    }

    pub fn get_sample_artist_pairs(&self, count: usize) -> Vec<(Uuid, Uuid)> {
        let artist_ids: Vec<Uuid> = self
            .forward_graph_index
            .keys()
            .take(count * 2)
            .copied()
            .collect();

        let mut pairs = Vec::new();
        for i in (0..artist_ids.len()).step_by(2) {
            if i + 1 < artist_ids.len() {
                pairs.push((artist_ids[i], artist_ids[i + 1]));
            }
        }

        pairs.truncate(count);
        pairs
    }
}

/// Run comprehensive benchmark that accounts for memory mapping cache effects
pub fn run_memory_aware_benchmark(
    forward_graph_path: &Path,
    reverse_graph_path: &Path,
    metadata_path: &Path,
    test_count: usize,
) -> Result<(), Box<dyn std::error::Error>> {
    println!("Initializing memory-aware pathfinding benchmark...");
    let benchmark =
        PathfindingBenchmark::new(forward_graph_path, reverse_graph_path, metadata_path)?;

    let test_pairs = benchmark.get_sample_artist_pairs(test_count);
    println!(
        "Testing {} artist pairs with memory cache analysis...\n",
        test_pairs.len()
    );

    for (i, (start, target)) in test_pairs.iter().enumerate() {
        println!("=== Test Pair {} ===", i + 1);
        println!("Start: {}", start);
        println!("Target: {}", target);

        // Test 1: Cache-aware (unidirectional first to warm cache)
        println!("\n--- Test 1: Cache-Aware Order (Unidirectional first) ---");
        let cache_aware_results = benchmark.benchmark_cache_aware(*start, *target);
        benchmark.analyze_memory_access_patterns(&cache_aware_results);
        benchmark.compare_algorithm_efficiency(&cache_aware_results);

        // Test 2: Cold cache penalty (bidirectional first)
        println!("\n--- Test 2: Cold Cache Penalty (Bidirectional first) ---");
        let cold_cache_results = benchmark.benchmark_cold_cache_penalty(*start, *target);
        benchmark.analyze_memory_access_patterns(&cold_cache_results);

        println!("{}", "=".repeat(60));
    }

    Ok(())
}
