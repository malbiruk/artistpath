#!/usr/bin/env python3
"""Generate graph embeddings using out-of-core FastRP with chunked processing."""

import gc
import json
import struct
import time
from pathlib import Path

import numpy as np
import psutil
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table
from scipy.sparse import coo_matrix
from sklearn import random_projection
from sklearn.decomposition import PCA
from sklearn.preprocessing import normalize, scale

console = Console()

RANDOM_STATE = 25
np.random.seed(RANDOM_STATE)

# FastRP parameters
FASTRP_DIM = 128
FASTRP_Q = 3
FASTRP_PROJECTION = "sparse"
FASTRP_NORMALIZE = True
MAX_EDGES_PER_NODE = 250


class ChunkedFastRP:
    """Out-of-core FastRP implementation using chunked matrix operations."""

    def __init__(self, dim=FASTRP_DIM, projection_method=FASTRP_PROJECTION):
        self.dim = dim
        self.projection_method = projection_method
        self.transformer = None
        self.node_to_idx = {}
        self.idx_to_node = {}
        self.n_nodes = 0

    def build_graph_index(self, graph_path: Path):
        """First pass: build node index without loading full graph."""
        console.print("[cyan]Building node index...")

        nodes_processed = 0
        with graph_path.open() as f:
            for line in f:
                if not line.strip():
                    continue

                data = json.loads(line)
                artist_id = data["id"]

                # Add source node
                if artist_id not in self.node_to_idx:
                    self.node_to_idx[artist_id] = len(self.node_to_idx)

                # Add target nodes
                for conn_id, _ in data["connections"][:MAX_EDGES_PER_NODE]:
                    if conn_id not in self.node_to_idx:
                        self.node_to_idx[conn_id] = len(self.node_to_idx)

                nodes_processed += 1
                if nodes_processed % 50000 == 0:
                    console.print(
                        f"  Indexed {nodes_processed:,} source nodes, {len(self.node_to_idx):,} total nodes",
                    )

        self.n_nodes = len(self.node_to_idx)
        self.idx_to_node = {idx: node_id for node_id, idx in self.node_to_idx.items()}
        console.print(f"[green]✓ Indexed {self.n_nodes:,} unique nodes")

    def load_graph_chunk(self, graph_path: Path, start_idx: int, chunk_size: int):
        """Load a chunk of the graph as sparse matrix."""
        edges = []
        weights = []
        rows_in_chunk = set()

        nodes_processed = 0
        with graph_path.open() as f:
            # Skip to start position
            for _ in range(start_idx):
                next(f, None)

            # Load chunk
            for line in f:
                if not line.strip():
                    continue

                data = json.loads(line)
                artist_id = data["id"]
                source_idx = self.node_to_idx[artist_id]
                rows_in_chunk.add(source_idx)

                for conn_id, weight in data["connections"][:MAX_EDGES_PER_NODE]:
                    target_idx = self.node_to_idx[conn_id]
                    edges.append((source_idx, target_idx))
                    weights.append(float(weight))

                nodes_processed += 1
                if nodes_processed >= chunk_size:
                    break

        if edges:
            row_indices = [e[0] for e in edges]
            col_indices = [e[1] for e in edges]
            # Create sparse matrix for entire graph dimensions
            a_chunk = coo_matrix(
                (weights, (row_indices, col_indices)),
                shape=(self.n_nodes, self.n_nodes),
            ).tocsr()
            return a_chunk, sorted(rows_in_chunk)

        return None, []

    def initialize_projection(self, sample_matrix):
        """Initialize and fit the random projection transformer."""
        console.print("[cyan]Initializing random projection...")

        if self.projection_method == "gaussian":
            self.transformer = random_projection.GaussianRandomProjection(
                n_components=self.dim,
                random_state=RANDOM_STATE,
            )
        else:
            self.transformer = random_projection.SparseRandomProjection(
                n_components=self.dim,
                random_state=RANDOM_STATE,
            )

        # Fit on sample
        self.transformer.fit(sample_matrix)
        console.print(f"[green]✓ Projection initialized with {self.dim} dimensions")

    def compute_embeddings_chunked(self, graph_path: Path, chunk_size: int = 50000):  # noqa: C901, PLR0912
        """Compute FastRP embeddings using chunked processing."""

        # Memory-mapped array for storing embeddings
        embeddings_file = Path("../data/embeddings_temp.npy")
        u_current = np.memmap(
            embeddings_file,
            dtype="float32",
            mode="w+",
            shape=(self.n_nodes, self.dim),
        )

        # Initialize u_list for storing powers
        u_list = []

        console.print(
            f"\n[bold]Computing FastRP with {self.n_nodes:,} nodes in chunks of {chunk_size:,}[/bold]",
        )

        # Process first power: U = A * R (where R is projection matrix)
        console.print("[cyan]Computing first power (direct projection)...")

        total_chunks = (self.n_nodes // chunk_size) + 1
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Processing chunks...", total=total_chunks)

            for chunk_idx in range(0, self.n_nodes, chunk_size):
                # Load chunk
                a_chunk, row_indices = self.load_graph_chunk(
                    graph_path,
                    chunk_idx // chunk_size,
                    min(chunk_size, self.n_nodes - chunk_idx),
                )

                if a_chunk is None:
                    continue

                # Initialize projection on first chunk
                if self.transformer is None:
                    self.initialize_projection(a_chunk)

                # Project this chunk
                u_chunk = self.transformer.transform(a_chunk)

                # Convert sparse to dense if needed
                if hasattr(u_chunk, "toarray"):
                    u_chunk = u_chunk.toarray()
                elif hasattr(u_chunk, "todense"):
                    u_chunk = np.asarray(u_chunk.todense())

                # Store in memory-mapped array (only for rows in this chunk)
                for row_idx in row_indices:
                    if row_idx < len(u_current):
                        u_current[row_idx] = u_chunk[row_idx]

                progress.update(task, advance=1)

                # Memory management
                del a_chunk, u_chunk
                gc.collect()

                if chunk_idx % (chunk_size * 5) == 0:
                    memory_mb = psutil.Process().memory_info().rss / (1024**2)
                    console.print(f"  Memory: {memory_mb:.0f}MB")

        # Save first power
        u_list.append(np.array(u_current))

        # Compute higher powers using blocked matrix multiplication
        for power in range(2, FASTRP_Q + 1):
            console.print(f"[cyan]Computing power {power}/{FASTRP_Q}...")

            # Create new memmap for next power
            u_next = np.memmap(
                f"../data/embeddings_temp_{power}.npy",
                dtype="float32",
                mode="w+",
                shape=(self.n_nodes, self.dim),
            )

            # Compute A @ U_current in chunks
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("Matrix multiplication...", total=total_chunks)

                for chunk_idx in range(0, self.n_nodes, chunk_size):
                    # Load graph chunk
                    a_chunk, row_indices = self.load_graph_chunk(
                        graph_path,
                        chunk_idx // chunk_size,
                        min(chunk_size, self.n_nodes - chunk_idx),
                    )

                    if a_chunk is None:
                        continue

                    # Multiply: A_chunk x U_current
                    # This computes only the rows we need
                    result = a_chunk @ u_current

                    # Store result
                    for row_idx in row_indices:
                        if row_idx < len(u_next):
                            u_next[row_idx] = result[row_idx]

                    progress.update(task, advance=1)

                    # Memory management
                    del a_chunk, result
                    gc.collect()

            # Save this power
            u_list.append(np.array(u_next))
            u_current = u_next

        # Merge embeddings
        console.print("[cyan]Merging embeddings from different powers...")
        return self.merge_embeddings(u_list)

    def merge_embeddings(self, u_list):
        """Merge embeddings from different matrix powers."""
        # Apply normalization if requested
        if FASTRP_NORMALIZE:
            u_list = [normalize(U, norm="l2", axis=1) for U in u_list]

        # Equal weighted combination
        weights = [1.0] * len(u_list)
        u_final = np.zeros_like(u_list[0])

        for u, weight in zip(u_list, weights):
            u_final += u * weight

        # Scale final embeddings
        return scale(u_final)


def apply_pacmap_2d(embeddings_128d):
    """Apply PCA then PaCMAP to reduce embeddings to 2D."""

    # First apply PCA to reduce dimensionality for PaCMAP memory efficiency
    console.print("[cyan]Applying PCA preprocessing...")

    # Find optimal PCA dimensions (capture 90% variance, starting from 28D)
    pca_test = PCA(random_state=RANDOM_STATE)
    pca_test.fit(embeddings_128d)

    cumsum_var = pca_test.explained_variance_ratio_.cumsum()
    variance_threshold = 0.90
    optimal_dims = (cumsum_var >= variance_threshold).argmax() + 1
    optimal_dims = min(max(optimal_dims, 28), 64)

    console.print(
        f"[cyan]PCA: Reducing 128D → {optimal_dims}D (captures {cumsum_var[optimal_dims - 1]:.1%} variance)",
    )

    # Apply PCA with optimal dimensions
    pca = PCA(n_components=optimal_dims, random_state=RANDOM_STATE)
    embeddings_pca = pca.fit_transform(embeddings_128d)

    console.print(f"[green]✓ PCA completed: {embeddings_pca.shape}")

    # Then apply PaCMAP (more memory efficient than UMAP)
    console.print("[cyan]Applying PaCMAP for 2D visualization...")

    import pacmap

    # PaCMAP with memory-efficient settings
    reducer = pacmap.PaCMAP(
        n_components=2,
        # n_neighbors=10,      # Lower than UMAP default (15)
        # MN_ratio=0.5,        # Controls global vs local structure balance
        # FP_ratio=2.0,        # Further pair ratio
        random_state=RANDOM_STATE,
        verbose=True,
    )

    embeddings_2d = reducer.fit_transform(embeddings_pca)
    console.print(f"[green]✓ PaCMAP completed: {embeddings_2d.shape}")
    return embeddings_2d


def save_embeddings(
    embeddings_128d,
    embeddings_2d,
    node_names,
    output_dir: Path,
):
    """Save both 128D and 2D embeddings."""
    output_dir.mkdir(exist_ok=True)

    # Save 128D embeddings (just UUIDs + embeddings)
    embeddings_128d_path = output_dir / "embeddings_128d_fastrp_chunked.npz"
    np.savez_compressed(
        embeddings_128d_path,
        embeddings=embeddings_128d,
        node_ids=node_names,  # More accurate name
    )
    console.print(f"[green]✓ Saved 128D embeddings: {embeddings_128d_path}")

    # Save 2D embeddings (just UUIDs + coordinates)
    embeddings_2d_path = output_dir / "embeddings_2d_fastrp_chunked.ndjson"
    with embeddings_2d_path.open("w") as f:
        for i, node_id in enumerate(node_names):
            entry = {
                "id": node_id,
                "x": float(embeddings_2d[i, 0]),
                "y": float(embeddings_2d[i, 1]),
            }
            f.write(json.dumps(entry) + "\n")

    # Binary format
    binary_path = embeddings_2d_path.with_suffix(".bin")
    with binary_path.open("wb") as f:
        f.write(struct.pack("<I", len(node_names)))
        for i, node_id in enumerate(node_names):
            from uuid import UUID

            uuid_bytes = UUID(node_id).bytes
            f.write(uuid_bytes)
            f.write(struct.pack("<ff", embeddings_2d[i, 0], embeddings_2d[i, 1]))

    console.print("[green]✓ Saved 2D embeddings:")
    console.print(f"  NDJSON: {embeddings_2d_path}")
    console.print(f"  Binary: {binary_path}")


def main():
    """Main chunked FastRP pipeline."""

    data_dir = Path("../data")
    graph_path = data_dir / "graph.ndjson"

    # Memory check
    total_ram_gb = psutil.virtual_memory().total / (1024**3)
    available_ram_gb = psutil.virtual_memory().available / (1024**3)

    # Auto-configure chunk size based on RAM
    memory_threshold1 = 8
    memory_threshold2 = 16
    if available_ram_gb < memory_threshold1:
        chunk_size = 30000
    elif available_ram_gb < memory_threshold2:
        chunk_size = 50000
    else:
        chunk_size = 80000

    console.print(
        Panel.fit(
            f"[bold cyan]Chunked FastRP + PaCMAP Generator[/bold cyan]\n\n"
            f"System RAM: {total_ram_gb:.1f} GB (Available: {available_ram_gb:.1f} GB)\n"
            f"Processing: Entire graph in chunks of {chunk_size:,}\n"
            f"FastRP: {FASTRP_DIM}D, q={FASTRP_Q}, {FASTRP_PROJECTION} projection\n"
            f"Method: Out-of-core with memory mapping",
            padding=1,
        ),
    )

    # Initialize FastRP
    fastrp = ChunkedFastRP(dim=FASTRP_DIM, projection_method=FASTRP_PROJECTION)

    # Build node index
    console.print("\n[bold]1. Building Node Index[/bold]")
    start_time = time.time()
    fastrp.build_graph_index(graph_path)

    # Compute embeddings using chunked processing
    console.print("\n[bold]2. Computing FastRP Embeddings (Chunked)[/bold]")
    embeddings_128d = fastrp.compute_embeddings_chunked(graph_path, chunk_size=chunk_size)

    # Get node names
    node_names = [fastrp.idx_to_node[i] for i in range(fastrp.n_nodes)]

    # Apply UMAP
    console.print("\n[bold]3. Applying UMAP Reduction[/bold]")
    embeddings_2d = apply_pacmap_2d(embeddings_128d)

    # Keep PaCMAP's raw output (no normalization to preserve coordinate distribution)

    # Save results
    console.print("\n[bold]4. Saving Results[/bold]")
    save_embeddings(embeddings_128d, embeddings_2d, node_names, data_dir)

    # Clean up temp files
    console.print("[cyan]Cleaning up temporary files...")
    for temp_file in Path("../data").glob("embeddings_temp*.npy"):
        temp_file.unlink()

    # Stats
    stats_table = Table(title="Results")
    stats_table.add_column("Metric", style="cyan")
    stats_table.add_column("Value", style="green")

    stats_table.add_row("Nodes processed", f"{fastrp.n_nodes:,}")
    stats_table.add_row("Total time", f"{time.time() - start_time:.1f}s")
    stats_table.add_row("Peak memory", f"{psutil.Process().memory_info().rss / (1024**2):.0f} MB")

    console.print("\n")
    console.print(stats_table)
    console.print(Panel.fit("[bold green]✨ Chunked embedding complete!", title="Success"))


if __name__ == "__main__":
    main()
