#!/usr/bin/env python3
"""Calculate graph metrics by loading the full graph into scipy.sparse CSR.

All summary stats (degree, weight, reciprocity, power-law fits) are exact.
Distributions are saved at full resolution for degrees; edge weights are
subsampled only for plot rendering (full set is hundreds of millions).
Clustering coefficient remains sampled — exact triangle counting at this
scale (billions of triplets) is not tractable.
"""

import argparse
import gc
import gzip
import json
import mmap
import pickle
import random
import struct
import time
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import orjson
import psutil
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table
from scipy import sparse, stats

console = Console()

MAX_EDGES_PER_NODE = 250
# Plot-rendering subsample sizes. Summary stats are computed from full data;
# these samples only feed plotly traces. Cap is driven by Cloudflare Pages'
# 25 MB per-file limit — full 5M-row arrays in plotly Histograms blow past it.
DEGREE_PLOT_SAMPLE = 200_000
WEIGHTS_PLOT_SAMPLE = 200_000
# Clustering coefficient sampling — full transitivity is O(sum of C(deg,2))
# which is billions of triplets at 5M+ nodes.
CLUSTERING_NODE_SAMPLE = 200_000
CLUSTERING_TRIPLET_SAMPLE = 1_000_000


# Binary format (matches core/src/pathfinding/utils.rs:73):
#   16 bytes UUID | u32 connection_count | n × (16 bytes UUID + f32 weight)
_EDGE_DTYPE = np.dtype([("uuid", "V16"), ("weight", "<f4")])


def _load_forward_index(metadata_path: Path) -> list[tuple[bytes, int]]:
    """Read metadata.bin's forward_index section: [(uuid_bytes, graph_bin_pos), ...]."""
    with metadata_path.open("rb") as f:
        # Header: 4 × u32 section offsets (lookup, metadata, forward_index, reverse_index)
        _, _, forward_offset, _ = struct.unpack("<4I", f.read(16))
        f.seek(forward_offset)
        (entry_count,) = struct.unpack("<I", f.read(4))
        # Each entry: 16 bytes UUID + 8 bytes u64 position
        raw = f.read(entry_count * 24)

    entries: list[tuple[bytes, int]] = []
    for i in range(entry_count):
        base = i * 24
        uuid_bytes = bytes(raw[base : base + 16])
        (pos,) = struct.unpack_from("<Q", raw, base + 16)
        entries.append((uuid_bytes, pos))
    return entries


def load_graph_csr_from_binary(
    metadata_path: Path,
    graph_path: Path,
) -> tuple[sparse.csr_matrix, dict[bytes, int], int]:
    """Build CSR by reading graph.bin via mmap + the forward_index in metadata.bin."""
    console.print(f"[cyan]Loading forward index from {metadata_path}...")
    forward_entries = _load_forward_index(metadata_path)
    forward_entries.sort(key=lambda e: e[1])
    console.print(f"[green]✓ {len(forward_entries):,} source nodes in index")

    console.print(f"[cyan]Loading graph file {graph_path} into memory...")
    t_read = time.time()
    graph_bytes = graph_path.read_bytes()
    console.print(
        f"[green]✓ Loaded {len(graph_bytes) / 1024**3:.2f} GB in {time.time() - t_read:.1f}s",
    )

    id_to_idx: dict[bytes, int] = {}

    def intern(uuid_b: bytes) -> int:
        idx = id_to_idx.get(uuid_b)
        if idx is None:
            idx = len(id_to_idx)
            id_to_idx[uuid_b] = idx
        return idx

    rows: list[npt.NDArray[np.int32]] = []
    cols: list[npt.NDArray[np.int32]] = []
    data: list[npt.NDArray[np.float32]] = []
    source_nodes = 0
    total_edges_seen = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Parsing graph.bin...", total=len(forward_entries))

        for i, (uuid_b, pos) in enumerate(forward_entries):
            if pos + 20 > len(graph_bytes):
                continue
            # 16-byte UUID stored in record (skip verify for speed)
            (conn_count,) = struct.unpack_from("<I", graph_bytes, pos + 16)
            src = intern(uuid_b)
            if conn_count == 0:
                continue
            source_nodes += 1
            edges_start = pos + 20

            # Vectorized parse of edge block — offset+count avoids slicing
            # the underlying bytes (zero-copy view)
            block = np.frombuffer(
                graph_bytes,
                dtype=_EDGE_DTYPE,
                count=conn_count,
                offset=edges_start,
            )
            # Intern all target UUIDs (still Python-level, but bulk extracted)
            tgt_indices = np.empty(conn_count, dtype=np.int32)
            uuid_view = block["uuid"]
            for k in range(conn_count):
                tgt_indices[k] = intern(bytes(uuid_view[k]))

            weights = block["weight"].copy()
            # Keep only positive weights
            mask = weights > 0
            if mask.all():
                rows.append(np.full(conn_count, src, dtype=np.int32))
                cols.append(tgt_indices)
                data.append(weights)
            else:
                rows.append(np.full(mask.sum(), src, dtype=np.int32))
                cols.append(tgt_indices[mask])
                data.append(weights[mask])
            total_edges_seen += conn_count

            if (i & 0xFFFF) == 0:
                progress.update(task, completed=i)

    # Release the big bytes object before building CSR. We must also drop
    # any numpy views (block, uuid_view) that reference graph_bytes via
    # `.base`, otherwise the refcount stays nonzero and the memory isn't
    # actually freed until function return.
    block = None
    uuid_view = None
    del graph_bytes
    gc.collect()

    n = len(id_to_idx)
    console.print(f"[green]✓ Parsed {n:,} nodes, {total_edges_seen:,} edges")

    rows_arr = np.concatenate(rows) if rows else np.empty(0, dtype=np.int32)
    cols_arr = np.concatenate(cols) if cols else np.empty(0, dtype=np.int32)
    data_arr = np.concatenate(data) if data else np.empty(0, dtype=np.float32)
    del rows, cols, data
    gc.collect()

    A = sparse.csr_matrix((data_arr, (rows_arr, cols_arr)), shape=(n, n))
    del rows_arr, cols_arr, data_arr
    gc.collect()
    A.sum_duplicates()
    A.eliminate_zeros()
    console.print(f"[green]✓ Built CSR: nnz={A.nnz:,}")
    return A, id_to_idx, source_nodes


def calculate_gini(values: npt.NDArray[np.float64]) -> float:
    sorted_values = np.sort(values)
    n = len(sorted_values)
    if n == 0:
        return 0.0
    cumsum = np.cumsum(sorted_values)
    if cumsum[-1] == 0:
        return 0.0
    return (2 * np.sum(np.arange(1, n + 1) * sorted_values)) / (n * cumsum[-1]) - (n + 1) / n


def degree_stats_dict(degrees: npt.NDArray[np.int64]) -> dict[str, Any]:
    return {
        "mean": float(np.mean(degrees)),
        "median": float(np.median(degrees)),
        "std": float(np.std(degrees)),
        "min": int(np.min(degrees)),
        "max": int(np.max(degrees)),
        "q25": float(np.percentile(degrees, 25)),
        "q75": float(np.percentile(degrees, 75)),
        "gini": calculate_gini(degrees.astype(np.float64)),
        "sample_size": int(len(degrees)),
    }


def weight_stats_dict(weights: npt.NDArray[np.float64]) -> dict[str, Any]:
    return {
        "mean": float(np.mean(weights)),
        "median": float(np.median(weights)),
        "std": float(np.std(weights)),
        "min": float(np.min(weights)),
        "max": float(np.max(weights)),
        "q25": float(np.percentile(weights, 25)),
        "q75": float(np.percentile(weights, 75)),
        "sample_size": int(len(weights)),
    }


def calculate_reciprocity(A: sparse.csr_matrix) -> float:
    """Exact reciprocity: fraction of edges (i,j) such that (j,i) also exists."""
    console.print("[cyan]Calculating reciprocity (exact)...")
    bin_a = (A > 0).astype(np.int8)
    # multiply elementwise: positions with both A[i,j] and A[j,i] > 0 stay positive
    reciprocal = bin_a.multiply(bin_a.T)
    rec = reciprocal.nnz / bin_a.nnz if bin_a.nnz else 0.0
    console.print(f"[green]✓ Reciprocity: {rec:.4%} over {bin_a.nnz:,} edges")
    return float(rec)


def power_law_fit(degrees: npt.NDArray[np.int64]) -> dict[str, Any] | None:
    positive = degrees[degrees > 0]
    if positive.size == 0:
        return None
    unique, counts = np.unique(positive, return_counts=True)
    if unique.size < 2:
        return None
    log_d = np.log10(unique.astype(np.float64))
    log_c = np.log10(counts.astype(np.float64))
    slope, intercept, r_value, _, _ = stats.linregress(log_d, log_c)
    return {
        "alpha": float(-slope),
        "intercept": float(intercept),
        "r_squared": float(r_value**2),
        "fit_range": [float(unique.min()), float(unique.max())],
        "n_points": int(unique.size),
    }


def clustering_coefficient(
    A: sparse.csr_matrix,
    node_sample: int = CLUSTERING_NODE_SAMPLE,
    triplet_sample: int = CLUSTERING_TRIPLET_SAMPLE,
) -> dict[str, Any]:
    """Sampled clustering coefficient using CSR neighbor lookups.

    Approach: pick random center nodes that have ≥2 out-neighbors, sample
    a pair (B, C) from their neighbors, check if B↔C or C↔B exists.
    """
    console.print("[cyan]Calculating clustering coefficient (sampled)...")
    indptr = A.indptr
    indices = A.indices
    row_lens = np.diff(indptr)
    valid = np.where(row_lens >= 2)[0]

    if valid.size == 0:
        return {
            "clustering_coefficient": 0.0,
            "triangles_sampled": 0,
            "triplets_sampled": 0,
            "sample_attempts": 0,
        }

    if valid.size > node_sample:
        valid = np.random.choice(valid, node_sample, replace=False)

    # Precompute neighbor sets for the sampled nodes — set membership is O(1).
    # The other ~2/3 of the time the script spends on random.randint dominates.
    neighbor_sets: dict[int, set[int]] = {
        int(a): set(indices[indptr[a] : indptr[a + 1]].tolist()) for a in valid
    }
    valid_list = list(neighbor_sets.keys())

    triangles = 0
    triplets = 0
    attempts = 0
    max_attempts = triplet_sample * 10

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Sampling triplets...", total=triplet_sample)

        while triplets < triplet_sample and attempts < max_attempts:
            attempts += 1
            a = random.choice(valid_list)
            neighbors_a = neighbor_sets[a]
            if len(neighbors_a) < 2:
                continue
            b, c = random.sample(tuple(neighbors_a), 2)
            triplets += 1
            # Triangle if B→C or C→B exists. Use precomputed sets where we
            # have them; fall back to indices lookup otherwise.
            b_neighbors = neighbor_sets.get(b)
            if b_neighbors is None:
                b_neighbors = set(indices[indptr[b] : indptr[b + 1]].tolist())
            if c in b_neighbors:
                triangles += 1
            else:
                c_neighbors = neighbor_sets.get(c)
                if c_neighbors is None:
                    c_neighbors = set(indices[indptr[c] : indptr[c + 1]].tolist())
                if b in c_neighbors:
                    triangles += 1
            if triplets % 10000 == 0:
                progress.update(task, completed=triplets)

    coef = triangles / triplets if triplets > 0 else 0.0
    console.print(f"[green]✓ Clustering: {coef:.4f} ({triangles:,}/{triplets:,})")
    return {
        "clustering_coefficient": coef,
        "triangles_sampled": triangles,
        "triplets_sampled": triplets,
        "sample_attempts": attempts,
    }


def _uuid_bytes_to_str(b: bytes) -> str:
    """Convert 16 raw UUID bytes to canonical 8-4-4-4-12 hex string."""
    import uuid as _uuid

    return str(_uuid.UUID(bytes=b))


def top_nodes(
    out_degrees: npt.NDArray[np.int64],
    in_degrees: npt.NDArray[np.int64],
    idx_to_id: dict[int, bytes],
    metadata_path: Path | None,
    n: int = 20,
) -> dict[str, list[tuple[str, int]]]:
    top_out_idx = np.argpartition(-out_degrees, min(n, out_degrees.size - 1))[:n]
    top_out_idx = top_out_idx[np.argsort(-out_degrees[top_out_idx])]
    top_in_idx = np.argpartition(-in_degrees, min(n, in_degrees.size - 1))[:n]
    top_in_idx = top_in_idx[np.argsort(-in_degrees[top_in_idx])]

    top_out_ids = [_uuid_bytes_to_str(idx_to_id[int(i)]) for i in top_out_idx]
    top_in_ids = [_uuid_bytes_to_str(idx_to_id[int(i)]) for i in top_in_idx]

    names: dict[str, str] = {}
    if metadata_path and metadata_path.exists():
        console.print("[cyan]Loading metadata for top nodes...")
        wanted = set(top_out_ids) | set(top_in_ids)
        with metadata_path.open("rb") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    d = orjson.loads(line)
                except orjson.JSONDecodeError:
                    continue
                if d["id"] in wanted:
                    names[d["id"]] = d["name"]

    return {
        "top_by_out_degree": [
            (names.get(nid, nid), int(out_degrees[i]))
            for i, nid in zip(top_out_idx, top_out_ids, strict=True)
        ],
        "top_by_in_degree": [
            (names.get(nid, nid), int(in_degrees[i]))
            for i, nid in zip(top_in_idx, top_in_ids, strict=True)
        ],
    }


def save_distributions(
    output_dir: Path,
    output_name: str,
    out_degrees: npt.NDArray[np.int64],
    in_degrees: npt.NDArray[np.int64],
    weights: npt.NDArray[np.float32],
    reciprocity: float,
) -> None:
    """Save subsampled distributions for plot rendering. Summary stats in
    graph_metrics.json remain exact — only what plotly inlines into the HTML
    needs to be capped (Cloudflare Pages 25 MB per-file limit)."""
    output_dir.mkdir(exist_ok=True, parents=True)

    def subsample(arr: npt.NDArray, k: int) -> npt.NDArray:
        if arr.size <= k:
            return arr
        idx = np.random.choice(arr.size, k, replace=False)
        return arr[idx]

    distributions: dict[str, Any] = {
        "out_degrees": subsample(out_degrees, DEGREE_PLOT_SAMPLE).tolist(),
        "in_degrees": subsample(in_degrees, DEGREE_PLOT_SAMPLE).tolist(),
        "weights": subsample(weights, WEIGHTS_PLOT_SAMPLE).tolist(),
        "reciprocity_info": {
            "sampled_edges": int(weights.size),  # exact: full edge count
            "reciprocity": reciprocity,
        },
    }

    dist_path = output_dir / f"{output_name}_distributions.pkl.gz"
    with gzip.open(dist_path, "wb") as fh:
        pickle.dump(distributions, fh, protocol=pickle.HIGHEST_PROTOCOL)
    console.print(f"[green]✓ Saved distributions: {dist_path}")

    # JSON fallback subset for Quarto
    max_json_samples = 5000

    def take(arr: list[Any], k: int) -> list[Any]:
        return arr if len(arr) <= k else random.sample(arr, k)

    json_sample = {
        "out_degrees": take(distributions["out_degrees"], max_json_samples),
        "in_degrees": take(distributions["in_degrees"], max_json_samples),
        "weights": take(distributions["weights"], max_json_samples),
        "reciprocity_info": distributions["reciprocity_info"],
    }
    json_path = output_dir / f"{output_name}_distributions_sample.json"
    with json_path.open("w") as fh:
        json.dump(json_sample, fh, indent=2)
    console.print(f"[green]✓ Saved JSON sample: {json_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Calculate graph metrics (exact, scipy.sparse)")
    parser.add_argument("--graph", type=str, help="Path to graph.bin (default: ../data/graph.bin)")
    parser.add_argument(
        "--metadata-bin", type=str, help="Path to metadata.bin (default: ../data/metadata.bin)"
    )
    parser.add_argument(
        "--metadata-ndjson",
        type=str,
        help="Path to metadata.ndjson for top-node names (default: ../data/metadata.ndjson)",
    )
    parser.add_argument("--output-prefix", type=str, help="Output name prefix (default: graph)")
    args = parser.parse_args()

    data_dir = Path("../data")
    graph_path = Path(args.graph) if args.graph else data_dir / "graph.bin"
    metadata_bin_path = Path(args.metadata_bin) if args.metadata_bin else data_dir / "metadata.bin"
    metadata_ndjson_path = (
        Path(args.metadata_ndjson) if args.metadata_ndjson else data_dir / "metadata.ndjson"
    )

    output_dir = Path(__file__).parent / "results" / "metrics"
    output_prefix = args.output_prefix or "graph"

    for p, label in [(graph_path, "graph"), (metadata_bin_path, "metadata.bin")]:
        if not p.exists():
            console.print(f"[red]Error: {label} file not found: {p}")
            return

    console.print("[bold cyan]Exact Graph Metrics (scipy.sparse, binary loader)[/bold cyan]")
    console.print(f"Graph: {graph_path}")
    console.print(f"Metadata: {metadata_bin_path}")

    start = time.time()
    A, id_to_idx, source_nodes = load_graph_csr_from_binary(metadata_bin_path, graph_path)
    n = A.shape[0]
    num_edges = int(A.nnz)

    # Reverse map for top-node lookup
    idx_to_id = {idx: uuid for uuid, idx in id_to_idx.items()}

    # Degree arrays (exact, from CSR)
    console.print("[cyan]Computing degree distributions...")
    out_degrees = np.asarray(A.getnnz(axis=1), dtype=np.int64)
    in_degrees = np.asarray(A.getnnz(axis=0), dtype=np.int64)

    # Weights (exact, from CSR data)
    weights = A.data.copy()

    # Reciprocity (exact)
    reciprocity = calculate_reciprocity(A)

    # Clustering (sampled — see module docstring)
    clustering = clustering_coefficient(A)

    # Power-law fits (exact, from full degree distributions)
    console.print("[cyan]Fitting power laws...")
    power_law_fits: dict[str, dict[str, Any]] = {}
    fit_out = power_law_fit(out_degrees)
    if fit_out:
        power_law_fits["out_degree_fit"] = fit_out
    fit_in = power_law_fit(in_degrees)
    if fit_in:
        power_law_fits["in_degree_fit"] = fit_in

    # Top nodes
    top = top_nodes(
        out_degrees,
        in_degrees,
        idx_to_id,
        metadata_ndjson_path if metadata_ndjson_path.exists() else None,
    )

    # Compose final metrics dict (schema-compatible with report.py)
    metrics_out: dict[str, Any] = {
        "dataset_info": {
            "nodes": n,
            "edges": num_edges,
            "source_nodes": source_nodes,
            "max_edges_per_node": MAX_EDGES_PER_NODE,
        },
        "basic_metrics": {
            "density": num_edges / (n * (n - 1)) if n > 1 else 0,
            "reciprocity": reciprocity,
            "reciprocity_sample_size": num_edges,  # exact: full edge count
        },
        "degree_stats": {
            "out_degree": degree_stats_dict(out_degrees),
            "in_degree": {
                **degree_stats_dict(in_degrees),
                "full_count": int(in_degrees.size),
            },
        },
        "weight_stats": weight_stats_dict(weights.astype(np.float64)),
        "clustering": clustering,
        "power_law_fits": power_law_fits,
        "top_nodes": top,
        "computation_time": time.time() - start,
    }

    # Save metrics + distributions
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = output_dir / f"{output_prefix}_metrics.json"
    with metrics_path.open("w") as fh:
        json.dump(metrics_out, fh, indent=2)
    console.print(f"[green]✓ Saved metrics: {metrics_path}")

    save_distributions(output_dir, output_prefix, out_degrees, in_degrees, weights, reciprocity)

    memory_mb = psutil.Process().memory_info().rss / (1024**2)
    console.print(f"[cyan]Peak resident memory: {memory_mb:.0f} MB")
    console.print(f"[cyan]Total time: {metrics_out['computation_time']:.1f} s")

    # Summary table
    table = Table(title="Graph Summary (exact)")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Nodes", f"{n:,}")
    table.add_row("Edges", f"{num_edges:,}")
    table.add_row("Source nodes", f"{source_nodes:,}")
    table.add_row("Density", f"{metrics_out['basic_metrics']['density']:.4%}")
    table.add_row("Reciprocity", f"{reciprocity:.1%}")
    table.add_row("Clustering", f"{clustering['clustering_coefficient']:.4f}")
    table.add_row(
        "Out-degree (mean/med/max)",
        f"{metrics_out['degree_stats']['out_degree']['mean']:.1f} / "
        f"{metrics_out['degree_stats']['out_degree']['median']:.1f} / "
        f"{metrics_out['degree_stats']['out_degree']['max']}",
    )
    table.add_row(
        "In-degree (mean/med/max)",
        f"{metrics_out['degree_stats']['in_degree']['mean']:.1f} / "
        f"{metrics_out['degree_stats']['in_degree']['median']:.1f} / "
        f"{metrics_out['degree_stats']['in_degree']['max']}",
    )
    console.print("\n")
    console.print(table)


if __name__ == "__main__":
    main()
