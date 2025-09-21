# Experiments

Scientific analysis and experimentation scripts for the artist similarity graph.

## Scripts

### `calculate_graph_metrics.py`
**Purpose:** Analyze graph properties and collect full distributions
**Output:**
- `metrics/graph_metrics.json` - Statistics and analysis results
- `metrics/distributions.pkl.gz` - Full distribution data (compressed)
- `metrics/distributions_sample.json` - Sampled data for visualization

**Key Metrics Calculated:**
- **Degree distribution** - Power law fitting (α, R²), Gini coefficient
- **Edge weights** - Distribution, percentiles, skewness
- **Graph structure** - Density, reciprocity, connected components
- **Top nodes** - Most connected artists (hub identification)
- **Full distributions** - Saved for visualization in reports

**Memory-efficient:** Streaming analysis with sampling for 850k node graph

### `graph_analysis_report.qmd`
**Purpose:** Interactive visualization report of graph metrics
**Output:** HTML (interactive) and/or PDF (static) reports
**Features:**
- Distribution plots with histograms, KDE curves, and rug plots
- Power law analysis with log-log plots
- Weight distribution analysis
- Reciprocity visualization
- Top nodes tables

## Key Findings

### Graph Type
- **Scale-free network** with power-law in-degree distribution (α=1.68, R²=0.89)
- Similar to social networks and web graphs
- ~70% edge reciprocity (bidirectional similarity)

### Degree Patterns
- **Out-degree:** Artificially uniform (Last.fm API returns ~250 for everyone)
- **In-degree:** Natural power law (few artists referenced by thousands)
- High inequality in popularity (Gini=0.67 for in-degree)

### Edge Weights
- Heavily skewed toward weak connections (56% < 0.1)
- Median similarity only 0.077
- Important for weighted pathfinding algorithms

## Upcoming Experiments

### Embedding Quality Metrics
Compare different embedding parameters:
- Random seeds (reproducibility)
- PCA preprocessing (on/off)
- FastRP dimensions (2, 64, 128, 256)
- PaCMAP neighbors (5, 10, 30)

Evaluation metrics:
- Neighborhood preservation (k-NN overlap)
- Distance correlation (graph vs 2D)
- Community structure preservation

## Usage

```bash
cd experiments

uv sync

# Calculate graph metrics
uv run python calculate_graph_metrics.py

# Run embedding experiments (coming soon)
uv run python run_embedding_experiments.py
```

## Results
All results stored in:
- `metrics/` - Graph analysis
- `results/` - Embedding experiments (coming soon)
