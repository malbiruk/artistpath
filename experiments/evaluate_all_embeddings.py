#!/usr/bin/env python3
"""Evaluate all embeddings and compare results."""

import json
from pathlib import Path

from rich.console import Console
from rich.table import Table

from evaluate_embedding import evaluate_single_embedding

console = Console()


def load_existing_results(results_dir: Path) -> dict[str, dict]:
    """Load all existing evaluation results."""
    results = {}
    for result_file in results_dir.glob("evaluation_*.json"):
        embedding_name = result_file.stem.replace("evaluation_", "")
        with result_file.open() as f:
            results[embedding_name] = json.load(f)
    return results


def create_comparison_table(results: dict[str, dict]) -> Table:
    """Create comparison table for all results."""
    table = Table(title="Embedding Comparison", show_lines=True)

    # Headers
    table.add_column("Embedding", style="cyan", no_wrap=True)
    table.add_column("k-NN@10", style="green", justify="right")
    table.add_column("k-NN@50", style="green", justify="right")
    table.add_column("Spearman R²", style="blue", justify="right")
    table.add_column("Pearson R²", style="blue", justify="right")
    table.add_column("NMI", style="magenta", justify="right")
    table.add_column("ARI", style="magenta", justify="right")

    # Sort by name
    for name in sorted(results.keys()):
        r = results[name]
        # Fix: Use correct keys from actual JSON structure
        neighborhood = r.get("neighborhood_preservation", {})
        corr = r.get("distance_correlation", {})
        comm = r.get("community_preservation", {})

        # Extract config from name
        config_str = name.replace("embeddings_", "")

        table.add_row(
            config_str,
            f"{neighborhood.get('10', {}).get('mean', 0):.3f}",
            f"{neighborhood.get('50', {}).get('mean', 0):.3f}",
            f"{corr.get('spearman_r2', 0):.3f}",
            f"{corr.get('pearson_r2', 0):.3f}",
            f"{comm.get('nmi', 0):.3f}",
            f"{comm.get('ari', 0):.3f}",
        )

    return table


def find_best_configs(results: dict[str, dict]) -> None:
    """Identify best configurations per metric."""
    if not results:
        return

    metrics = {
        "k-NN@10": lambda r: r.get("neighborhood_preservation", {}).get("10", {}).get("mean", 0),
        "k-NN@50": lambda r: r.get("neighborhood_preservation", {}).get("50", {}).get("mean", 0),
        "Spearman R²": lambda r: r.get("distance_correlation", {}).get("spearman_r2", 0),
        "Pearson R²": lambda r: r.get("distance_correlation", {}).get("pearson_r2", 0),
        "NMI": lambda r: r.get("community_preservation", {}).get("nmi", 0),
        "ARI": lambda r: r.get("community_preservation", {}).get("ari", 0),
    }

    console.print("\n[bold yellow]Best Configurations:")
    for metric_name, metric_func in metrics.items():
        best_name = max(results.keys(), key=lambda n: metric_func(results[n]))
        best_value = metric_func(results[best_name])
        config = best_name.replace("embeddings_", "")
        console.print(f"  {metric_name}: [cyan]{config}[/cyan] = [green]{best_value:.3f}")

    # Overall best (average rank)
    ranks = {}
    for metric_func in metrics.values():
        sorted_names = sorted(results.keys(), key=lambda n: metric_func(results[n]), reverse=True)
        for rank, name in enumerate(sorted_names):
            ranks[name] = ranks.get(name, 0) + rank

    best_overall = min(ranks.keys(), key=lambda n: ranks[n])
    console.print(f"\n[bold green]Best Overall: {best_overall.replace('embeddings_', '')}")


def main(*, compare_only: bool = False, graph_path: str | None = None) -> None:
    """Main evaluation function.

    Args:
        compare_only: Only compare existing results, don't run new evaluations
        graph_path: Path to graph binary file (default: data/subgraph.bin)
    """
    # Load config
    config_path = Path(__file__).parent / "configs" / "evaluation_config.json"
    if not config_path.exists():
        console.print(f"[red]Config not found: {config_path}")
        return

    with config_path.open() as f:
        all_configs = json.load(f)

    paths = all_configs.get("paths", {})
    eval_cfg = all_configs.get("evaluation_params", {})

    # Directories
    embeddings_dir = Path(__file__).parent / "embeddings"
    results_dir = Path(__file__).parent / paths.get("results_dir", "results")
    results_dir.mkdir(exist_ok=True)

    # Graph path
    if graph_path:
        graph_path = Path(graph_path)
    else:
        # Default to subgraph.bin in experiments/data
        graph_path = Path(__file__).parent / "data" / "subgraph.bin"

    if not graph_path.exists():
        console.print(f"[red]Graph not found: {graph_path}")
        console.print("[yellow]Make sure to generate the binary graph file first")
        return

    if not compare_only:
        # Find all embeddings to evaluate
        embeddings = list(embeddings_dir.glob("embeddings_*.bin"))

        if not embeddings:
            console.print(f"[red]No embeddings found in {embeddings_dir}")
            console.print("[yellow]Run `generate_all_embeddings.py` first")
            return

        console.print(f"[cyan]Found {len(embeddings)} embeddings to evaluate")

        # Evaluate each embedding
        for embedding_path in sorted(embeddings):
            # Check if already evaluated
            embedding_name = embedding_path.stem
            result_path = results_dir / f"evaluation_{embedding_name}.json"

            if result_path.exists():
                console.print(f"[yellow]Skipping {embedding_name} (already evaluated)")
                continue

            # Evaluate using the imported function
            evaluate_single_embedding(
                embedding_path=embedding_path,
                graph_path=graph_path,
                eval_cfg=eval_cfg,
                results_dir=results_dir,
                verbose=True,
            )

    # Load and compare results
    results = load_existing_results(results_dir)
    if results:
        console.print("\n" + "=" * 60)
        table = create_comparison_table(results)
        console.print(table)
        find_best_configs(results)
    else:
        console.print("[yellow]No results found to compare")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Evaluate all embeddings and compare")
    parser.add_argument(
        "--compare-only",
        action="store_true",
        help="Only compare existing results, don't run new evaluations",
    )
    parser.add_argument(
        "--graph",
        type=str,
        default="data/subgraph.bin",
        help="Path to graph binary file (default: data/subgraph.bin)",
    )
    args = parser.parse_args()
    main(compare_only=args.compare_only, graph_path=args.graph)
