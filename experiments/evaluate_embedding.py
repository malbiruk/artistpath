#!/usr/bin/env python3
"""Memory-efficient evaluation of embedding quality using binary files."""

import json
import mmap
import struct
import time
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import numpy as np
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table
from scipy import stats
from sklearn.metrics import normalized_mutual_info_score
from sklearn.neighbors import NearestNeighbors

console = Console()


class MemoryEfficientEvaluator:
    """Memory-efficient evaluation of embeddings against graph structure."""

    def __init__(
        self,
        graph_path: Path,
        embedding_path: Path,
        sample_size: int = 10000,
        chunk_size: int = 1000,
    ) -> None:
        """
        Initialize evaluator.

        Args:
            graph_path: Path to graph.bin
            embedding_path: Path to embeddings_*.bin
            sample_size: Number of nodes to sample for expensive metrics
            chunk_size: Size of chunks for processing
        """
        self.graph_path = graph_path
        self.embedding_path = embedding_path
        self.sample_size = sample_size
        self.chunk_size = chunk_size

        # We'll use memory mapping for embeddings
        self.embedding_mmap = None
        self.embedding_index = {}  # node_id -> file offset
        self.num_embeddings = 0
        self.embedding_dim = 0  # Will be detected from file

        # For graph, we'll stream and sample
        self.sampled_graph = {}  # Only store sampled nodes
        self.sampled_embeddings = {}
        self.node_list = []

    def _read_embedding_header(self) -> int:
        """Read number of embeddings from binary file."""
        with self.embedding_path.open("rb") as f:
            return struct.unpack("<I", f.read(4))[0]

    def build_embedding_index(self) -> None:
        """Build index of node_id -> file offset for fast lookups."""
        console.print(f"[cyan]Building embedding index from {self.embedding_path}...")

        # Detect dimensionality from file size
        file_size = self.embedding_path.stat().st_size
        with self.embedding_path.open("rb") as f:
            self.num_embeddings = struct.unpack("<I", f.read(4))[0]

            # Calculate embedding dimension
            # File size = 4 (header) + num_embeddings * (16 UUID + dim * 4 floats)
            data_size = file_size - 4
            bytes_per_embedding = data_size // self.num_embeddings
            self.embedding_dim = (bytes_per_embedding - 16) // 4

            console.print(f"[cyan]Detected {self.embedding_dim}D embeddings")

            offset = 4  # Start after header
            bytes_per_entry = 16 + self.embedding_dim * 4

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("Indexing embeddings...", total=self.num_embeddings)

                for _ in range(self.num_embeddings):
                    uuid_bytes = f.read(16)
                    node_id = str(UUID(bytes=uuid_bytes))
                    self.embedding_index[node_id] = offset
                    offset += bytes_per_entry
                    f.seek(offset)  # Skip the embedding vector
                    progress.advance(task)

        console.print(
            f"[green]✓ Indexed {len(self.embedding_index):,} {self.embedding_dim}D embeddings",
        )

    def get_embedding(self, node_id: str) -> np.ndarray | None:
        """Get embedding for a specific node using memory mapping."""
        if node_id not in self.embedding_index:
            return None

        if self.embedding_mmap is None:
            # Open memory map on first use
            f = self.embedding_path.open("rb")
            self.embedding_mmap = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)

        offset = self.embedding_index[node_id]
        self.embedding_mmap.seek(offset + 16)  # Skip UUID

        # Read the entire embedding vector
        embedding_bytes = self.embedding_mmap.read(self.embedding_dim * 4)
        return np.frombuffer(embedding_bytes, dtype=np.float32)

    def stream_graph_nodes(self, max_edges: int = 250) -> Iterator[tuple[str, list]]:
        """Stream graph nodes from binary file without loading all to memory."""
        with self.graph_path.open("rb") as f:
            # graph.bin has no header - it starts directly with entries
            while True:
                # Try to read node ID (16 bytes)
                uuid_bytes = f.read(16)
                if not uuid_bytes or len(uuid_bytes) < 16:
                    break  # EOF

                node_id = str(UUID(bytes=uuid_bytes))

                # Read number of connections (4 bytes)
                conn_count_bytes = f.read(4)
                if not conn_count_bytes or len(conn_count_bytes) < 4:
                    break
                num_connections = struct.unpack("<I", conn_count_bytes)[0]

                # Read connections (limit to max_edges)
                connections = []
                for _ in range(min(num_connections, max_edges)):
                    neighbor_uuid_bytes = f.read(16)
                    weight_bytes = f.read(4)
                    if len(neighbor_uuid_bytes) < 16 or len(weight_bytes) < 4:
                        break
                    neighbor_uuid = str(UUID(bytes=neighbor_uuid_bytes))
                    weight = struct.unpack("<f", weight_bytes)[0]
                    connections.append((neighbor_uuid, weight))

                # Skip remaining connections if any
                if num_connections > max_edges:
                    f.seek((num_connections - max_edges) * 20, 1)  # 16 + 4 bytes per connection

                yield node_id, connections

    def sample_nodes(self) -> None:
        """Sample nodes that exist in both graph and embeddings."""
        console.print("[cyan]Sampling nodes...")

        # First pass: count common nodes and collect candidates
        candidates = []

        for node_id, connections in self.stream_graph_nodes():
            if node_id in self.embedding_index:
                candidates.append((node_id, connections))
                if len(candidates) >= self.sample_size * 2:  # Get 2x for better sampling
                    break

        # Sample from candidates
        import random

        random.seed(42)

        if len(candidates) > self.sample_size:
            sampled = random.sample(candidates, self.sample_size)
        else:
            sampled = candidates

        # Build sampled graph and embeddings
        for node_id, connections in sampled:
            self.sampled_graph[node_id] = connections
            embedding = self.get_embedding(node_id)
            if embedding:
                self.sampled_embeddings[node_id] = embedding
                self.node_list.append(node_id)

        console.print(
            f"[green]✓ Sampled {len(self.node_list):,} nodes with both graph and embedding data",
        )

    def compute_graph_distances_sparse(self, subset_size: int = 2000) -> tuple[np.ndarray, list]:
        """Compute graph distances on a smaller subset to save memory."""
        # Further subsample for distance computation
        subset_size = min(subset_size, len(self.node_list))
        import random

        random.seed(42)
        subset_nodes = random.sample(self.node_list, subset_size)

        n = len(subset_nodes)
        distances = np.full((n, n), np.inf, dtype=np.float32)  # Use float32 to save memory
        np.fill_diagonal(distances, 0)

        node_to_idx = {node: i for i, node in enumerate(subset_nodes)}

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Computing sparse graph distances...", total=n)

            for node_id in subset_nodes:
                i = node_to_idx[node_id]
                for neighbor_id, weight in self.sampled_graph.get(node_id, []):
                    if neighbor_id in node_to_idx:
                        j = node_to_idx[neighbor_id]
                        distances[i, j] = 1.0 / (weight + 1e-6)
                progress.advance(task)

        return distances, subset_nodes

    def compute_embedding_distances_sparse(self, subset_nodes: list) -> np.ndarray:
        """Compute embedding distances for subset."""
        coords = np.array(
            [self.sampled_embeddings[node_id] for node_id in subset_nodes],
            dtype=np.float32,
        )
        # Compute distances in chunks to save memory
        n = len(coords)
        distances = np.zeros((n, n), dtype=np.float32)

        chunk_size = 100
        for i in range(0, n, chunk_size):
            end_i = min(i + chunk_size, n)
            for j in range(0, n, chunk_size):
                end_j = min(j + chunk_size, n)
                # Compute chunk
                chunk = np.sqrt(
                    ((coords[i:end_i, np.newaxis, :] - coords[np.newaxis, j:end_j, :]) ** 2).sum(
                        axis=2,
                    ),
                )
                distances[i:end_i, j:end_j] = chunk

        return distances

    def evaluate_neighborhood_preservation(self, k_values: list[int] | None = None) -> dict:
        """Evaluate neighborhood preservation with memory efficiency."""
        if k_values is None:
            k_values = [5, 10, 20, 50]
        console.print("[cyan]Evaluating neighborhood preservation...")

        # Work with larger batches for better statistics
        batch_size = min(5000, len(self.node_list))
        import random

        random.seed(42)
        batch_nodes = random.sample(self.node_list, batch_size)

        # Get graph neighbors for batch
        graph_neighbors = {}
        for node_id in batch_nodes:
            neighbors = sorted(self.sampled_graph[node_id], key=lambda x: x[1], reverse=True)
            graph_neighbors[node_id] = [n[0] for n in neighbors if n[0] in self.sampled_embeddings]

        # Get embedding coordinates for batch
        coords = np.array(
            [self.sampled_embeddings[node_id] for node_id in batch_nodes],
            dtype=np.float32,
        )

        results = {}
        for k in k_values:
            if k >= len(batch_nodes):
                continue

            # Find k-NN in embedding space
            nbrs = NearestNeighbors(n_neighbors=min(k + 1, len(batch_nodes)), metric="euclidean")
            nbrs.fit(coords)
            _, indices = nbrs.kneighbors(coords)

            # Calculate preservation
            preservations = []
            for i, node_id in enumerate(batch_nodes):
                graph_knn = set(graph_neighbors[node_id][:k])
                embedding_knn = {
                    batch_nodes[j] for j in indices[i][1 : k + 1] if j < len(batch_nodes)
                }

                if len(graph_knn) > 0:
                    preservation = len(graph_knn & embedding_knn) / len(graph_knn)
                    preservations.append(preservation)

            if preservations:
                results[k] = {
                    "mean": np.mean(preservations),
                    "std": np.std(preservations),
                    "median": np.median(preservations),
                }

        return results

    def evaluate_distance_correlation(self) -> dict:
        """Evaluate distance correlation with sparse sampling."""
        console.print("[cyan]Computing distance correlation...")

        # Use larger subset for distance correlation
        graph_dist, subset_nodes = self.compute_graph_distances_sparse(subset_size=2000)
        embed_dist = self.compute_embedding_distances_sparse(subset_nodes)

        # Extract upper triangle
        graph_dists = []
        embed_dists = []
        for i in range(len(subset_nodes)):
            for j in range(i + 1, len(subset_nodes)):
                g_dist = graph_dist[i, j]
                if g_dist < np.inf:
                    graph_dists.append(g_dist)
                    embed_dists.append(embed_dist[i, j])

        if len(graph_dists) > 0:
            spearman_r, spearman_p = stats.spearmanr(graph_dists, embed_dists)
            pearson_r, pearson_p = stats.pearsonr(graph_dists, embed_dists)

            # Calculate R-squared values
            spearman_r2 = spearman_r**2 if not np.isnan(spearman_r) else np.nan
            pearson_r2 = pearson_r**2 if not np.isnan(pearson_r) else np.nan

            return {
                "spearman_r": float(spearman_r),
                "spearman_r2": float(spearman_r2),
                "spearman_p": float(spearman_p),
                "pearson_r": float(pearson_r),
                "pearson_r2": float(pearson_r2),
                "pearson_p": float(pearson_p),
                "n_pairs": len(graph_dists),
            }
        return {
            "spearman_r": np.nan,
            "spearman_r2": np.nan,
            "spearman_p": np.nan,
            "pearson_r": np.nan,
            "pearson_r2": np.nan,
            "pearson_p": np.nan,
            "n_pairs": 0,
        }

    def evaluate_community_preservation(self) -> dict:
        """Evaluate community preservation with memory constraints."""
        console.print("[cyan]Evaluating community preservation...")

        try:
            from sklearn.cluster import KMeans
        except ImportError:
            console.print("[yellow]Skipping community evaluation (sklearn required)")
            return {}

        # Use larger sample for clustering
        sample_size = min(10000, len(self.node_list))
        import random

        random.seed(42)
        sample_nodes = random.sample(self.node_list, sample_size)

        # Build small adjacency matrix
        n = len(sample_nodes)
        adjacency = np.zeros((n, n), dtype=np.float32)
        node_to_idx = {node: i for i, node in enumerate(sample_nodes)}

        for node_id in sample_nodes:
            i = node_to_idx[node_id]
            for neighbor_id, weight in self.sampled_graph.get(node_id, []):
                if neighbor_id in node_to_idx:
                    j = node_to_idx[neighbor_id]
                    adjacency[i, j] = weight

        # Make symmetric
        adjacency = (adjacency + adjacency.T) / 2

        # Determine optimal number of clusters (between 5 and 20)
        n_clusters = min(20, max(5, n // 500))

        # Try better clustering via spectral clustering
        if n_clusters > 1 and adjacency.sum() > 0:
            try:
                # Use spectral clustering on graph
                from sklearn.cluster import SpectralClustering

                graph_clustering = SpectralClustering(
                    n_clusters=n_clusters,
                    affinity="precomputed",
                    random_state=42,
                    n_init=5,
                    assign_labels="kmeans",
                )
                # Add small constant for numerical stability
                adjacency_stable = adjacency + 1e-8 * np.eye(n)
                graph_labels = graph_clustering.fit_predict(adjacency_stable)
            except Exception as e:
                console.print(f"[yellow]Spectral clustering failed: {e}, using degree-based")
                # Fallback to degree-based clustering
                degrees = adjacency.sum(axis=1)
                graph_labels = np.digitize(
                    degrees,
                    np.percentile(degrees, np.linspace(0, 100, n_clusters + 1)[1:-1]),
                )
        else:
            graph_labels = np.zeros(n, dtype=int)

        # Cluster in embedding space
        coords = np.array(
            [self.sampled_embeddings[node_id] for node_id in sample_nodes],
            dtype=np.float32,
        )
        embed_clustering = KMeans(n_clusters=n_clusters, random_state=42, n_init=10).fit(coords)
        embed_labels = embed_clustering.labels_

        # Compare clusterings
        nmi = normalized_mutual_info_score(graph_labels, embed_labels)

        # Also compute Adjusted Rand Index for comparison
        from sklearn.metrics import adjusted_rand_score

        ari = adjusted_rand_score(graph_labels, embed_labels)

        return {"nmi": float(nmi), "ari": float(ari), "n_clusters": n_clusters, "n_nodes": n}

    def cleanup(self) -> None:
        """Clean up memory-mapped resources."""
        if self.embedding_mmap:
            self.embedding_mmap.close()

    def run_evaluation(self) -> dict:
        """Run complete evaluation pipeline."""
        start_time = time.time()

        try:
            # Build index and sample
            self.build_embedding_index()
            self.sample_nodes()

            # Run evaluations
            results = {
                "metadata": {
                    "graph_path": str(self.graph_path),
                    "embedding_path": str(self.embedding_path),
                    "n_nodes_evaluated": len(self.node_list),
                    "sample_size": self.sample_size,
                },
            }

            # Neighborhood preservation
            results["neighborhood_preservation"] = self.evaluate_neighborhood_preservation()

            # Distance correlation
            results["distance_correlation"] = self.evaluate_distance_correlation()

            # Community preservation
            results["community_preservation"] = self.evaluate_community_preservation()

            results["runtime_seconds"] = time.time() - start_time

            return results

        finally:
            self.cleanup()

    def print_results(self, results: dict) -> None:
        """Print evaluation results in a nice table."""

        # Summary table
        table = Table(title="Memory-Efficient Embedding Evaluation Results", show_header=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        # Metadata
        table.add_row("Graph", Path(results["metadata"]["graph_path"]).name)
        table.add_row("Embedding", Path(results["metadata"]["embedding_path"]).name)
        table.add_row("Nodes Evaluated", f"{results['metadata']['n_nodes_evaluated']:,}")
        table.add_row("", "")

        # Neighborhood preservation
        if "neighborhood_preservation" in results:
            for k, scores in results["neighborhood_preservation"].items():
                table.add_row(
                    f"k-NN Preservation (k={k})",
                    f"{scores['mean']:.1%} ± {scores['std']:.1%}",
                )

        # Distance correlation
        if "distance_correlation" in results:
            dc = results["distance_correlation"]
            if not np.isnan(dc["spearman_r"]):
                table.add_row("", "")
                table.add_row("Distance Corr (Spearman r)", f"{dc['spearman_r']:.3f}")
                table.add_row(
                    "Distance Corr (Spearman R²)",
                    f"{dc['spearman_r2']:.3f} ({dc['spearman_r2'] * 100:.1f}% variance)",
                )
                table.add_row("Distance Corr (Pearson r)", f"{dc['pearson_r']:.3f}")
                table.add_row(
                    "Distance Corr (Pearson R²)",
                    f"{dc['pearson_r2']:.3f} ({dc['pearson_r2'] * 100:.1f}% variance)",
                )
                table.add_row("Connected Pairs Evaluated", f"{dc['n_pairs']:,}")

        # Community preservation
        if "community_preservation" in results:
            cp = results["community_preservation"]
            if cp:
                table.add_row("", "")
                table.add_row("Community Preservation (NMI)", f"{cp['nmi']:.3f}")
                if "ari" in cp:
                    table.add_row("Community Preservation (ARI)", f"{cp['ari']:.3f}")
                table.add_row("Clusters Used", str(cp["n_clusters"]))

        table.add_row("", "")
        table.add_row("Runtime", f"{results['runtime_seconds']:.1f}s")

        console.print(table)


def evaluate_single_embedding(
    embedding_path: Path,
    graph_path: Path,
    eval_cfg: dict,
    results_dir: Path,
    *,
    verbose: bool = True,
) -> dict:
    """Evaluate a single embedding file and return results.

    Args:
        embedding_path: Path to the embedding file
        graph_path: Path to the graph binary file
        eval_cfg: Evaluation configuration dict
        results_dir: Directory to save results
        verbose: Whether to print progress

    Returns:
        Dictionary with evaluation results
    """
    if verbose:
        console.print(f"[bold cyan]Evaluating: {embedding_path.name}[/bold cyan]")

    # Run evaluation with config params
    evaluator = MemoryEfficientEvaluator(
        graph_path,
        embedding_path,
        sample_size=eval_cfg.get("sample_size", 50000),
        chunk_size=eval_cfg.get("chunk_size", 5000),
    )
    results = evaluator.run_evaluation()

    if verbose:
        evaluator.print_results(results)

    # Save results with embedding-specific name
    embedding_name = embedding_path.stem
    results_path = results_dir / f"evaluation_{embedding_name}.json"

    with results_path.open("w") as f:
        json.dump(results, f, indent=2)

    if verbose:
        console.print(f"\n[green]✓ Results saved to {results_path}")

    return results


def main(embedding_suffix: str | None = None) -> None:
    """Main evaluation function."""

    # Load config
    config_path = Path(__file__).parent / "configs" / "evaluation_config.json"
    if not config_path.exists():
        console.print(f"[red]Config file not found: {config_path}")
        return
    with config_path.open() as f:
        all_configs = json.load(f)

    paths = all_configs.get("paths", {})
    # Look for experimental embeddings in experiments/embeddings/
    embeddings_dir = Path(__file__).parent / "embeddings"
    # Graph data is still in main data directory
    data_dir = Path(__file__).parent.parent / paths.get("data_dir", "data")

    # Use binary files
    graph_path = data_dir / paths.get("graph_binary", "graph.bin")

    # Determine which embedding to evaluate
    if embedding_suffix:
        # Check if it's just a suffix or a full filename
        if embedding_suffix.endswith(".bin"):
            embedding_path = embeddings_dir / embedding_suffix
        else:
            embedding_path = embeddings_dir / f"embeddings_{embedding_suffix}.bin"
    else:
        # Use default
        embedding_path = embeddings_dir / "embeddings_fastrp_128_q3.bin"

    if not graph_path.exists():
        console.print(f"[red]Graph not found: {graph_path}")
        return

    if not embedding_path.exists():
        console.print(f"[red]Embedding not found: {embedding_path}")
        console.print("[yellow]Available embeddings in experiments/embeddings/:")
        if embeddings_dir.exists():
            for f in sorted(embeddings_dir.glob("embeddings_*.bin")):
                console.print(f"  - {f.name}")
        return

    # Get evaluation params from config
    eval_cfg = all_configs.get("evaluation_params", {})
    results_dir = Path(__file__).parent / paths.get("results_dir", "results")
    results_dir.mkdir(exist_ok=True)

    # Use the new function
    evaluate_single_embedding(
        embedding_path=embedding_path,
        graph_path=graph_path,
        eval_cfg=eval_cfg,
        results_dir=results_dir,
        verbose=True,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Evaluate graph embeddings")
    parser.add_argument(
        "--file",
        type=str,
        help="Embedding file to evaluate (e.g., 'embeddings_fastrp_128_q3.bin' or just 'fastrp_128_q3')",
    )
    args = parser.parse_args()
    main(args.file)
