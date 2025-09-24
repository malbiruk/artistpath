#!/usr/bin/env python3
"""Calculate comprehensive graph metrics using streaming with reservoir sampling for distributions."""

import gc
import gzip
import json
import pickle
import random
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import psutil
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from scipy import stats

console = Console()

MAX_EDGES_PER_NODE = 250
RESERVOIR_SIZE = 100000  # Max samples to keep in memory


class ReservoirSampler:
    """Reservoir sampling for memory-bounded distribution collection."""

    def __init__(self, size: int = RESERVOIR_SIZE) -> None:
        self.size = size
        self.reservoir = []
        self.n = 0

    def add(self, item: object) -> None:
        """Add item using reservoir sampling algorithm."""
        self.n += 1
        if len(self.reservoir) < self.size:
            self.reservoir.append(item)
        else:
            # Randomly replace with decreasing probability
            j = random.randint(0, self.n - 1)
            if j < self.size:
                self.reservoir[j] = item

    def get_samples(self) -> list[object]:
        """Get collected samples."""
        return self.reservoir


class StreamingGraphMetrics:
    """Memory-efficient streaming graph metrics with reservoir sampling."""

    def __init__(self, graph_path: Path, metadata_path: Path | None) -> None:
        self.graph_path: Path = graph_path
        self.metadata_path: Path | None = metadata_path

        # Reservoir samplers for distributions
        self.out_degree_sampler: ReservoirSampler = ReservoirSampler(RESERVOIR_SIZE)
        self.in_degree_counter: dict[str, int] = defaultdict(
            int,
        )  # Need full counter for accurate top nodes
        self.weight_sampler: ReservoirSampler = ReservoirSampler(
            RESERVOIR_SIZE,
        )  # Same size as other samplers

        # For reciprocity - we'll do a second pass on a sample
        self.edges_for_reciprocity: list[tuple[str, str]] = []  # Sample of edges to check
        self.reciprocity_sample_size: int = min(1000000, RESERVOIR_SIZE * 10)  # 1M edges to check

        # Basic counters
        self.num_edges: int = 0
        self.num_source_nodes: int = 0
        self.nodes_seen: set[str] = set()

        # Top node tracking
        self.top_out_degrees: list[tuple[int, str]] = []  # [(degree, node_id)]
        self.top_k: int = 100

        random.seed(42)

    def process_graph(self) -> None:
        """Single streaming pass through graph."""
        console.print("[cyan]Processing graph with reservoir sampling...")

        nodes_processed = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Streaming through graph...", total=None)

            with self.graph_path.open() as f:
                for line_num, line in enumerate(f):
                    if not line.strip():
                        continue

                    try:
                        data = json.loads(line)
                        artist_id = data["id"]
                        connections = data["connections"][:MAX_EDGES_PER_NODE]

                        # Track source node
                        self.num_source_nodes += 1
                        self.nodes_seen.add(artist_id)

                        # Out-degree sampling
                        out_degree = len(connections)
                        self.out_degree_sampler.add(out_degree)

                        # Track top out-degrees efficiently
                        if len(self.top_out_degrees) < self.top_k:
                            self.top_out_degrees.append((out_degree, artist_id))
                            self.top_out_degrees.sort(reverse=True)
                        elif out_degree > self.top_out_degrees[-1][0]:
                            self.top_out_degrees[-1] = (out_degree, artist_id)
                            self.top_out_degrees.sort(reverse=True)

                        # Process connections
                        for conn_id, weight in connections:
                            self.nodes_seen.add(conn_id)
                            self.num_edges += 1

                            # In-degree tracking (need full counter for top nodes)
                            self.in_degree_counter[conn_id] += 1

                            # Add weight to reservoir sampler (handles sampling internally)
                            self.weight_sampler.add(float(weight))

                            # Sample edges for reciprocity check (collect first, check later)
                            if len(self.edges_for_reciprocity) < self.reciprocity_sample_size:
                                self.edges_for_reciprocity.append((artist_id, conn_id))

                        nodes_processed += 1
                        if nodes_processed % 10000 == 0:
                            progress.update(
                                task,
                                description=f"Processed {nodes_processed:,} nodes, {self.num_edges:,} edges",
                            )
                            if nodes_processed % 50000 == 0:
                                # Periodic memory cleanup
                                gc.collect()

                    except (json.JSONDecodeError, KeyError) as e:
                        console.print(f"[yellow]Warning: Skipping line {line_num}: {e}")

        console.print(
            f"[green]✓ Processed {len(self.nodes_seen):,} nodes, {self.num_edges:,} edges",
        )

    def calculate_reciprocity(self) -> float:
        """Second pass to calculate reciprocity from edge sample."""
        console.print("\n[cyan]Calculating reciprocity from edge sample...")

        if not self.edges_for_reciprocity:
            return 0.0

        # Build set of sampled edges for fast lookup
        sampled_edges = set(self.edges_for_reciprocity)
        edges_to_check = {(b, a) for a, b in self.edges_for_reciprocity}  # Reverse edges

        # Second pass: check which reverse edges exist
        reciprocal_count = 0
        edges_found = set()

        with self.graph_path.open() as f:
            for line in f:
                if not line.strip():
                    continue

                try:
                    data = json.loads(line)
                    artist_id = data["id"]

                    for conn_id, _ in data["connections"][:MAX_EDGES_PER_NODE]:
                        edge = (artist_id, conn_id)
                        if edge in edges_to_check and (conn_id, artist_id) in sampled_edges:
                            reciprocal_count += 1
                            edges_found.add(edge)
                            edges_to_check.remove(edge)  # Don't count twice

                            if not edges_to_check:  # Found all we need
                                break

                except (json.JSONDecodeError, KeyError):
                    continue

                if not edges_to_check:
                    break

        reciprocity = (
            reciprocal_count / len(self.edges_for_reciprocity) if self.edges_for_reciprocity else 0
        )
        console.print(
            f"[green]✓ Found {reciprocal_count:,} reciprocal pairs out of {len(self.edges_for_reciprocity):,} sampled edges",
        )
        return reciprocity

    def calculate_power_law_fits(self) -> dict[str, dict[str, Any]]:
        """Calculate power law fits from sampled distributions."""
        results: dict[str, dict[str, Any]] = {}

        # Out-degree power law from samples
        out_degrees = np.array(self.out_degree_sampler.get_samples())
        if len(out_degrees) > 0:
            unique_out, counts_out = np.unique(out_degrees[out_degrees > 0], return_counts=True)

            if len(unique_out) > 1:
                log_degrees_out = np.log10(unique_out)
                log_counts_out = np.log10(counts_out)
                slope_out, intercept_out, r_value_out, _, _ = stats.linregress(
                    log_degrees_out,
                    log_counts_out,
                )

                # Limit to reasonable size for JSON
                max_points = 1000
                if len(unique_out) > max_points:
                    indices = np.linspace(0, len(unique_out) - 1, max_points, dtype=int)
                    unique_out = unique_out[indices]
                    counts_out = counts_out[indices]

                results["out_degree_fit"] = {
                    "alpha": -slope_out,
                    "intercept": intercept_out,
                    "r_squared": r_value_out**2,
                    "fit_range": [float(unique_out.min()), float(unique_out.max())],
                    "n_points": len(unique_out),
                }

        # In-degree power law - sample from full counter
        in_degrees = list(self.in_degree_counter.values())
        unique_in, counts_in = np.unique(in_degrees, return_counts=True)

        if len(unique_in) > 1:
            positive_mask = unique_in > 0
            if np.any(positive_mask):
                log_degrees_in = np.log10(unique_in[positive_mask])
                log_counts_in = np.log10(counts_in[positive_mask])
                slope_in, intercept_in, r_value_in, _, _ = stats.linregress(
                    log_degrees_in,
                    log_counts_in,
                )

                # Limit size for JSON
                unique_in_pos = unique_in[positive_mask]
                counts_in_pos = counts_in[positive_mask]
                max_points = 1000
                if len(unique_in_pos) > max_points:
                    indices = np.linspace(0, len(unique_in_pos) - 1, max_points, dtype=int)
                    unique_in_pos = unique_in_pos[indices]
                    counts_in_pos = counts_in_pos[indices]

                results["in_degree_fit"] = {
                    "alpha": -slope_in,
                    "intercept": intercept_in,
                    "r_squared": r_value_in**2,
                    "fit_range": [
                        float(unique_in[positive_mask].min()),
                        float(unique_in[positive_mask].max()),
                    ],
                    "n_points": len(unique_in[positive_mask]),
                }

        return results

    def get_basic_stats(self, reciprocity: float) -> dict[str, Any]:
        """Calculate basic statistics from samples."""
        out_degrees = np.array(self.out_degree_sampler.get_samples())
        in_degrees = np.array(list(self.in_degree_counter.values()))
        weights = np.array(self.weight_sampler.get_samples())

        num_nodes = len(self.nodes_seen)

        return {
            "dataset_info": {
                "nodes": num_nodes,
                "edges": self.num_edges,
                "source_nodes": self.num_source_nodes,
                "max_edges_per_node": MAX_EDGES_PER_NODE,
            },
            "basic_metrics": {
                "density": self.num_edges / (num_nodes * (num_nodes - 1)) if num_nodes > 1 else 0,
                "reciprocity": reciprocity,
                "reciprocity_sample_size": len(self.edges_for_reciprocity),
            },
            "degree_stats": {
                "out_degree": {
                    "mean": float(np.mean(out_degrees)),
                    "median": float(np.median(out_degrees)),
                    "std": float(np.std(out_degrees)),
                    "min": int(np.min(out_degrees)),
                    "max": int(np.max(out_degrees)),
                    "q25": float(np.percentile(out_degrees, 25)),
                    "q75": float(np.percentile(out_degrees, 75)),
                    "gini": calculate_gini(out_degrees),
                    "sample_size": len(out_degrees),
                },
                "in_degree": {
                    "mean": float(np.mean(in_degrees)),
                    "median": float(np.median(in_degrees)),
                    "std": float(np.std(in_degrees)),
                    "min": int(np.min(in_degrees)),
                    "max": int(np.max(in_degrees)),
                    "q25": float(np.percentile(in_degrees, 25)),
                    "q75": float(np.percentile(in_degrees, 75)),
                    "gini": calculate_gini(in_degrees),
                    "full_count": len(in_degrees),
                },
            },
            "weight_stats": {
                "mean": float(np.mean(weights)) if len(weights) > 0 else 0,
                "median": float(np.median(weights)) if len(weights) > 0 else 0,
                "std": float(np.std(weights)) if len(weights) > 0 else 0,
                "min": float(np.min(weights)) if len(weights) > 0 else 0,
                "max": float(np.max(weights)) if len(weights) > 0 else 0,
                "q25": float(np.percentile(weights, 25)) if len(weights) > 0 else 0,
                "q75": float(np.percentile(weights, 75)) if len(weights) > 0 else 0,
                "sample_size": len(weights),
            },
        }

    def get_top_nodes(self, n: int = 20) -> dict[str, list[tuple[str, int]]]:
        """Get top nodes by degree with names."""
        # Get top by in-degree
        top_in_items = sorted(self.in_degree_counter.items(), key=lambda x: x[1], reverse=True)[:n]
        top_in_ids = [node_id for node_id, _ in top_in_items]

        # Get top by out-degree
        top_out_ids = [node_id for _, node_id in self.top_out_degrees[:n]]

        # Load names for top nodes if metadata exists
        node_names = {}
        if self.metadata_path and self.metadata_path.exists():
            console.print("\n[cyan]Loading metadata for top nodes...")
            all_top_ids = set(top_in_ids + top_out_ids)

            with self.metadata_path.open() as f:
                for line in f:
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    if data["id"] in all_top_ids:
                        node_names[data["id"]] = data["name"]

        return {
            "top_by_in_degree": [(node_names.get(nid, nid), deg) for nid, deg in top_in_items],
            "top_by_out_degree": [
                (node_names.get(nid, nid), deg) for deg, nid in self.top_out_degrees[:n]
            ],
        }

    def save_distributions(
        self,
        output_dir: Path,
        reciprocity: float,
        output_name: str = "graph",
    ) -> None:
        """Save sampled distribution data for visualization."""
        output_dir.mkdir(exist_ok=True, parents=True)

        # Get sampled out-degrees
        out_degree_samples = self.out_degree_sampler.get_samples()

        # Sample in-degrees if too many
        in_degree_values = list(self.in_degree_counter.values())
        if len(in_degree_values) > RESERVOIR_SIZE:
            in_degree_samples = random.sample(in_degree_values, RESERVOIR_SIZE)
        else:
            in_degree_samples = in_degree_values

        # Get weight samples
        weight_samples = self.weight_sampler.get_samples()

        # Create distributions dictionary
        distributions = {
            "out_degrees": out_degree_samples,
            "in_degrees": in_degree_samples,
            "weights": weight_samples,
            "reciprocity_info": {
                "sampled_edges": len(self.edges_for_reciprocity),
                "reciprocity": reciprocity,
            },
        }

        # Save as compressed pickle
        dist_path = output_dir / f"{output_name}_distributions.pkl.gz"
        with gzip.open(dist_path, "wb") as f:
            pickle.dump(distributions, f, protocol=pickle.HIGHEST_PROTOCOL)
        console.print(f"[green]✓ Saved distributions: {dist_path}")

        # Save representative sample as JSON for Quarto
        max_json_samples = 5000

        def sample_if_needed(data: list[Any], max_size: int) -> list[Any]:
            if len(data) <= max_size:
                return data
            # Random sample for representative subset
            return random.sample(data, max_size)

        json_sample = {
            "out_degrees": sample_if_needed(out_degree_samples, max_json_samples),
            "in_degrees": sample_if_needed(in_degree_samples, max_json_samples),
            "weights": sample_if_needed(weight_samples, max_json_samples),
            "reciprocity_info": distributions["reciprocity_info"],
        }

        json_path = output_dir / f"{output_name}_distributions_sample.json"
        with json_path.open("w") as f:
            json.dump(json_sample, f, indent=2)
        console.print(f"[green]✓ Saved JSON sample: {json_path}")


def calculate_gini(values: npt.NDArray[np.float64]) -> float:
    """Calculate Gini coefficient."""
    sorted_values = np.sort(values)
    n = len(values)
    cumsum = np.cumsum(sorted_values)
    return (2 * np.sum((np.arange(1, n + 1)) * sorted_values)) / (n * cumsum[-1]) - (n + 1) / n


def main() -> None:  # noqa: PLR0915
    """Main entry point for streaming graph metrics calculation."""
    import argparse

    parser = argparse.ArgumentParser(description="Calculate graph metrics")
    parser.add_argument(
        "--input",
        type=str,
        help="Input graph file (default: ../data/graph.ndjson)",
    )
    parser.add_argument(
        "--output-prefix",
        type=str,
        help="Output name prefix (default: graph)",
    )
    args = parser.parse_args()

    # Determine paths based on arguments
    if args.input:
        graph_path = Path(args.input)
        # For subgraph, metadata might not exist
        if "subgraph" in str(graph_path):
            metadata_path = None  # No metadata for subgraph
        else:
            metadata_path = graph_path.parent / "metadata.ndjson"
    else:
        data_dir = Path("../data")
        graph_path = data_dir / "graph.ndjson"
        metadata_path = data_dir / "metadata.ndjson"

    output_dir = Path("metrics")
    output_prefix = args.output_prefix if args.output_prefix else "graph"

    if not graph_path.exists():
        console.print(f"[red]Error: Graph file not found: {graph_path}")
        return

    console.print("[bold cyan]Streaming Graph Metrics Calculator[/bold cyan]")
    console.print(f"Graph: {graph_path}")
    console.print(f"Reservoir size: {RESERVOIR_SIZE:,} samples per distribution")

    start_time = time.time()

    # Initialize metrics calculator
    metrics = StreamingGraphMetrics(graph_path, metadata_path)

    # Process graph in single streaming pass
    metrics.process_graph()

    # Calculate reciprocity (requires second pass)
    reciprocity = metrics.calculate_reciprocity()

    # Calculate derived metrics
    console.print("\n[cyan]Calculating statistics...")
    basic_stats = metrics.get_basic_stats(reciprocity)
    power_law_fits = metrics.calculate_power_law_fits()
    top_nodes = metrics.get_top_nodes()

    # Save distributions
    console.print("\n[cyan]Saving distributions...")
    metrics.save_distributions(output_dir, reciprocity, output_prefix)

    # Combine all metrics
    all_metrics = {
        **basic_stats,
        "power_law_fits": power_law_fits,
        "top_nodes": top_nodes,
        "computation_time": time.time() - start_time,
    }

    # Save metrics
    output_dir.mkdir(exist_ok=True)
    metrics_path = output_dir / f"{output_prefix}_metrics.json"
    with metrics_path.open("w") as f:
        json.dump(all_metrics, f, indent=2)

    # Print summary
    console.print(f"\n[green]✓ Saved metrics: {metrics_path}")
    console.print(f"[cyan]Computation time: {all_metrics['computation_time']:.1f} seconds")

    # Memory usage
    memory_mb = psutil.Process().memory_info().rss / (1024**2)
    console.print(f"[cyan]Peak memory usage: {memory_mb:.0f} MB")

    # Summary table
    from rich.table import Table

    table = Table(title="Graph Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Nodes", f"{basic_stats['dataset_info']['nodes']:,}")
    table.add_row("Edges", f"{basic_stats['dataset_info']['edges']:,}")
    table.add_row("Source nodes", f"{basic_stats['dataset_info']['source_nodes']:,}")
    table.add_row("Density", f"{basic_stats['basic_metrics']['density']:.4%}")
    table.add_row(
        "Reciprocity",
        f"{basic_stats['basic_metrics']['reciprocity']:.1%}",
    )
    table.add_row(
        "Out-degree (mean/med)",
        f"{basic_stats['degree_stats']['out_degree']['mean']:.1f} / "
        f"{basic_stats['degree_stats']['out_degree']['median']:.1f}",
    )
    table.add_row(
        "In-degree (mean/med)",
        f"{basic_stats['degree_stats']['in_degree']['mean']:.1f} / "
        f"{basic_stats['degree_stats']['in_degree']['median']:.1f}",
    )

    console.print("\n")
    console.print(table)


if __name__ == "__main__":
    main()
