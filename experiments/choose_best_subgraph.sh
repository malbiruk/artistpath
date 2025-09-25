#!/bin/bash
# Test multiple random seeds for subgraph creation

set -e  # Exit on error

echo "Testing multiple seeds for subgraph creation"
echo "============================================"

# Seeds to test
SEEDS=(25 42 123 456 789 999)

for seed in "${SEEDS[@]}"; do
    echo -e "\n\n=========================================="
    echo "Testing seed: $seed"
    echo "=========================================="

    suffix="_seed${seed}"

    # Create subgraph
    echo "1. Creating subgraph with seed $seed..."
    uv run python create_subgraph.py --seed $seed --output-suffix "$suffix"

    # Calculate metrics
    echo -e "\n2. Calculating metrics for subgraph$suffix..."
    uv run python calculate_graph_metrics.py \
        --input "data/subgraph${suffix}.ndjson" \
        --output-prefix "subgraph${suffix}"

    # Compare with full graph
    echo -e "\n3. Comparing subgraph$suffix with full graph..."
    uv run python compare_graph_metrics.py \
        --sub-metrics "metrics/subgraph${suffix}_metrics.json" \
        --output "metrics/subgraph${suffix}_comparison.json"

    # Extract key metrics
    echo -e "\n4. Results for seed $seed:"
    python3 -c "
import json
with open('metrics/subgraph${suffix}_comparison.json') as f:
    data = json.load(f)
    print(f\"  Average difference: {data['assessment']['average_difference']:.2f}%\")
    print(f\"  Gini difference: {data['assessment']['details'][2]['difference']:.2f}%\")
    print(f\"  Overall: {data['assessment']['overall']}\")
"
done

echo -e "\n\n=========================================="
echo "Summary of all tested seeds:"
echo "=========================================="

# Display summary table
python3 -c "
import json
from pathlib import Path

print(f\"{'Seed':<10} {'Avg Diff %':<12} {'Gini Diff %':<12} {'Overall':<10}\")
print('-' * 50)

# Original subgraph (if exists)
if Path('metrics/graph_comparison.json').exists():
    with open('metrics/graph_comparison.json') as f:
        data = json.load(f)
        print(f\"{'original':<10} {data['assessment']['average_difference']:<12.2f} {data['assessment']['details'][2]['difference']:<12.2f} {data['assessment']['overall']:<10}\")

# Test all seed comparison files
for path in sorted(Path('metrics').glob('subgraph_seed*_comparison.json')):
    seed = path.stem.replace('subgraph_seed', '').replace('_comparison', '')
    with open(path) as f:
        data = json.load(f)
        print(f\"{seed:<10} {data['assessment']['average_difference']:<12.2f} {data['assessment']['details'][2]['difference']:<12.2f} {data['assessment']['overall']:<10}\")

print()
print('Best seed is the one with lowest average difference.')
"
