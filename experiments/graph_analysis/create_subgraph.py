#!/usr/bin/env python3
"""Create a representative subgraph for hyperparameter optimization using streaming approach."""

import argparse
import json
import random
import struct
from pathlib import Path
from uuid import UUID

import numpy as np
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table

console = Console()

# Target 20% of nodes for HPO following literature
SUBGRAPH_RATIO = 0.2
DEFAULT_SEED = 456
MAX_EDGES_PER_NODE = 250
MAX_SEED_NODES = 1000  # Start with top 1000 nodes as potential seeds


class StreamingSubgraphSampler:
    """Create representative subgraph using streaming random walks."""

    def __init__(
        self,
        graph_path: Path,
        target_ratio: float = SUBGRAPH_RATIO,
        seed: int | None = None,
        output_suffix: str = "",
    ) -> None:
        self.graph_path = graph_path
        self.target_ratio = target_ratio
        self.seed = seed if seed is not None else DEFAULT_SEED
        self.output_suffix = output_suffix
        self.node_index = {}  # node_id -> file offset for quick lookups
        self.node_degrees = {}  # Only for seed selection
        self.total_nodes = 0
        self.target_nodes = 0
        self.sampled_nodes = set()
        random.seed(self.seed)
        np.random.seed(self.seed)

    def build_index_and_find_seeds(self) -> list[str]:
        """First pass: Build node index and identify high-degree seed nodes."""
        console.print("[cyan]Building index and finding seed nodes...")

        # Track top nodes by degree
        top_nodes = []  # [(degree, node_id)]

        with self.graph_path.open() as f:
            while True:
                # Store position before reading
                offset = f.tell()
                line = f.readline()

                if not line:  # EOF
                    break

                if not line.strip():
                    continue

                try:
                    data = json.loads(line)
                    node_id = data["id"]
                    connections = data["connections"][:MAX_EDGES_PER_NODE]
                    degree = len(connections)

                    # Store file position for this node
                    self.node_index[node_id] = offset

                    # Track high-degree nodes for seeds
                    if len(top_nodes) < MAX_SEED_NODES:
                        top_nodes.append((degree, node_id))
                        top_nodes.sort(reverse=True)
                    elif degree > top_nodes[-1][0]:
                        top_nodes[-1] = (degree, node_id)
                        top_nodes.sort(reverse=True)

                    self.total_nodes += 1

                    if self.total_nodes % 50000 == 0:
                        console.print(f"  Indexed {self.total_nodes:,} nodes...")

                except (json.JSONDecodeError, KeyError) as e:
                    console.print(f"[yellow]Warning: Error parsing line: {e}")

        self.target_nodes = int(self.total_nodes * self.target_ratio)

        console.print(f"[green]✓ Indexed {self.total_nodes:,} nodes")
        console.print(
            f"[yellow]Target subgraph size: {self.target_nodes:,} nodes ({self.target_ratio:.0%})",
        )

        # Select diverse seed nodes from top nodes
        n_seeds = min(500, len(top_nodes))  # Use more seeds for better coverage

        # Take some from very top, some from middle of top nodes
        seeds = []
        if len(top_nodes) > 0:
            # Top 20%
            seeds.extend([node_id for _, node_id in top_nodes[: n_seeds // 5]])
            # Random sample from rest
            remaining = [node_id for _, node_id in top_nodes[n_seeds // 5 :]]
            if remaining:
                seeds.extend(random.sample(remaining, min(len(remaining), n_seeds - len(seeds))))

        avg_degree = np.mean([d for d, _ in top_nodes[: len(seeds)]])
        console.print(f"[cyan]Selected {len(seeds)} seed nodes (avg degree: {avg_degree:.1f})")

        return seeds

    def get_node_connections(self, node_id: str) -> list[tuple[str, float]]:
        """Get connections for a specific node by seeking to its position."""
        if node_id not in self.node_index:
            return []

        offset = self.node_index[node_id]

        with self.graph_path.open() as f:
            f.seek(offset)
            line = f.readline()
            if not line.strip():
                return []

            try:
                data = json.loads(line)
                if data["id"] == node_id:
                    return data["connections"][:MAX_EDGES_PER_NODE]
            except (json.JSONDecodeError, KeyError):
                pass

        return []

    def random_walk_from_seed(
        self,
        seed: str,
        walk_length: int = 20,
        n_walks: int = 100,
    ) -> set[str]:
        """Perform multiple random walks from a seed node."""
        local_sampled = {seed}

        for _ in range(n_walks):
            current = seed

            # Random walk
            for _ in range(walk_length):
                connections = self.get_node_connections(current)
                if not connections:
                    break

                # Choose next node based on weights
                if random.random() < 0.15:  # 15% random restart
                    current = seed
                else:
                    # Weighted random selection
                    weights = [w for _, w in connections]
                    if sum(weights) > 0:
                        probs = np.array(weights) / sum(weights)
                        idx = np.random.choice(len(connections), p=probs)
                    else:
                        idx = random.randint(0, len(connections) - 1)

                    current = connections[idx][0]
                    local_sampled.add(current)

                    # Don't limit per seed - we want full coverage
                    if len(local_sampled) >= self.target_nodes // 20:  # ~5% per seed max
                        break

        return local_sampled

    def sample_nodes_streaming(self, seed_nodes: list[str]) -> set[str]:
        """Perform streaming random walks from seed nodes."""
        console.print("[cyan]Performing random walk sampling...")

        sampled_nodes = set()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Random walks...", total=len(seed_nodes))

            for seed in seed_nodes:
                # Random walk from this seed
                local_sampled = self.random_walk_from_seed(seed)
                sampled_nodes.update(local_sampled)

                progress.advance(task)

                # Stop if we have enough nodes
                if len(sampled_nodes) >= self.target_nodes:
                    break

                # Memory management
                if len(seed_nodes) > 0 and seed_nodes.index(seed) % 50 == 0:
                    console.print(f"  Sampled {len(sampled_nodes):,} nodes so far...")

        # If we don't have enough nodes, do BFS from existing nodes
        if len(sampled_nodes) < self.target_nodes * 0.9:  # Less than 90% of target
            console.print("[yellow]Need more nodes. Using BFS to reach target...")

            # BFS expansion from existing sampled nodes
            frontier = list(sampled_nodes)
            random.shuffle(frontier)

            while len(sampled_nodes) < self.target_nodes and frontier:
                current = frontier.pop(0)
                connections = self.get_node_connections(current)

                for conn_id, _ in connections[:10]:  # Sample up to 10 neighbors
                    if conn_id not in sampled_nodes:
                        sampled_nodes.add(conn_id)
                        frontier.append(conn_id)

                        if len(sampled_nodes) >= self.target_nodes:
                            break

        # Trim to exact target size
        if len(sampled_nodes) > self.target_nodes:
            sampled_nodes = set(list(sampled_nodes)[: self.target_nodes])

        console.print(f"[green]✓ Sampled {len(sampled_nodes):,} nodes")
        return sampled_nodes

    def extract_subgraph_streaming(self, sampled_nodes: set[str]) -> None:  # noqa: PLR0915
        """Extract and save subgraph with only sampled nodes."""
        console.print("[cyan]Extracting and saving subgraph...")

        output_dir = Path(__file__).parent / "../data"
        output_dir.mkdir(exist_ok=True, parents=True)

        # Open output files
        ndjson_path = output_dir / f"subgraph{self.output_suffix}.ndjson"
        bin_path = output_dir / f"subgraph{self.output_suffix}.bin"

        subgraph_size = 0
        total_edges_original = 0
        total_edges_preserved = 0
        degree_sum = 0

        with (
            ndjson_path.open("w") as ndjson_f,
            bin_path.open("wb") as bin_f,
            self.graph_path.open() as f,
        ):
            for line_num, line in enumerate(f):
                if not line.strip():
                    continue

                try:
                    data = json.loads(line)
                    node_id = data["id"]

                    if node_id not in sampled_nodes:
                        continue

                    # Filter connections to only sampled nodes
                    original_connections = data["connections"][:MAX_EDGES_PER_NODE]
                    filtered_connections = [
                        (conn_id, weight)
                        for conn_id, weight in original_connections
                        if conn_id in sampled_nodes
                    ]

                    total_edges_original += len(original_connections)
                    total_edges_preserved += len(filtered_connections)

                    if filtered_connections:  # Only include nodes with connections
                        # Write to NDJSON
                        entry = {"id": node_id, "connections": filtered_connections}
                        ndjson_f.write(json.dumps(entry) + "\n")

                        # Write to binary
                        uuid_bytes = UUID(node_id).bytes
                        bin_f.write(uuid_bytes)
                        bin_f.write(struct.pack("<I", len(filtered_connections)))

                        for conn_id, weight in filtered_connections:
                            conn_uuid_bytes = UUID(conn_id).bytes
                            bin_f.write(conn_uuid_bytes)
                            bin_f.write(struct.pack("<f", float(weight)))

                        subgraph_size += 1
                        degree_sum += len(filtered_connections)

                        if subgraph_size % 10000 == 0:
                            console.print(f"  Written {subgraph_size:,} nodes to subgraph...")

                except (json.JSONDecodeError, KeyError) as e:
                    console.print(f"[yellow]Warning: Skipping line {line_num}: {e}")

        # Calculate statistics
        edge_preservation = (
            total_edges_preserved / total_edges_original if total_edges_original > 0 else 0
        )
        avg_degree = degree_sum / subgraph_size if subgraph_size > 0 else 0

        console.print(f"[green]✓ Saved subgraph with {subgraph_size:,} connected nodes")
        console.print(f"  Edge preservation rate: {edge_preservation:.1%}")
        console.print(f"  Average degree: {avg_degree:.1f}")
        console.print("  Files saved:")
        console.print(f"    - {ndjson_path}")
        console.print(f"    - {bin_path}")

        # Save metadata
        metadata = {
            "original_nodes": self.total_nodes,
            "sampled_nodes": len(sampled_nodes),
            "connected_nodes_in_subgraph": subgraph_size,
            "sampling_ratio": len(sampled_nodes) / self.total_nodes,
            "target_ratio": self.target_ratio,
            "edge_preservation_rate": edge_preservation,
            "average_degree_subgraph": avg_degree,
            "seed": self.seed,
            "method": "streaming_random_walk",
            "max_edges_per_node": MAX_EDGES_PER_NODE,
        }

        metadata_path = output_dir / f"subgraph{self.output_suffix}_metadata.json"
        with metadata_path.open("w") as f:
            json.dump(metadata, f, indent=2)

        console.print(f"  - {metadata_path}")

        # Display summary table
        table = Table(title="Subgraph Statistics")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Original nodes", f"{self.total_nodes:,}")
        table.add_row("Target nodes", f"{self.target_nodes:,}")
        table.add_row("Sampled nodes", f"{len(sampled_nodes):,}")
        table.add_row("Connected nodes", f"{subgraph_size:,}")
        table.add_row("Sampling ratio", f"{len(sampled_nodes) / self.total_nodes:.1%}")
        table.add_row("Edge preservation", f"{edge_preservation:.1%}")
        table.add_row("Avg degree", f"{avg_degree:.1f}")

        console.print("\n")
        console.print(table)


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Create representative subgraph for hyperparameter optimization",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"Random seed for sampling (default: {DEFAULT_SEED})",
    )
    parser.add_argument(
        "--output-suffix",
        type=str,
        default="",
        help="Suffix for output files (e.g., '_seed42' produces 'subgraph_seed42.ndjson')",
    )
    args = parser.parse_args()

    # Paths
    data_dir = Path("../../data")
    graph_path = data_dir / "graph.ndjson"

    if not graph_path.exists():
        console.print(f"[red]Error: Graph not found at {graph_path}")
        return

    console.print("[bold cyan]Streaming Subgraph Creator")
    console.print(f"Random seed: {args.seed}")
    console.print("Following KGTuner methodology: 20% multi-start random walk sampling")
    console.print("[yellow]Memory-efficient: Uses file seeking instead of loading graph")
    console.print("")

    # Create sampler
    sampler = StreamingSubgraphSampler(
        graph_path,
        target_ratio=SUBGRAPH_RATIO,
        seed=args.seed,
        output_suffix=args.output_suffix,
    )

    # Build index and find seed nodes
    seed_nodes = sampler.build_index_and_find_seeds()

    # Sample nodes using streaming random walks
    sampled_nodes = sampler.sample_nodes_streaming(seed_nodes)

    # Extract and save subgraph
    sampler.extract_subgraph_streaming(sampled_nodes)

    console.print("\n[green]✨ Subgraph creation complete!")
    console.print("\n[yellow]Next steps:")
    console.print(
        "1. Run: python calculate_graph_metrics.py --input ../data/subgraph.ndjson --output-prefix subgraph",
    )
    console.print("2. Run: python compare_graph_metrics.py")
    console.print("3. If representative, proceed with experiments on subgraph")


if __name__ == "__main__":
    main()
