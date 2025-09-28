#!/usr/bin/env python3
"""Aggregate embedding evaluation results across seeds and rank configurations."""

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from rich.console import Console
from rich.table import Table

console = Console()


def extract_config_and_seed(filename: str) -> tuple[str, int] | tuple[None, None]:
    """Extract configuration name and seed from evaluation filename.

    Example: evaluation_embeddings_2d_dim256_q3_seed42.json -> (2d_dim256_q3, 42)
    """
    # Pattern to match seed at the end of filename
    pattern = r"evaluation_embeddings_(.+)_seed(\d+)$"
    match = re.match(pattern, filename.replace(".json", ""))

    if match:
        return match.group(1), int(match.group(2))

    # Try without seed (single evaluation)
    pattern_no_seed = r"evaluation_embeddings_(.+)$"
    match = re.match(pattern_no_seed, filename.replace(".json", ""))
    if match:
        return match.group(1), 0

    return None, None


def aggregate_metrics(results: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Aggregate metrics across multiple seeds.

    Returns dict with mean and std for each metric.
    """
    # Collect all metric values
    metrics_collection = defaultdict(list)

    for result in results:
        # Neighborhood preservation
        neighborhood = result.get("neighborhood_preservation", {})
        for k in ["10", "50"]:
            if k in neighborhood:
                metrics_collection[f"knn_{k}"].append(neighborhood[k].get("mean", 0))

        # Distance correlation
        corr = result.get("distance_correlation", {})
        if "spearman_r2" in corr:
            metrics_collection["spearman_r2"].append(corr["spearman_r2"])
        if "pearson_r2" in corr:
            metrics_collection["pearson_r2"].append(corr["pearson_r2"])

        # Community preservation
        comm = result.get("community_preservation", {})
        if "nmi" in comm:
            metrics_collection["nmi"].append(comm["nmi"])
        if "ari" in comm:
            metrics_collection["ari"].append(comm["ari"])

    # Calculate mean and std
    aggregated = {}
    for metric_name, values in metrics_collection.items():
        if values:
            aggregated[metric_name] = {
                "mean": float(np.mean(values)),
                "std": float(np.std(values)) if len(values) > 1 else 0.0,
                "n_seeds": len(values),
                "values": values,  # Keep raw values for inspection
            }

    return aggregated


def create_comparison_table(aggregated_results: dict[str, dict]) -> Table:
    """Create a rich table comparing all configurations."""
    table = Table(title="Embedding Configuration Comparison (Mean ± Std)", show_lines=True)

    # Headers
    table.add_column("Config", style="cyan", no_wrap=True)
    table.add_column("Seeds", style="white", justify="center")
    table.add_column("k-NN@10", style="green", justify="right")
    table.add_column("k-NN@50", style="green", justify="right")
    table.add_column("Spearman R²", style="blue", justify="right")
    table.add_column("Pearson R²", style="blue", justify="right")
    table.add_column("NMI", style="magenta", justify="right")
    table.add_column("ARI", style="magenta", justify="right")

    # Sort by config name
    for config in sorted(aggregated_results.keys()):
        metrics = aggregated_results[config]

        # Get number of seeds (should be consistent across metrics)
        n_seeds = max(m.get("n_seeds", 0) for m in metrics.values())

        def format_metric(metric_key: str) -> str:
            if metric_key in metrics:
                m = metrics[metric_key]
                if m["std"] > 0:
                    return f"{m['mean']:.3f} ± {m['std']:.3f}"
                else:
                    return f"{m['mean']:.3f}"
            return "-"

        table.add_row(
            config,
            str(n_seeds),
            format_metric("knn_10"),
            format_metric("knn_50"),
            format_metric("spearman_r2"),
            format_metric("pearson_r2"),
            format_metric("nmi"),
            format_metric("ari"),
        )

    return table


def rank_configurations(aggregated_results: dict[str, dict]) -> None:
    """Rank configurations by different criteria."""
    if not aggregated_results:
        return

    # Metrics to rank by (higher is better for all)
    metric_keys = ["knn_10", "knn_50", "spearman_r2", "pearson_r2", "nmi", "ari"]

    console.print("\n[bold yellow]Best Configurations by Metric:[/bold yellow]")

    # Find best for each metric
    for metric_key in metric_keys:
        valid_configs = [
            (config, metrics[metric_key]["mean"])
            for config, metrics in aggregated_results.items()
            if metric_key in metrics
        ]

        if valid_configs:
            best_config, best_value = max(valid_configs, key=lambda x: x[1])
            metric_display = metric_key.replace("_", " ").replace("knn", "k-NN@").upper()
            console.print(
                f"  {metric_display}: [cyan]{best_config}[/cyan] = [green]{best_value:.3f}"
            )

    # Overall ranking (average rank across all metrics)
    console.print("\n[bold yellow]Overall Ranking (by average rank):[/bold yellow]")

    config_ranks = defaultdict(list)

    for metric_key in metric_keys:
        # Get configs with this metric
        configs_with_metric = [
            (config, metrics.get(metric_key, {}).get("mean", 0))
            for config, metrics in aggregated_results.items()
        ]

        # Sort by metric value (descending)
        sorted_configs = sorted(configs_with_metric, key=lambda x: x[1], reverse=True)

        # Assign ranks
        for rank, (config, _) in enumerate(sorted_configs, 1):
            config_ranks[config].append(rank)

    # Calculate average rank
    avg_ranks = {}
    for config, ranks in config_ranks.items():
        avg_ranks[config] = np.mean(ranks) if ranks else float("inf")

    # Sort by average rank
    sorted_by_rank = sorted(avg_ranks.items(), key=lambda x: x[1])

    # Display top 5
    for i, (config, avg_rank) in enumerate(sorted_by_rank[:5], 1):
        console.print(f"  {i}. [cyan]{config}[/cyan] (avg rank: {avg_rank:.1f})")

    console.print(f"\n[bold green]Best Overall Configuration: {sorted_by_rank[0][0]}[/bold green]")


def statistical_comparison(aggregated_results: dict[str, dict]) -> None:
    """Provide statistical insights about the results."""
    console.print("\n[bold yellow]Statistical Insights:[/bold yellow]")

    # Check variability across seeds
    high_variance_configs = []
    for config, metrics in aggregated_results.items():
        for metric_name, metric_data in metrics.items():
            if metric_data["std"] > 0.1 * metric_data["mean"]:  # CV > 10%
                high_variance_configs.append(
                    (config, metric_name, metric_data["std"] / metric_data["mean"])
                )

    if high_variance_configs:
        console.print("\n[yellow]Configurations with high variability (CV > 10%):")
        for config, metric, cv in sorted(high_variance_configs, key=lambda x: x[2], reverse=True)[
            :5
        ]:
            console.print(f"  - {config} ({metric}): CV = {cv:.2%}")

    # Check consistency across metrics
    console.print("\n[yellow]Metric Correlations (top configs):")
    top_configs = set()
    for metric_key in ["knn_10", "knn_50", "spearman_r2", "nmi"]:
        configs = sorted(
            aggregated_results.items(),
            key=lambda x: x[1].get(metric_key, {}).get("mean", 0),
            reverse=True,
        )[:3]
        for config, _ in configs:
            top_configs.add(config)

    console.print(f"  Unique configs in top-3 across metrics: {len(top_configs)}")
    if len(top_configs) <= 3:
        console.print("  [green]High consistency: Same configs perform well across metrics")
    else:
        console.print("  [yellow]Low consistency: Different configs excel at different metrics")


def main(results_dir: Path | None = None) -> None:
    """Main aggregation function."""
    # Use provided directory or default
    if results_dir is None:
        results_dir = Path(__file__).parent / "results" / "embeddings_evaluation"

    if not results_dir.exists():
        console.print(f"[red]Results directory not found: {results_dir}")
        console.print("[yellow]Run evaluation first with: python evaluate_all_embeddings.py")
        return

    # Load all evaluation results
    result_files = list(results_dir.glob("evaluation_*.json"))
    if not result_files:
        console.print(f"[red]No evaluation results found in {results_dir}")
        return

    console.print(f"[cyan]Found {len(result_files)} evaluation results")

    # Group results by configuration
    config_results = defaultdict(list)

    for result_file in result_files:
        config_name, seed = extract_config_and_seed(result_file.name)

        if config_name is None:
            console.print(f"[yellow]Warning: Could not parse filename: {result_file.name}")
            continue

        with result_file.open() as f:
            result_data = json.load(f)
            config_results[config_name].append(result_data)

    console.print(f"[cyan]Found {len(config_results)} unique configurations")

    # Aggregate metrics for each configuration
    aggregated = {}
    for config_name, results in config_results.items():
        aggregated[config_name] = aggregate_metrics(results)

    # Display comparison table
    table = create_comparison_table(aggregated)
    console.print("\n")
    console.print(table)

    # Rank configurations
    rank_configurations(aggregated)

    # Statistical insights
    statistical_comparison(aggregated)

    # Save aggregated results
    output_path = results_dir.parent / "aggregated_results.json"
    with output_path.open("w") as f:
        json.dump(aggregated, f, indent=2)
    console.print(f"\n[green]Aggregated results saved to: {output_path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Aggregate embedding evaluation results")
    parser.add_argument(
        "--results-dir",
        type=Path,
        help="Path to evaluation results directory",
    )

    args = parser.parse_args()
    main(results_dir=args.results_dir)
