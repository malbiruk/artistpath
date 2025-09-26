#!/usr/bin/env python3
"""Generate embeddings for all configs in a configuration file."""

import argparse
import json
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from generate_embedding import generate_embedding

console = Console()

# Default seeds for robust evaluation
DEFAULT_SEEDS = [25, 42, 123, 456, 789]


def load_config_names(config_file: str) -> list[str]:
    """Load all config names from configuration file."""
    config_path = Path(__file__).parent / "configs" / config_file
    if not config_path.exists():
        config_path = Path(__file__).parent / config_file

    if not config_path.exists():
        console.print(f"[red]Config file not found: {config_path}")
        return []

    with config_path.open() as f:
        all_configs = json.load(f)

    return [cfg["name"] for cfg in all_configs["configs"]]


def main(
    configs: list[str] | None = None,
    *,
    skip_existing: bool = False,
    config_file: str = "phase1_fastrp_optimization.json",
    seeds: list[int] | None = None,
    single_seed: bool = False,
    graph_path: str | None = None,
) -> None:
    """Generate embeddings for specified configs.

    Args:
        configs: List of config names or ["all"] for all configs
        skip_existing: Skip configs that already have embeddings
        config_file: Config file to use
        seeds: List of random seeds to use
        single_seed: Use only first seed (for quick testing)
        graph_path: Path to graph file (default: data/subgraph.ndjson)
    """
    # Load available configs
    available_configs = load_config_names(config_file)
    if not available_configs:
        return

    # Determine which configs to run
    if configs and configs[0] == "all":
        configs_to_run = available_configs
    elif configs:
        configs_to_run = configs
        # Validate configs
        invalid = [c for c in configs_to_run if c not in available_configs]
        if invalid:
            console.print(f"[red]Invalid configs: {invalid}")
            console.print(f"[yellow]Available configs: {available_configs}")
            return
    else:
        console.print("[yellow]No configs specified. Available configs:")
        for cfg in available_configs:
            console.print(f"  - {cfg}")
        return

    # Determine seeds to use
    if single_seed:
        seeds_to_use = [DEFAULT_SEEDS[0]]  # Just use first seed
        console.print(f"[yellow]Single-seed mode: using seed {seeds_to_use[0]}")
    else:
        seeds_to_use = seeds if seeds else DEFAULT_SEEDS
        console.print(f"[cyan]Using seeds: {seeds_to_use}")

    # Check existing embeddings
    embeddings_dir = Path(__file__).parent / "embeddings"
    embeddings_dir.mkdir(exist_ok=True)

    # Build list of (config, seed) pairs to run
    tasks_to_run = []
    for cfg in configs_to_run:
        for seed in seeds_to_use:
            if skip_existing:
                # Check if embedding already exists for this config+seed
                pattern = f"embeddings_2d_{cfg}_seed{seed}.bin"
                if list(embeddings_dir.glob(pattern)):
                    console.print(f"[yellow]Skipping existing: {cfg} seed={seed}")
                    continue
            tasks_to_run.append((cfg, seed))

    if not tasks_to_run:
        console.print("[yellow]No configs to run (all already exist)")
        return

    # Generate embeddings
    total_tasks = len(tasks_to_run)
    console.print(
        Panel.fit(
            f"[bold cyan]Generating Embeddings[/bold cyan]\n\n"
            f"Config file: {config_file}\n"
            f"Total tasks: {total_tasks} ({len(configs_to_run)} configs × {len(seeds_to_use)} seeds)",
            padding=1,
        ),
    )

    # Track results
    results = []

    for i, (config_name, seed) in enumerate(tasks_to_run, 1):
        console.print(f"\n[bold]Running task {i}/{total_tasks}: {config_name} (seed={seed})[/bold]")
        console.print("=" * 60)

        try:
            output_path, success = generate_embedding(
                config_name=config_name,
                config_file=config_file,
                verbose=True,
                seed=seed,
                graph_path=graph_path,
            )

            if success:
                results.append((config_name, seed, "✅ Success", output_path))
                console.print(f"\n[green]✅ Successfully generated: {config_name} (seed={seed})")
            else:
                results.append((config_name, seed, "❌ Failed", None))
                console.print(f"\n[red]❌ Failed to generate: {config_name} (seed={seed})")
        except Exception as e:
            results.append((config_name, seed, f"❌ Error: {e!s}", None))
            console.print(f"\n[red]❌ Error generating {config_name} (seed={seed}): {e}")

    # Summary
    console.print("\n" + "=" * 60)
    table = Table(title="Generation Summary")
    table.add_column("Config", style="cyan")
    table.add_column("Seed", style="magenta")
    table.add_column("Status", style="green")
    table.add_column("Output", style="blue")

    for config_name, seed, status, output in results:
        output_str = output.name if output else "-"
        table.add_row(config_name, str(seed), status, output_str)

    console.print(table)

    successful = sum(1 for _, _, status, _ in results if "Success" in status)
    console.print(f"\n[bold]Completed: {successful}/{total_tasks} successful")

    if successful == total_tasks:
        console.print("[green]✨ All embeddings generated successfully!")
        console.print("[yellow]Run `evaluate_all_embeddings.py` to evaluate and compare results")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate embeddings for multiple configs")
    parser.add_argument(
        "configs",
        nargs="*",
        help="Config names to run (use 'all' for all configs)",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip configs that already have embeddings",
    )
    parser.add_argument(
        "--config-file",
        default="phase1_fastrp_optimization.json",
        help="Config file to use",
    )
    parser.add_argument(
        "--seeds",
        type=int,
        nargs="+",
        help="Random seeds to use (default: 25 42 123 456 789)",
    )
    parser.add_argument(
        "--single-seed",
        action="store_true",
        help="Use only first seed for quick testing",
    )
    parser.add_argument(
        "--graph",
        type=str,
        default="data/subgraph.ndjson",
        help="Path to graph file (default: data/subgraph.ndjson)",
    )

    args = parser.parse_args()
    main(
        configs=args.configs,
        skip_existing=args.skip_existing,
        config_file=args.config_file,
        seeds=args.seeds,
        single_seed=args.single_seed,
        graph_path=args.graph,
    )
