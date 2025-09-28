#!/usr/bin/env python3
"""Generate graph embeddings using out-of-core FastRP with chunked processing."""

import argparse
import gc
import json
import struct
import time
from pathlib import Path

import numpy as np
import numpy.typing as npt
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

DEFAULT_SEED = 25

# Default FastRP parameters (overridden by config)
FASTRP_DIM = 128
FASTRP_Q = 3
FASTRP_PROJECTION = "sparse"
FASTRP_NORMALIZE = True
MAX_EDGES_PER_NODE = 250


class ChunkedFastRP:
    """Out-of-core FastRP implementation using chunked matrix operations."""

    def __init__(
        self,
        dim: int = FASTRP_DIM,
        projection_method: str = FASTRP_PROJECTION,
        q: int = FASTRP_Q,
        *,
        normalize: bool = FASTRP_NORMALIZE,
        random_state: int = DEFAULT_SEED,
        weight_transform: str | None = None,
        weight_threshold: float = 0.2,
    ) -> None:
        self.dim: int = dim
        self.projection_method: str = projection_method
        self.q: int = q
        self.normalize: bool = normalize
        self.random_state: int = random_state
        self.weight_transform: str | None = (
            weight_transform  # 'log', 'sqrt', 'square', 'threshold', or None
        )
        self.weight_threshold: float = weight_threshold  # For threshold transform
        self.transformer: random_projection.SparseRandomProjection | None = None
        self.node_to_idx: dict[str, int] = {}
        self.idx_to_node: dict[int, str] = {}
        self.n_nodes = 0

    def build_graph_index(self, graph_path: Path) -> None:
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

    def load_graph_chunk(
        self,
        graph_path: Path,
        start_idx: int,
        chunk_size: int,
    ) -> tuple[coo_matrix | None, list[int]]:
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

                    # Apply weight transformation if specified
                    w = float(weight)
                    if self.weight_transform == "log":
                        # Log transform: log(1 + weight) to handle weights close to 0
                        # This spreads out low values while preserving 0
                        w = np.log1p(w)
                    elif self.weight_transform == "sqrt":
                        # Square root transform: less aggressive than log
                        w = np.sqrt(w)
                    elif self.weight_transform == "square":
                        # Square transform: amplify differences
                        w = w * w
                    elif self.weight_transform == "threshold":
                        # Threshold: zero out weak edges
                        w = w if w >= self.weight_threshold else 0.0
                    weights.append(w)

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

    def initialize_projection(self, sample_matrix: coo_matrix) -> None:
        """Initialize and fit the random projection transformer."""
        console.print("[cyan]Initializing random projection...")

        if self.projection_method == "gaussian":
            self.transformer = random_projection.GaussianRandomProjection(
                n_components=self.dim,
                random_state=self.random_state,
            )
        else:
            self.transformer = random_projection.SparseRandomProjection(
                n_components=self.dim,
                random_state=self.random_state,
            )

        # Fit on sample
        self.transformer.fit(sample_matrix)
        console.print(f"[green]✓ Projection initialized with {self.dim} dimensions")

    def compute_embeddings_chunked(
        self,
        graph_path: Path,
        chunk_size: int = 50000,
    ) -> npt.NDArray[np.float32]:
        """Compute FastRP embeddings using chunked processing."""

        # Memory-mapped array for storing embeddings
        temp_dir = Path(__file__).parent / "results" / "embeddings"
        temp_dir.mkdir(parents=True, exist_ok=True)
        embeddings_file = temp_dir / "embeddings_temp.npy"
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
        for power in range(2, self.q + 1):
            console.print(f"[cyan]Computing power {power}/{self.q}...")

            # Create new memmap for next power
            temp_dir = Path(__file__).parent / "results" / "embeddings"
            u_next = np.memmap(
                temp_dir / f"embeddings_temp_{power}.npy",
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

    def merge_embeddings(self, u_list: list[npt.NDArray[np.float32]]) -> npt.NDArray[np.float32]:
        """Merge embeddings from different matrix powers."""
        # Apply normalization if requested
        if self.normalize:
            u_list = [normalize(U, norm="l2", axis=1) for U in u_list]

        # Equal weighted combination
        weights = [1.0] * len(u_list)
        u_final = np.zeros_like(u_list[0])

        for u, weight in zip(u_list, weights):
            u_final += u * weight

        # Scale final embeddings
        return scale(u_final)


def apply_reduction_2d(
    embeddings_high_d: npt.NDArray[np.float32],
    config: dict,
    random_state: int = DEFAULT_SEED,
) -> npt.NDArray[np.float32]:
    """Apply dimensionality reduction based on config."""

    reduction = config.get("reduction", {})
    method = reduction.get("method", "pacmap")

    if method == "none":
        # No reduction needed - already 2D
        console.print("[cyan]No reduction needed (already 2D)")
        return embeddings_high_d

    # Apply PCA if specified
    embeddings_for_reduction = embeddings_high_d
    pca_dims = reduction.get("pca_dims", "auto_90")

    if pca_dims and pca_dims != "none":
        console.print("[cyan]Applying PCA preprocessing...")

        if isinstance(pca_dims, str) and pca_dims.startswith("auto_"):
            # Auto PCA with variance threshold
            variance_threshold = int(pca_dims.split("_")[1]) / 100.0
            pca_test = PCA(random_state=random_state)
            pca_test.fit(embeddings_high_d)
            cumsum_var = pca_test.explained_variance_ratio_.cumsum()
            optimal_dims = (cumsum_var >= variance_threshold).argmax() + 1
            optimal_dims = min(max(optimal_dims, 10), embeddings_high_d.shape[1] - 1)

            console.print(
                f"[cyan]PCA: Reducing {embeddings_high_d.shape[1]}D → {optimal_dims}D "
                f"(captures {cumsum_var[optimal_dims - 1]:.1%} variance)",
            )
            pca = PCA(n_components=optimal_dims, random_state=random_state)
        else:
            # Fixed PCA dimensions
            pca = PCA(n_components=pca_dims, random_state=random_state)
            console.print(f"[cyan]PCA: Reducing to {pca_dims}D")

        embeddings_for_reduction = pca.fit_transform(embeddings_high_d)
        console.print(f"[green]✓ PCA completed: {embeddings_for_reduction.shape}")

    # Apply final 2D reduction
    if method == "pacmap":
        console.print("[cyan]Applying PaCMAP for 2D visualization...")
        import pacmap

        reducer = pacmap.PaCMAP(
            n_components=2,
            n_neighbors=reduction.get("pacmap_neighbors", 15),
            MN_ratio=reduction.get("pacmap_MN_ratio", 0.5),
            FP_ratio=reduction.get("pacmap_FP_ratio", 2.0),
            random_state=random_state,
            verbose=True,
        )
        embeddings_2d = reducer.fit_transform(embeddings_for_reduction)
        console.print(f"[green]✓ PaCMAP completed: {embeddings_2d.shape}")

    elif method == "umap":
        console.print("[cyan]Applying UMAP for 2D visualization...")
        from umap import UMAP

        reducer = UMAP(
            n_components=2,
            n_neighbors=reduction.get("umap_neighbors", 15),
            min_dist=reduction.get("umap_min_dist", 0.1),
            random_state=random_state,
        )
        embeddings_2d = reducer.fit_transform(embeddings_for_reduction)
        console.print(f"[green]✓ UMAP completed: {embeddings_2d.shape}")

    else:
        raise ValueError(f"Unknown reduction method: {method}")

    return embeddings_2d


def save_embeddings(
    embeddings: npt.NDArray[np.float32],
    node_names: list[str],
    output_dir: Path,
    suffix: str = "fastrp",
    seed: int | None = None,
) -> Path:
    """Save embeddings in binary format to experiments/results/embeddings/."""
    output_dir = (
        Path(__file__).parent / "results" / "embeddings"
    )  # Always save to experiments/results/embeddings/
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save embeddings in binary format (works for any dimensionality)
    seed_suffix = f"_seed{seed}" if seed is not None else ""
    binary_path = output_dir / f"embeddings_{suffix}{seed_suffix}.bin"

    n_embeddings = len(node_names)
    dims = embeddings.shape[1]

    with binary_path.open("wb") as f:
        # Header: number of embeddings
        f.write(struct.pack("<I", n_embeddings))

        # For each embedding: UUID (16 bytes) + embedding vector (dims * 4 bytes)
        for i, node_id in enumerate(node_names):
            from uuid import UUID

            uuid_bytes = UUID(node_id).bytes
            f.write(uuid_bytes)

            # Write the entire embedding vector
            embedding_bytes = embeddings[i].astype(np.float32).tobytes()
            f.write(embedding_bytes)

    size_mb = binary_path.stat().st_size / (1024**2)
    console.print(f"[green]✓ Saved {dims}D embeddings: {binary_path.name} ({size_mb:.1f} MB)")

    return binary_path  # Return the binary embedding path for evaluation


def generate_embedding(
    config_name: str | None = None,
    config_file: str | None = None,
    *,
    verbose: bool = True,
    seed: int = DEFAULT_SEED,
    graph_path: str | None = None,
) -> tuple[Path | None, bool]:
    """Generate embeddings for a specific config.

    Args:
        config_name: Name of config to use from config file
        config_file: Path to config file
        verbose: Whether to print progress
        seed: Random seed for reproducibility
        graph_path: Path to graph file (if None, uses path from config)

    Returns:
        tuple: (output_path, success) where output_path is the generated embedding file
    """
    # Set random seed
    np.random.seed(seed)
    random_state = seed
    # Load config
    if config_file:
        # Check in configs/ subdirectory first
        config_path = Path(__file__).parent / "configs" / config_file
        if not config_path.exists():
            # Try direct path for backward compatibility
            config_path = Path(__file__).parent / config_file
    else:
        config_path = Path(__file__).parent / "configs" / "phase1_fastrp_optimization.json"

    if not config_path.exists():
        if verbose:
            console.print(f"[red]Config file not found: {config_path}")
        return None, False

    with config_path.open() as f:
        all_configs = json.load(f)

    # Select config
    if config_name:
        config = None
        for cfg in all_configs["configs"]:
            if cfg["name"] == config_name:
                config = cfg
                break
        if not config:
            if verbose:
                console.print(f"[red]Config '{config_name}' not found!")
                console.print(f"Available configs: {[c['name'] for c in all_configs['configs']]}")
            return None, False
    else:
        # Use first config as default
        config = all_configs["configs"][0]

    if verbose:
        console.print(f"[bold cyan]Using config: {config['name']}[/bold cyan]")
        console.print(f"Description: {config['description']}")

    # Setup paths - data is one level up from experiments
    data_dir = Path(__file__).parent / "data"  # Always define data_dir
    if graph_path:
        # Use provided graph path
        graph_path = Path(graph_path)
        # Extract data_dir from the provided path
        data_dir = graph_path.parent
    else:
        # Use graph path from config or default to subgraph
        graph_path = data_dir / "subgraph.ndjson"

    # Memory check and chunk size
    total_ram_gb = psutil.virtual_memory().total / (1024**3)
    available_ram_gb = psutil.virtual_memory().available / (1024**3)

    memory_cfg = all_configs.get("memory", {})
    if available_ram_gb < 8:
        chunk_size = memory_cfg.get("chunk_size_8gb", 30000)
    elif available_ram_gb < 16:
        chunk_size = memory_cfg.get("chunk_size_16gb", 50000)
    else:
        chunk_size = memory_cfg.get("chunk_size_32gb", 80000)

    # Get FastRP params from config
    fastrp_cfg = config["fastrp"]
    dim = fastrp_cfg["dim"]
    q = fastrp_cfg["q"]
    projection = fastrp_cfg["projection"]
    normalize = fastrp_cfg["normalize"]

    if verbose:
        console.print(
            Panel.fit(
                f"[bold cyan]Chunked FastRP Pipeline[/bold cyan]\n\n"
                f"Config: {config['name']}\n"
                f"System RAM: {total_ram_gb:.1f} GB (Available: {available_ram_gb:.1f} GB)\n"
                f"Processing: Entire graph in chunks of {chunk_size:,}\n"
                f"FastRP: {dim}D, q={q}, {projection} projection\n"
                f"Method: Out-of-core with memory mapping",
                padding=1,
            ),
        )

    # Get preprocessing params
    preprocessing_cfg = config.get("preprocessing", {})
    weight_transform = preprocessing_cfg.get("weight_transform", None)

    # Initialize FastRP
    fastrp = ChunkedFastRP(
        dim=dim,
        projection_method=projection,
        q=q,
        normalize=normalize,
        random_state=random_state,
        weight_transform=weight_transform,
    )

    # Build node index
    if verbose:
        console.print("\n[bold]1. Building Node Index[/bold]")
    start_time = time.time()
    fastrp.build_graph_index(graph_path)

    # Compute embeddings using chunked processing
    if verbose:
        console.print("\n[bold]2. Computing FastRP Embeddings (Chunked)[/bold]")
    embeddings_high_d = fastrp.compute_embeddings_chunked(graph_path, chunk_size=chunk_size)

    # Get node names
    node_names = [fastrp.idx_to_node[i] for i in range(fastrp.n_nodes)]

    # Check if reduction is needed
    reduction = config.get("reduction", {})
    if reduction.get("method", "none") == "none":
        # No reduction - save FastRP embeddings directly
        if verbose:
            console.print("\n[bold]3. Saving FastRP embeddings (no reduction)[/bold]")
        embeddings_final = embeddings_high_d
    else:
        # Apply dimensionality reduction if specified
        if verbose:
            console.print("\n[bold]3. Applying 2D Reduction[/bold]")
        embeddings_final = apply_reduction_2d(embeddings_high_d, config, random_state)

    # Save results
    if verbose:
        console.print("\n[bold]4. Saving Results[/bold]")
    output_path = save_embeddings(
        embeddings_final,
        node_names,
        data_dir,
        config["output_suffix"],
        seed=random_state,
    )

    # Clean up temp files
    if verbose:
        console.print("[cyan]Cleaning up temporary files...")
    temp_dir = Path(__file__).parent / "results" / "embeddings"
    for temp_file in temp_dir.glob("embeddings_temp*.npy"):
        temp_file.unlink()

    # Stats
    if verbose:
        stats_table = Table(title="Results")
        stats_table.add_column("Metric", style="cyan")
        stats_table.add_column("Value", style="green")

        stats_table.add_row("Nodes processed", f"{fastrp.n_nodes:,}")
        stats_table.add_row("Total time", f"{time.time() - start_time:.1f}s")
        stats_table.add_row(
            "Peak memory",
            f"{psutil.Process().memory_info().rss / (1024**2):.0f} MB",
        )

        console.print("\n")
        console.print(stats_table)
        console.print(Panel.fit("[bold green]✨ Chunked embedding complete!", title="Success"))

    return output_path, True
