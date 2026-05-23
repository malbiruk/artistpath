#!/usr/bin/env python3
"""Compare metrics between full graph and subgraph with statistical tests."""

import argparse
import gzip
import json
import pickle
from pathlib import Path
from typing import Any

import numpy as np
from rich.console import Console
from rich.table import Table
from scipy import stats

console = Console()


def load_metrics(metrics_path: Path) -> dict[str, Any]:
    """Load metrics from JSON file."""
    with metrics_path.open() as f:
        return json.load(f)


def load_distributions(dist_path: Path) -> dict[str, Any]:
    """Load distribution data from compressed pickle."""
    with gzip.open(dist_path, "rb") as f:
        return pickle.load(f)


def calculate_relative_difference(val1: float, val2: float) -> float:
    """Calculate relative difference as percentage."""
    if val1 == 0:
        return 0 if val2 == 0 else float("inf")
    return abs(val1 - val2) / abs(val1) * 100


def perform_statistical_tests(
    full_dist: dict[str, list[float]],
    sub_dist: dict[str, list[float]],
) -> dict[str, dict[str, Any]]:
    """Perform statistical tests on distributions."""
    results = {}

    for dist_name in ["out_degrees", "in_degrees", "weights"]:
        if dist_name not in full_dist or dist_name not in sub_dist:
            continue

        full_data = np.array(full_dist[dist_name])
        sub_data = np.array(sub_dist[dist_name])

        # Limit sample size for tests (use random sampling if too large)
        max_samples = 10000
        if len(full_data) > max_samples:
            full_data = np.random.choice(full_data, max_samples, replace=False)
        if len(sub_data) > max_samples:
            sub_data = np.random.choice(sub_data, max_samples, replace=False)

        # Kolmogorov-Smirnov test for distribution similarity
        ks_stat, ks_pval = stats.ks_2samp(full_data, sub_data)

        # Mann-Whitney U test for central tendency
        mw_stat, mw_pval = stats.mannwhitneyu(full_data, sub_data, alternative="two-sided")

        # Levene's test for variance equality
        lev_stat, lev_pval = stats.levene(full_data, sub_data)

        # Effect size (Cohen's d)
        pooled_std = np.sqrt((np.std(full_data) ** 2 + np.std(sub_data) ** 2) / 2)
        cohens_d = abs(np.mean(full_data) - np.mean(sub_data)) / pooled_std if pooled_std > 0 else 0

        results[dist_name] = {
            "ks_test": {
                "statistic": float(ks_stat),
                "p_value": float(ks_pval),
                "significant": ks_pval < 0.05,
                "interpretation": "Distributions differ"
                if ks_pval < 0.05
                else "Distributions similar",
            },
            "mann_whitney": {
                "statistic": float(mw_stat),
                "p_value": float(mw_pval),
                "significant": mw_pval < 0.05,
                "interpretation": "Central tendencies differ"
                if mw_pval < 0.05
                else "Central tendencies similar",
            },
            "levene": {
                "statistic": float(lev_stat),
                "p_value": float(lev_pval),
                "significant": lev_pval < 0.05,
                "interpretation": "Variances differ" if lev_pval < 0.05 else "Variances similar",
            },
            "effect_size": {
                "cohens_d": float(cohens_d),
                "interpretation": (
                    "Negligible"
                    if cohens_d < 0.2
                    else "Small"
                    if cohens_d < 0.5
                    else "Medium"
                    if cohens_d < 0.8
                    else "Large"
                ),
            },
        }

    return results


def display_dataset_size_comparison(
    full_info: dict[str, Any],
    sub_info: dict[str, Any],
) -> dict[str, Any]:
    """Display dataset size comparison table."""
    console.print("\n[bold cyan]Dataset Size Comparison")
    table = Table(show_lines=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Full Graph", style="green")
    table.add_column("Subgraph", style="yellow")
    table.add_column("Ratio", style="magenta")

    comparison = {
        "full": full_info,
        "subgraph": sub_info,
        "ratios": {
            "nodes": sub_info["nodes"] / full_info["nodes"],
            "edges": sub_info["edges"] / full_info["edges"],
        },
    }

    table.add_row(
        "Nodes",
        f"{full_info['nodes']:,}",
        f"{sub_info['nodes']:,}",
        f"{comparison['ratios']['nodes']:.1%}",
    )

    table.add_row(
        "Edges",
        f"{full_info['edges']:,}",
        f"{sub_info['edges']:,}",
        f"{comparison['ratios']['edges']:.1%}",
    )

    console.print(table)
    return comparison


def display_degree_distribution_comparison(
    full_metrics: dict[str, Any],
    sub_metrics: dict[str, Any],
) -> dict[str, Any]:
    """Display degree distribution comparison table."""
    console.print("\n[bold cyan]Degree Distribution Comparison")
    table = Table(show_lines=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Full Graph", style="green")
    table.add_column("Subgraph", style="yellow")
    table.add_column("Diff %", style="magenta")

    comparison = {}

    for degree_type in ["out_degree", "in_degree"]:
        full_deg = full_metrics["degree_stats"][degree_type]
        sub_deg = sub_metrics["degree_stats"][degree_type]

        comparison[degree_type] = {
            "full": full_deg,
            "subgraph": sub_deg,
            "differences": {},
        }

        for stat in ["mean", "median", "std", "gini"]:
            diff = calculate_relative_difference(full_deg[stat], sub_deg[stat])
            comparison[degree_type]["differences"][stat] = diff

            table.add_row(
                f"{degree_type} {stat}",
                f"{full_deg[stat]:.1f}" if stat != "gini" else f"{full_deg[stat]:.3f}",
                f"{sub_deg[stat]:.1f}" if stat != "gini" else f"{sub_deg[stat]:.3f}",
                f"{diff:.1f}%",
            )

        if degree_type == "out_degree":
            table.add_row("", "", "", "")  # Separator

    console.print(table)
    return comparison


def display_statistical_tests(
    statistical_tests: dict[str, dict[str, Any]],
) -> None:
    """Display statistical tests results table."""
    if not statistical_tests:
        return

    console.print("\n[bold cyan]Statistical Tests Results")
    table = Table(show_lines=True)
    table.add_column("Distribution", style="cyan")
    table.add_column("K-S Test", style="yellow")
    table.add_column("Mann-Whitney", style="yellow")
    table.add_column("Levene's Test", style="yellow")
    table.add_column("Cohen's d", style="magenta")

    for dist_name in ["out_degrees", "in_degrees", "weights"]:
        if dist_name in statistical_tests:
            tests = statistical_tests[dist_name]
            table.add_row(
                dist_name.replace("_", " ").title(),
                f"p={tests['ks_test']['p_value']:.4f}\n{tests['ks_test']['interpretation']}",
                f"p={tests['mann_whitney']['p_value']:.4f}\n{tests['mann_whitney']['interpretation']}",
                f"p={tests['levene']['p_value']:.4f}\n{tests['levene']['interpretation']}",
                f"{tests['effect_size']['cohens_d']:.3f}\n{tests['effect_size']['interpretation']}",
            )

    console.print(table)


def display_power_law_comparison(
    full_metrics: dict[str, Any],
    sub_metrics: dict[str, Any],
) -> dict[str, Any]:
    """Display power law fits comparison table."""
    console.print("\n[bold cyan]Power Law Fits Comparison")
    table = Table(show_lines=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Full Graph", style="green")
    table.add_column("Subgraph", style="yellow")
    table.add_column("Diff %", style="magenta")

    if "power_law_fits" not in full_metrics or "power_law_fits" not in sub_metrics:
        return {}

    comparison = {
        "full": full_metrics["power_law_fits"],
        "subgraph": sub_metrics["power_law_fits"],
        "differences": {},
    }

    for fit_type in ["out_degree_fit", "in_degree_fit"]:
        if fit_type in full_metrics["power_law_fits"] and fit_type in sub_metrics["power_law_fits"]:
            full_fit = full_metrics["power_law_fits"][fit_type]
            sub_fit = sub_metrics["power_law_fits"][fit_type]

            comparison["differences"][fit_type] = {}

            for metric in ["alpha", "r_squared"]:
                diff = calculate_relative_difference(full_fit[metric], sub_fit[metric])
                comparison["differences"][fit_type][metric] = diff

                table.add_row(
                    f"{fit_type} {metric}",
                    f"{full_fit[metric]:.3f}",
                    f"{sub_fit[metric]:.3f}",
                    f"{diff:.1f}%",
                )

            if fit_type == "out_degree_fit":
                table.add_row("", "", "", "")  # Separator

    console.print(table)
    return comparison


def display_other_metrics_comparison(
    full_basic: dict[str, Any],
    sub_basic: dict[str, Any],
) -> dict[str, Any]:
    """Display other metrics comparison table."""
    console.print("\n[bold cyan]Other Metrics Comparison")
    table = Table(show_lines=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Full Graph", style="green")
    table.add_column("Subgraph", style="yellow")
    table.add_column("Diff %", style="magenta")

    comparison = {
        "full": full_basic,
        "subgraph": sub_basic,
        "differences": {},
    }

    for metric in ["density", "reciprocity"]:
        diff = calculate_relative_difference(full_basic[metric], sub_basic[metric])
        comparison["differences"][metric] = diff

        table.add_row(
            metric.capitalize(),
            f"{full_basic[metric]:.6f}" if metric == "density" else f"{full_basic[metric]:.3f}",
            f"{sub_basic[metric]:.6f}" if metric == "density" else f"{sub_basic[metric]:.3f}",
            f"{diff:.1f}%",
        )

    console.print(table)
    return comparison


def calculate_representativeness_assessment(
    full_metrics: dict[str, Any],
    sub_metrics: dict[str, Any],
) -> dict[str, Any]:
    """Calculate and display representativeness assessment."""
    console.print("\n[bold cyan]Representativeness Assessment")

    full_basic = full_metrics["basic_metrics"]
    sub_basic = sub_metrics["basic_metrics"]

    key_metrics = [
        (
            "degree_mean",
            full_metrics["degree_stats"]["out_degree"]["mean"],
            sub_metrics["degree_stats"]["out_degree"]["mean"],
        ),
        (
            "degree_std",
            full_metrics["degree_stats"]["out_degree"]["std"],
            sub_metrics["degree_stats"]["out_degree"]["std"],
        ),
        (
            "degree_gini",
            full_metrics["degree_stats"]["out_degree"]["gini"],
            sub_metrics["degree_stats"]["out_degree"]["gini"],
        ),
        ("reciprocity", full_basic["reciprocity"], sub_basic["reciprocity"]),
    ]

    # Add clustering coefficient if available
    if "clustering" in full_metrics and "clustering" in sub_metrics:
        key_metrics.append(
            (
                "clustering",
                full_metrics["clustering"]["clustering_coefficient"],
                sub_metrics["clustering"]["clustering_coefficient"],
            )
        )

    differences = []
    assessment_details = []

    for name, full_val, sub_val in key_metrics:
        diff = calculate_relative_difference(full_val, sub_val)
        differences.append(diff)

        status = "✅" if diff < 10 else "⚠️" if diff < 20 else "❌"
        console.print(f"  {status} {name}: {diff:.1f}% difference")
        assessment_details.append(
            {
                "metric": name,
                "difference": diff,
                "status": "good" if diff < 10 else "warning" if diff < 20 else "poor",
            },
        )

    avg_diff = np.mean(differences)

    if avg_diff < 10:
        console.print(f"\n[bold green]✅ Excellent representativeness (avg diff: {avg_diff:.1f}%)")
        console.print("The subgraph preserves key graph properties very well.")
        overall_assessment = "excellent"
    elif avg_diff < 20:
        console.print(f"\n[bold yellow]⚠️ Good representativeness (avg diff: {avg_diff:.1f}%)")
        console.print("The subgraph is reasonably representative for hyperparameter optimization.")
        overall_assessment = "good"
    else:
        console.print(f"\n[bold red]❌ Poor representativeness (avg diff: {avg_diff:.1f}%)")
        console.print("Consider adjusting the sampling strategy.")
        overall_assessment = "poor"

    return {
        "details": assessment_details,
        "average_difference": avg_diff,
        "overall": overall_assessment,
    }


def convert_numpy_types(obj: object) -> object:
    """Convert numpy types to native Python types for JSON serialization."""
    type_converters = {
        np.bool_: bool,
        np.integer: int,
        np.floating: float,
        np.ndarray: lambda x: x.tolist(),
        dict: lambda x: {key: convert_numpy_types(value) for key, value in x.items()},
        list: lambda x: [convert_numpy_types(item) for item in x],
    }

    for type_check, converter in type_converters.items():
        if isinstance(obj, type_check):
            return converter(obj)

    return obj


def compare_metrics(
    full_metrics: dict[str, Any],
    sub_metrics: dict[str, Any],
    statistical_tests: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Compare and display metrics between full graph and subgraph."""
    comparison_results = {}

    # Dataset size comparison
    comparison_results["dataset_size"] = display_dataset_size_comparison(
        full_metrics["dataset_info"],
        sub_metrics["dataset_info"],
    )

    # Degree distribution comparison
    comparison_results["degree_stats"] = display_degree_distribution_comparison(
        full_metrics,
        sub_metrics,
    )

    # Statistical tests
    if statistical_tests:
        display_statistical_tests(statistical_tests)
        comparison_results["statistical_tests"] = statistical_tests

    # Power law comparison
    power_law_comp = display_power_law_comparison(full_metrics, sub_metrics)
    if power_law_comp:
        comparison_results["power_law_fits"] = power_law_comp

    # Other metrics comparison
    comparison_results["basic_metrics"] = display_other_metrics_comparison(
        full_metrics["basic_metrics"],
        sub_metrics["basic_metrics"],
    )

    # Representativeness assessment
    comparison_results["assessment"] = calculate_representativeness_assessment(
        full_metrics,
        sub_metrics,
    )

    # Convert all numpy types to native Python types for JSON serialization
    return convert_numpy_types(comparison_results)


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Compare full graph and subgraph metrics")
    parser.add_argument(
        "--full-metrics",
        type=Path,
        default=Path("metrics/graph_metrics.json"),
        help="Path to full graph metrics JSON (default: metrics/graph_metrics.json)",
    )
    parser.add_argument(
        "--sub-metrics",
        type=Path,
        default=Path("metrics/subgraph_metrics.json"),
        help="Path to subgraph metrics JSON (default: metrics/subgraph_metrics.json)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("metrics/graph_comparison.json"),
        help="Output path for comparison results (default: metrics/graph_comparison.json)",
    )
    args = parser.parse_args()

    # Load full graph metrics
    full_metrics_path = args.full_metrics
    if not full_metrics_path.exists():
        console.print(f"[red]Full graph metrics not found: {full_metrics_path}")
        console.print("[yellow]Run: python calculate_graph_metrics.py")
        return

    # Load subgraph metrics
    sub_metrics_path = args.sub_metrics
    if not sub_metrics_path.exists():
        console.print(f"[red]Subgraph metrics not found: {sub_metrics_path}")
        console.print(
            "[yellow]Run: python calculate_graph_metrics.py --input ../data/subgraph.ndjson --output-prefix subgraph",
        )
        return

    full_metrics = load_metrics(full_metrics_path)
    sub_metrics = load_metrics(sub_metrics_path)

    # Try to load distribution data for statistical tests
    statistical_tests = {}
    # Derive distribution paths from metrics paths
    full_dist_path = full_metrics_path.parent / full_metrics_path.stem.replace(
        "_metrics",
        "_distributions",
    ).replace("graph", "graph_distributions")
    if not full_dist_path.with_suffix(".pkl.gz").exists():
        full_dist_path = full_metrics_path.parent / "graph_distributions.pkl.gz"
    else:
        full_dist_path = full_dist_path.with_suffix(".pkl.gz")

    sub_dist_path = sub_metrics_path.parent / sub_metrics_path.stem.replace(
        "_metrics",
        "_distributions",
    )
    if not sub_dist_path.with_suffix(".pkl.gz").exists():
        sub_dist_path = sub_metrics_path.parent / "subgraph_distributions.pkl.gz"
    else:
        sub_dist_path = sub_dist_path.with_suffix(".pkl.gz")

    if full_dist_path.exists() and sub_dist_path.exists():
        console.print("[cyan]Loading distribution data for statistical tests...")
        full_dist = load_distributions(full_dist_path)
        sub_dist = load_distributions(sub_dist_path)
        statistical_tests = perform_statistical_tests(full_dist, sub_dist)
    else:
        console.print("[yellow]Distribution files not found, skipping statistical tests")

    console.print("[bold cyan]Graph Metrics Comparison")
    console.print("Comparing full graph vs representative subgraph")

    comparison_results = compare_metrics(full_metrics, sub_metrics, statistical_tests)

    # Save comparison results
    output_path = args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as f:
        json.dump(comparison_results, f, indent=2)

    console.print(f"\n[green]✅ Comparison results saved to: {output_path}")
    console.print("\n[green]✨ Comparison complete!")


if __name__ == "__main__":
    main()
