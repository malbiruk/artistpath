#!/usr/bin/env python3
"""Create graph where each node only has incoming edges (who points TO them)."""

import json
import struct
from collections import defaultdict
from pathlib import Path
from uuid import UUID

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

console = Console()


def create_incoming_only_graph() -> (Path, Path):
    """Create a graph where each node only has its incoming edges.

    Memory-efficient two-pass approach:
    1. Count incoming edges per node
    2. Write files directly without storing all edges in memory
    """

    console.print("[bold cyan]Creating Incoming-Only Graph (Memory Efficient)[/bold cyan]")
    console.print("Pass 1: Count incoming edges per node")
    console.print("Pass 2: Write output files directly")

    input_path = Path("../../data/graph.bin")

    # Pass 1: Count incoming edges for each node
    console.print("\n[cyan]Pass 1: Counting incoming edges...")
    incoming_counts = defaultdict(int)
    nodes_processed = 0
    total_edges = 0

    with input_path.open("rb") as f:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Counting...", total=None)

            while True:
                uuid_bytes = f.read(16)
                if not uuid_bytes or len(uuid_bytes) < 16:
                    break

                source_id = str(UUID(bytes=uuid_bytes))

                conn_count_bytes = f.read(4)
                if not conn_count_bytes:
                    break
                num_connections = struct.unpack("<I", conn_count_bytes)[0]

                # Count incoming edges for each target
                for _ in range(num_connections):
                    neighbor_uuid_bytes = f.read(16)
                    weight_bytes = f.read(4)
                    if len(neighbor_uuid_bytes) < 16 or len(weight_bytes) < 4:
                        break

                    target_id = str(UUID(bytes=neighbor_uuid_bytes))
                    incoming_counts[target_id] += 1
                    total_edges += 1

                nodes_processed += 1
                if nodes_processed % 50000 == 0:
                    progress.update(task, description=f"Counted {nodes_processed:,} nodes...")
                    progress.advance(task)

    console.print("[green]✓ Pass 1 complete:[/green]")
    console.print(f"  Nodes with incoming edges: {len(incoming_counts):,}")
    console.print(f"  Total incoming edges: {total_edges:,}")
    console.print(f"  Average per node: {total_edges / len(incoming_counts):.1f}")

    # Analyze distribution
    in_degrees = list(incoming_counts.values())
    import numpy as np

    console.print(
        f"  In-degree stats: mean={np.mean(in_degrees):.1f}, max={max(in_degrees):,}, std={np.std(in_degrees):.1f}",
    )

    # Pass 2: Stream through again and collect edges for each node
    console.print("\n[cyan]Pass 2: Creating output files...")

    output_ndjson = Path(__file__).parent / "../data/graph_incoming_only.ndjson"
    output_binary = Path(__file__).parent / "../data/graph_incoming_only.bin"

    # Process in chunks to manage memory
    chunk_size = 10000  # Process 10k target nodes at a time
    all_targets = list(incoming_counts.keys())

    with output_ndjson.open("w") as f_json, output_binary.open("wb") as f_bin:
        for chunk_start in range(0, len(all_targets), chunk_size):
            chunk_targets = set(all_targets[chunk_start : chunk_start + chunk_size])
            chunk_edges = defaultdict(list)

            console.print(
                f"  Processing chunk {chunk_start // chunk_size + 1}/{(len(all_targets) - 1) // chunk_size + 1}",
            )

            # Scan entire graph for edges to this chunk's targets
            with input_path.open("rb") as f_read:
                while True:
                    uuid_bytes = f_read.read(16)
                    if not uuid_bytes or len(uuid_bytes) < 16:
                        break

                    source_id = str(UUID(bytes=uuid_bytes))

                    conn_count_bytes = f_read.read(4)
                    if not conn_count_bytes:
                        break
                    num_connections = struct.unpack("<I", conn_count_bytes)[0]

                    for _ in range(num_connections):
                        neighbor_uuid_bytes = f_read.read(16)
                        weight_bytes = f_read.read(4)
                        if len(neighbor_uuid_bytes) < 16 or len(weight_bytes) < 4:
                            break

                        target_id = str(UUID(bytes=neighbor_uuid_bytes))
                        weight = struct.unpack("<f", weight_bytes)[0]

                        # Only collect edges for targets in current chunk
                        if target_id in chunk_targets:
                            chunk_edges[target_id].append((source_id, weight))

            # Write chunk to files
            for target_id in sorted(chunk_targets):
                edge_list = chunk_edges.get(target_id, [])

                # Sort by weight and limit
                edge_list.sort(key=lambda x: x[1], reverse=True)
                limited_edges = edge_list[:250]

                if limited_edges:  # Only write if node has edges
                    # Write NDJSON
                    connections = [[source_id, weight] for source_id, weight in limited_edges]
                    entry = {"id": target_id, "connections": connections}
                    f_json.write(json.dumps(entry) + "\n")

                    # Write binary
                    f_bin.write(UUID(target_id).bytes)
                    f_bin.write(struct.pack("<I", len(limited_edges)))
                    for source_id, weight in limited_edges:
                        f_bin.write(UUID(source_id).bytes)
                        f_bin.write(struct.pack("<f", weight))

            # Clear chunk memory
            del chunk_edges

    console.print("[green]✓ Created incoming-only graph files:")
    console.print(f"  NDJSON: {output_ndjson}")
    console.print(f"  Binary: {output_binary}")
    console.print(
        f"\n[yellow]Memory usage: ~{chunk_size * 250 * 40 / 1024**2:.0f}MB per chunk (vs {total_edges * 40 / 1024**3:.1f}GB naive)",
    )

    return output_ndjson, output_binary


if __name__ == "__main__":
    create_incoming_only_graph()
