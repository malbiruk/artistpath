# %% [markdown]
"""
---
title: Last.fm Artist Similarity Graph Analysis
subtitle: Network Structure and Distribution Analysis
author: Klim Kostiuk
date: 21/09/2025
format:
  html:
    code-fold: true
    code-summary: "Show code"
    toc: true
    toc-depth: 3
    toc-float: true
    number-sections: true
    theme: cosmo
    fig-width: 10
    fig-height: 6
    fig-align: center
  pdf:
    documentclass: article
    geometry: margin=1in
    fig-format: png
    fig-dpi: 300
    toc: true
execute:
  warning: false
  message: false
jupyter: python3
---
"""

# %%
# | label: setup
# | include: false
import gzip
import json
import pickle
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from IPython.display import HTML, display
from plotly.subplots import make_subplots
from scipy.stats import gaussian_kde

from plot_template import setup_custom_template

warnings.filterwarnings("ignore")

setup_custom_template()

# Load data
metrics_path = Path("metrics/graph_metrics.json")
dist_path = Path("metrics/distributions.pkl.gz")
sample_path = Path("metrics/distributions_sample.json")

# Load metrics
with metrics_path.open() as f:
    metrics = json.load(f)

# Load distributions (try pickle first, fall back to JSON)
try:
    with gzip.open(dist_path, "rb") as f:
        distributions = pickle.load(f)
except Exception:
    with sample_path.open() as f:
        distributions = json.load(f)

# Extract data - new structure has everything at top level
dataset_info = metrics.get("dataset_info", {})
basic_metrics = metrics.get("basic_metrics", {})
degree_stats = metrics.get("degree_stats", {})
weight_stats = metrics.get("weight_stats", {})
power_law_fits = metrics.get("power_law_fits", {})

# %% [markdown]
"""
## Executive Summary

This report analyzes the structure of a large-scale music artist similarity graph derived from Last.fm data. The network exhibits scale-free properties with distinct patterns in connectivity and similarity distributions.

## Graph Overview

"""

# %%
# | label: basic-stats
# | fig-cap: "Basic graph statistics"

# Create overview cards
fig = go.Figure()

# Create text annotations for key metrics
annotations = [
    dict(
        text=f"<b>Total Nodes</b><br>{dataset_info['nodes']:,}",
        x=0.2,
        y=0.7,
        xref="paper",
        yref="paper",
        showarrow=False,
        font=dict(size=18),
        align="center",
    ),
    dict(
        text=f"<b>Total Edges</b><br>{dataset_info['edges']:,}",
        x=0.5,
        y=0.7,
        xref="paper",
        yref="paper",
        showarrow=False,
        font=dict(size=18),
        align="center",
    ),
    dict(
        text=f"<b>Source Nodes</b><br>{dataset_info['source_nodes']:,}",
        x=0.8,
        y=0.7,
        xref="paper",
        yref="paper",
        showarrow=False,
        font=dict(size=18),
        align="center",
    ),
    dict(
        text=f"<b>Graph Density</b><br>{basic_metrics['density']:.2e}",
        x=0.2,
        y=0.3,
        xref="paper",
        yref="paper",
        showarrow=False,
        font=dict(size=18),
        align="center",
    ),
    dict(
        text=f"<b>Reciprocity</b><br>{basic_metrics['reciprocity']:.1%}",
        x=0.5,
        y=0.3,
        xref="paper",
        yref="paper",
        showarrow=False,
        font=dict(size=18),
        align="center",
    ),
    dict(
        text=f"<b>Avg Degree</b><br>{degree_stats['out_degree']['mean']:.1f}",
        x=0.8,
        y=0.3,
        xref="paper",
        yref="paper",
        showarrow=False,
        font=dict(size=18),
        align="center",
    ),
]

fig.update_layout(
    annotations=annotations,
    showlegend=False,
    height=300,
    title="Graph Statistics Overview",
    xaxis=dict(visible=False),
    yaxis=dict(visible=False),
)

fig.show()

# %% [markdown]
f"""
The graph contains **{dataset_info["nodes"]:,} nodes** (unique artists) connected by **{dataset_info["edges"]:,} edges** (similarity relationships). With a density of **{basic_metrics["density"]:.2e}**, this is an extremely sparse network, typical of real-world graphs.

## Degree Distributions

### Out-Degree Distribution

The out-degree represents how many similar artists each node references.
"""

# %%
# | label: out-degree-dist
# | fig-cap: "Out-degree distribution with histogram, KDE, and rug plot"

out_degrees = np.array(distributions["out_degrees"])

# Create figure with histogram and KDE
fig = go.Figure()

# Histogram
fig.add_trace(
    go.Histogram(
        x=out_degrees,
        nbinsx=50,
        name="Histogram",
        opacity=0.7,
        histnorm="probability density",
        marker_color="lightseagreen",
    ),
)

# KDE
kde = gaussian_kde(out_degrees, bw_method=0.3)
x_range = np.linspace(out_degrees.min(), out_degrees.max(), 500)
kde_values = kde(x_range)

fig.add_trace(
    go.Scatter(
        x=x_range,
        y=kde_values,
        mode="lines",
        name="KDE",
        line=dict(color="darksalmon", width=3),
    ),
)

# Add rug plot
sample_for_rug = np.random.choice(out_degrees, min(1000, len(out_degrees)), replace=False)
fig.add_trace(
    go.Scatter(
        x=sample_for_rug,
        y=np.zeros_like(sample_for_rug),
        mode="markers",
        name="Data points",
        marker=dict(symbol="line-ns", size=8, color="steelblue", opacity=0.3),
        yaxis="y2",
    ),
)

fig.update_layout(
    title=f"Out-Degree Distribution (μ={degree_stats['out_degree']['mean']:.1f}, σ={degree_stats['out_degree']['std']:.1f})",
    xaxis_title="Out-degree",
    yaxis_title="Density",
    yaxis2=dict(
        overlaying="y",
        side="right",
        range=[-0.01, 0.01],
        showticklabels=False,
        showgrid=False,
    ),
    height=500,
    showlegend=True,
)

# Add statistics annotation
stats_text = f"Mean: {degree_stats['out_degree']['mean']:.1f}<br>"
stats_text += f"Median: {degree_stats['out_degree']['median']:.0f}<br>"
stats_text += f"Std: {degree_stats['out_degree']['std']:.1f}<br>"
stats_text += f"Gini: {degree_stats['out_degree']['gini']:.3f}"

fig.add_annotation(
    text=stats_text,
    xref="paper",
    yref="paper",
    x=0.98,
    y=0.98,
    showarrow=False,
    bgcolor="rgba(255, 255, 255, 0.8)",
    bordercolor="gray",
    borderwidth=1,
    font=dict(size=12),
    align="left",
    xanchor="right",
    yanchor="top",
)

fig.show()

# %% [markdown]
"""
### In-Degree Distribution

The in-degree shows how many times each artist is referenced as similar by others.
"""

# %%
# | label: in-degree-dist
# | fig-cap: "In-degree distribution with histogram, KDE, and rug plot"

in_degrees = np.array(distributions["in_degrees"])

# Create figure
fig = go.Figure()

# Limit display for better visualization (log scale will handle the full range)
in_degrees_clipped = np.clip(in_degrees, 0, 1000)

# Histogram
fig.add_trace(
    go.Histogram(
        x=in_degrees_clipped,
        nbinsx=100,
        name="Histogram",
        opacity=0.7,
        histnorm="probability density",
        marker_color="plum",
    ),
)

# KDE
kde = gaussian_kde(in_degrees_clipped, bw_method=0.3)
x_range = np.linspace(in_degrees_clipped.min(), in_degrees_clipped.max(), 500)
kde_values = kde(x_range)

fig.add_trace(
    go.Scatter(
        x=x_range,
        y=kde_values,
        mode="lines",
        name="KDE",
        line=dict(color="lightcoral", width=3),
    ),
)

# Add rug plot
sample_for_rug = np.random.choice(
    in_degrees_clipped,
    min(1000, len(in_degrees_clipped)),
    replace=False,
)
fig.add_trace(
    go.Scatter(
        x=sample_for_rug,
        y=np.zeros_like(sample_for_rug),
        mode="markers",
        name="Data points",
        marker=dict(symbol="line-ns", size=8, color="darkseagreen", opacity=0.3),
        yaxis="y2",
    ),
)

fig.update_layout(
    title=f"In-Degree Distribution (μ={degree_stats['in_degree']['mean']:.1f}, σ={degree_stats['in_degree']['std']:.1f})",
    xaxis_title="In-degree (clipped at 1000 for visualization)",
    yaxis_title="Density",
    yaxis2=dict(
        overlaying="y",
        side="right",
        range=[-0.001, 0.001],
        showticklabels=False,
        showgrid=False,
    ),
    height=500,
    showlegend=True,
)

# Add statistics
stats_text = f"Mean: {degree_stats['in_degree']['mean']:.1f}<br>"
stats_text += f"Median: {degree_stats['in_degree']['median']:.0f}<br>"
stats_text += f"Max: {degree_stats['in_degree']['max']:,}<br>"
stats_text += f"Gini: {degree_stats['in_degree']['gini']:.3f}"

fig.add_annotation(
    text=stats_text,
    xref="paper",
    yref="paper",
    x=0.98,
    y=0.98,
    showarrow=False,
    bgcolor="rgba(255, 255, 255, 0.8)",
    bordercolor="gray",
    borderwidth=1,
    font=dict(size=12),
    align="left",
    xanchor="right",
    yanchor="top",
)

fig.show()

# %% [markdown]
"""
## Power Law Analysis

Scale-free networks follow a power law distribution: P(k) ~ k^(-α)
"""

# %%
# | label: power-law-fits
# | fig-cap: "Power law fits for degree distributions (log-log scale)"

# Create subplots
fig = make_subplots(
    rows=1,
    cols=2,
    subplot_titles=("Out-Degree Power Law", "In-Degree Power Law"),
    horizontal_spacing=0.12,
)

# Out-degree power law
if "out_degree_fit" in power_law_fits:
    fit = power_law_fits["out_degree_fit"]

    # Calculate degree distribution from samples
    out_degrees = np.array(distributions["out_degrees"])
    unique_out, counts_out = np.unique(out_degrees[out_degrees > 0], return_counts=True)

    # Limit points for visualization
    if len(unique_out) > 100:
        indices = np.linspace(0, len(unique_out) - 1, 100, dtype=int)
        unique_out = unique_out[indices]
        counts_out = counts_out[indices]

    # Scatter plot of actual data
    fig.add_trace(
        go.Scatter(
            x=unique_out,
            y=counts_out,
            mode="markers",
            name="Actual",
            marker=dict(color="lightseagreen", size=8, opacity=0.6),
        ),
        row=1,
        col=1,
    )

    # Fitted line using the fit parameters
    x_fit = np.logspace(np.log10(fit["fit_range"][0]), np.log10(fit["fit_range"][1]), 100)
    y_fit = 10 ** (fit["intercept"]) * x_fit ** (-fit["alpha"])

    fig.add_trace(
        go.Scatter(
            x=x_fit,
            y=y_fit,
            mode="lines",
            name=f"Fit (α={fit['alpha']:.3f})",
            line=dict(color="red", width=2, dash="dash"),
        ),
        row=1,
        col=1,
    )

    # Add R² annotation
    fig.add_annotation(
        text=f"R² = {fit['r_squared']:.4f}",
        xref="x",
        yref="y",
        x=fit["fit_range"][1] * 0.1,
        y=counts_out.max() * 0.1 if len(counts_out) > 0 else 1,
        showarrow=False,
        bgcolor="white",
        row=1,
        col=1,
    )

# In-degree power law
if "in_degree_fit" in power_law_fits:
    fit = power_law_fits["in_degree_fit"]

    # Calculate degree distribution from samples
    in_degrees = np.array(distributions["in_degrees"])
    unique_in, counts_in = np.unique(in_degrees[in_degrees > 0], return_counts=True)

    # Limit points for visualization
    if len(unique_in) > 100:
        indices = np.linspace(0, len(unique_in) - 1, 100, dtype=int)
        unique_in = unique_in[indices]
        counts_in = counts_in[indices]

    # Scatter plot
    fig.add_trace(
        go.Scatter(
            x=unique_in,
            y=counts_in,
            mode="markers",
            name="Actual",
            marker=dict(color="plum", size=8, opacity=0.6),
            showlegend=False,
        ),
        row=1,
        col=2,
    )

    # Fitted line using the fit parameters
    x_fit = np.logspace(np.log10(fit["fit_range"][0]), np.log10(fit["fit_range"][1]), 100)
    y_fit = 10 ** (fit["intercept"]) * x_fit ** (-fit["alpha"])

    fig.add_trace(
        go.Scatter(
            x=x_fit,
            y=y_fit,
            mode="lines",
            name=f"Fit (α={fit['alpha']:.3f})",
            line=dict(color="red", width=2, dash="dash"),
            showlegend=False,
        ),
        row=1,
        col=2,
    )

    # Add R² annotation
    fig.add_annotation(
        text=f"R² = {fit['r_squared']:.4f}",
        xref="x2",
        yref="y2",
        x=fit["fit_range"][1] * 0.1,
        y=counts_in.max() * 0.1 if len(counts_in) > 0 else 1,
        showarrow=False,
        bgcolor="white",
        row=1,
        col=2,
    )

# Update axes to log scale
fig.update_xaxes(type="log", title="Degree (k)", row=1, col=1)
fig.update_xaxes(type="log", title="Degree (k)", row=1, col=2)
fig.update_yaxes(type="log", title="Frequency P(k)", row=1, col=1)
fig.update_yaxes(type="log", title="Frequency P(k)", row=1, col=2)

fig.update_layout(height=500, title_text="Power Law Distribution Analysis", showlegend=True)

fig.show()

# %% [markdown]
"""
## Edge Weight Distribution
"""

# %%
# | label: weight-dist
# | fig-cap: "Distribution of edge weights (similarity scores)"

weights = np.array(distributions["weights"])

# Create figure
fig = go.Figure()

# Histogram
fig.add_trace(
    go.Histogram(
        x=weights,
        nbinsx=100,
        name="Histogram",
        opacity=0.7,
        histnorm="probability density",
        marker_color="skyblue",
    ),
)

# KDE
kde = gaussian_kde(weights, bw_method=0.1)
x_range = np.linspace(0, 1, 500)
kde_values = kde(x_range)

fig.add_trace(
    go.Scatter(
        x=x_range,
        y=kde_values,
        mode="lines",
        name="KDE",
        line=dict(color="darkgray", width=3),
    ),
)

# Add rug plot
sample_for_rug = np.random.choice(weights, min(1000, len(weights)), replace=False)
fig.add_trace(
    go.Scatter(
        x=sample_for_rug,
        y=np.zeros_like(sample_for_rug),
        mode="markers",
        name="Data points",
        marker=dict(symbol="line-ns", size=8, color="mediumturquoise", opacity=0.3),
        yaxis="y2",
    ),
)

# Add quartile lines
quartiles = [0.25, 0.5, 0.75]
colors = ["green", "orange", "red"]
for q, color in zip(quartiles, colors):
    q_value = np.percentile(weights, q * 100)
    fig.add_vline(
        x=q_value,
        line_dash="dot",
        line_color=color,
        annotation_text=f"Q{int(q * 100)}: {q_value:.3f}",
        annotation_position="top",
    )

fig.update_layout(
    title=f"Edge Weight Distribution (n={len(weights):,} sampled edges)",
    xaxis_title="Weight (Similarity Score)",
    yaxis_title="Density",
    yaxis2=dict(
        overlaying="y",
        side="right",
        range=[-0.5, 0.5],
        showticklabels=False,
        showgrid=False,
    ),
    height=500,
    showlegend=True,
)

# Add statistics
stats_text = f"Mean: {weight_stats['mean']:.3f}<br>"
stats_text += f"Median: {weight_stats['median']:.3f}<br>"
stats_text += f"Std: {weight_stats['std']:.3f}<br>"
stats_text += f"Range: [{weight_stats['min']:.4f}, {weight_stats['max']:.3f}]"

fig.add_annotation(
    text=stats_text,
    xref="paper",
    yref="paper",
    x=0.98,
    y=0.98,
    showarrow=False,
    bgcolor="rgba(255, 255, 255, 0.8)",
    bordercolor="gray",
    borderwidth=1,
    font=dict(size=12),
    align="left",
    xanchor="right",
    yanchor="top",
)

fig.show()

# %% [markdown]
"""
## Reciprocity Analysis
"""

# %%
# | label: reciprocity-viz
# | fig-cap: "Edge reciprocity in the graph"

# Create pie chart for reciprocity
# Calculate from percentage
reciprocity_rate = basic_metrics["reciprocity"]
total_edges = dataset_info["edges"]
reciprocal_edges = int(total_edges * reciprocity_rate)
non_reciprocal = total_edges - reciprocal_edges

fig = go.Figure(
    data=[
        go.Pie(
            labels=["Reciprocal Edges", "Non-reciprocal Edges"],
            values=[reciprocal_edges, non_reciprocal],
            hole=0.3,
            marker_colors=["lightcoral", "lightsteelblue"],
            textinfo="label+percent",
            textposition="auto",
        ),
    ],
)

fig.update_layout(
    title=f"Edge Reciprocity: {basic_metrics['reciprocity']:.1%} of edges are bidirectional",
    height=400,
    annotations=[
        dict(
            text=f"{basic_metrics['reciprocity']:.1%}<br>Reciprocal",
            x=0.5,
            y=0.5,
            font_size=20,
            showarrow=False,
        ),
    ],
)

fig.show()

# %% [markdown]
"""
## Top Connected Artists
"""

# %%
# | label: top-nodes-table
# | tbl-cap: "Most connected artists in the network"

# Create DataFrame for top nodes
top_in = pd.DataFrame(
    metrics["top_nodes"]["top_by_in_degree"][:10],
    columns=["Artist", "In-Degree"],
)
top_out = pd.DataFrame(
    metrics["top_nodes"]["top_by_out_degree"][:10],
    columns=["Artist", "Out-Degree"],
)

# Create side-by-side display
html = f"""
<div style="display: flex; justify-content: space-around;">
    <div style="width: 45%;">
        <h4>Top by In-Degree (Most Referenced)</h4>
        {top_in.to_html(index=False)}
    </div>
    <div style="width: 45%;">
        <h4>Top by Out-Degree (Most Connections Listed)</h4>
        {top_out.to_html(index=False)}
    </div>
</div>
"""

display(HTML(html))

# %% [markdown]
f"""
## Key Insights

### Network Type
- **Scale-free network** with power-law in-degree distribution (α = {power_law_fits.get("in_degree_fit", {}).get("alpha", 0):.2f})
- High **reciprocity** ({basic_metrics["reciprocity"]:.1%}) indicating symmetric similarity relationships
- **Extremely sparse** (density = {basic_metrics["density"]:.2e}) yet well-connected

### Degree Patterns
- **Out-degree**: Artificially uniform distribution due to API limits (max 250)
- **In-degree**: Natural power-law distribution with high inequality (Gini = {degree_stats["in_degree"]["gini"]:.3f})
- A few "supernode" artists are referenced by thousands of others

### Weight Distribution
- Heavily skewed toward weak connections (median = {weight_stats["median"]:.3f})
- Most similarities are weak, suggesting the importance of thresholding in applications

## Methodology

Data collected from Last.fm API for {dataset_info["nodes"]:,} artists. Analysis performed using streaming algorithms to handle the large graph size with memory constraints. Distributions sampled at 10% for weight analysis.
"""
