# %% [markdown]
"""
---
title: Last.fm Artist Similarity Graph Analysis
subtitle: Network Structure and Distribution Analysis
author: Klim Kostiuk
date: 09/23/2025
format:
  html:
    code-fold: true
    self-contained: true
jupyter: python3
---

<style>
#tbl-network-metrics caption,
.quarto-figure-center > figcaption,
.table caption {
  text-align: left;
}
</style>
"""

# %%
# | label: setup
import gzip
import json
import pickle
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from IPython.display import HTML, Markdown, display
from plotly.subplots import make_subplots
from scipy.stats import gaussian_kde

from plot_template import setup_custom_template

warnings.filterwarnings("ignore")

setup_custom_template()

# Load data
METRICS_PATH = Path("metrics/graph_metrics.json")
DIST_PATH = Path("metrics/graph_distributions.pkl.gz")
SAMPLE_PATH = Path("metrics/graph_distributions_sample.json")

# Load metrics
with METRICS_PATH.open() as f:
    metrics = json.load(f)

# Load distributions (try pickle first, fall back to JSON)
try:
    with gzip.open(DIST_PATH, "rb") as f:
        distributions = pickle.load(f)
except Exception:
    with SAMPLE_PATH.open() as f:
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
# | tbl-cap: "Basic graph statistics"

# Create DataFrame for basic statistics
stats_data = {
    "Metric": [
        "Total Nodes",
        "Total Edges",
        "Source Nodes",
        "Graph Density",
        "Reciprocity",
        "Average Degree",
    ],
    "Value": [
        f"{dataset_info['nodes']:,}",
        f"{dataset_info['edges']:,}",
        f"{dataset_info['source_nodes']:,}",
        f"{basic_metrics['density']:.2e}",
        f"{basic_metrics['reciprocity']:.1%}",
        f"{degree_stats['out_degree']['mean']:.1f}",
    ],
}

stats_df = pd.DataFrame(stats_data)
display(HTML(stats_df.to_html(index=False)))

# %% [markdown]
"""
This is an extremely sparse network, typical of real-world graphs.

## Degree Distributions

### Out-Degree Distribution

The out-degree represents how many similar artists each node references.
"""

# %%
# | label: out-degree-dist

out_degrees = np.array(distributions["out_degrees"])

# Create figure with histogram and KDE
fig = go.Figure()

# Histogram
fig.add_trace(
    go.Histogram(
        x=out_degrees,
        nbinsx=50,
        name="Histogram",
        opacity=0.5,
        histnorm="probability density",
        marker_color="lightseagreen",
    ),
)

# KDE
kde = gaussian_kde(out_degrees, bw_method=0.1)
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

fig.update_layout(
    xaxis_title="Out-degree",
    yaxis_title="Density",
    height=500,
    showlegend=False,
    yaxis=dict(range=[0, None]),
    margin=dict(t=30),
)


# Add statistics
stats_text = f"Mean: {degree_stats['out_degree']['mean']:.1f}<br>"
stats_text += f"Median: {degree_stats['out_degree']['median']:.0f}<br>"
stats_text += f"Min: {degree_stats['out_degree']['min']:.0f}<br>"
stats_text += f"Max: {degree_stats['out_degree']['max']:,}<br>"
stats_text += f"Gini: {degree_stats['out_degree']['gini']:.3f}"

fig.add_annotation(
    text=stats_text,
    xref="paper",
    yref="paper",
    x=1.1,
    y=1,
    showarrow=False,
    font=dict(size=12),
    align="right",
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

in_degrees = np.array(distributions["in_degrees"])

# Create figure
fig = go.Figure()

# Histogram
fig.add_trace(
    go.Histogram(
        x=in_degrees,
        nbinsx=100,
        name="Histogram",
        opacity=0.5,
        histnorm="probability density",
        marker_color="plum",
    ),
)

# KDE
kde = gaussian_kde(in_degrees, bw_method=0.1)
x_range = np.linspace(in_degrees.min(), in_degrees.max(), 500)
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

fig.update_layout(
    xaxis_title="In-degree",
    yaxis_title="Density",
    height=500,
    showlegend=False,
    yaxis=dict(range=[0, None]),
    margin=dict(t=30),
)

# Add statistics
stats_text = f"Mean: {degree_stats['in_degree']['mean']:.1f}<br>"
stats_text += f"Median: {degree_stats['in_degree']['median']:.0f}<br>"
stats_text += f"Min: {degree_stats['in_degree']['min']:,}<br>"
stats_text += f"Max: {degree_stats['in_degree']['max']:,}<br>"
stats_text += f"Gini: {degree_stats['in_degree']['gini']:.3f}"

fig.add_annotation(
    text=stats_text,
    xref="paper",
    yref="paper",
    x=1.1,
    y=1,
    showarrow=False,
    font=dict(size=12),
    align="right",
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

# Create subplots
fig = make_subplots(
    rows=1,
    cols=2,
    subplot_titles=("Out-Degree Power Law", "In-Degree Power Law"),
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
            marker=dict(color="lightseagreen", size=8, opacity=0.5),
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
            line=dict(color="darksalmon", width=3, dash="dash"),
        ),
        row=1,
        col=1,
    )

    # Add annotations
    annotation_text = f"R² = {fit['r_squared']:.4f}<br>"
    annotation_text += f"α = {fit['alpha']:.4f}"

    fig.add_annotation(
        text=annotation_text,
        xref="x domain",
        yref="y domain",
        x=0.3,
        y=0.98,
        bgcolor="#fafafa",
        showarrow=False,
        xanchor="right",
        yanchor="top",
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
            marker=dict(color="plum", size=8, opacity=0.5),
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
            line=dict(color="darksalmon", width=3, dash="dash"),
            showlegend=False,
        ),
        row=1,
        col=2,
    )

    # Add annotations
    annotation_text = f"R² = {fit['r_squared']:.4f}<br>"
    annotation_text += f"α = {fit['alpha']:.4f}"

    fig.add_annotation(
        text=annotation_text,
        xref="x2 domain",
        yref="y2 domain",
        x=0.3,
        y=0.98,
        showarrow=False,
        bgcolor="#fafafa",
        xanchor="right",
        yanchor="top",
    )

# Update axes to log scale
fig.update_xaxes(type="log", title="Degree (k)", row=1, col=1)
fig.update_xaxes(type="log", title="Degree (k)", row=1, col=2)
fig.update_yaxes(type="log", title="Frequency P(k)", row=1, col=1)
fig.update_yaxes(type="log", title="Frequency P(k)", row=1, col=2)

fig.update_layout(height=500, showlegend=False, margin=dict(t=40))

fig.show()

# %% [markdown]
"""
## Edge Weight Distribution
"""

# %%
# | label: weight-dist

weights = np.array(distributions["weights"])

# Create figure
fig = go.Figure()

# Histogram
fig.add_trace(
    go.Histogram(
        x=weights,
        nbinsx=100,
        name="Histogram",
        opacity=0.5,
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
        line=dict(color="darksalmon", width=3),
    ),
)

fig.update_layout(
    xaxis_title="Similarity Score (1 - Weight)",
    yaxis_title="Density",
    height=500,
    showlegend=False,
    yaxis=dict(range=[0, None]),
    margin=dict(t=30),
)

# Add statistics
stats_text = f"Mean: {weight_stats['mean']:.3f}<br>"
stats_text += f"Median: {weight_stats['median']:.3f}<br>"
stats_text += f"Std: {weight_stats['std']:.3f}<br>"
stats_text += f"Min: {weight_stats['min']:.4f}<br>"
stats_text += f"Max: {weight_stats['max']:.4f}<br>"


fig.add_annotation(
    text=stats_text,
    xref="paper",
    yref="paper",
    x=1.1,
    y=1,
    showarrow=False,
    font=dict(size=12),
    align="right",
    xanchor="right",
    yanchor="top",
)

fig.show()


# %% [markdown]
"""
## Top Connected Artists
"""

# %%
# | label: top-nodes-table

# Create DataFrame for top nodes
top_in = pd.DataFrame(
    metrics["top_nodes"]["top_by_in_degree"][1:11],
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
        <p style="font-size: .9rem; color: #5a6570; padding-top: .5rem; margin-bottom: -.2rem;">Top by In-Degree (Most Referenced)</p>
        {top_in.to_html(index=False)}
    </div>
    <div style="width: 45%;">
        <p style="font-size: .9rem; color: #5a6570; padding-top: .5rem; margin-bottom: -.2rem;">Top by Out-Degree (Most Connections Listed)</p>
        {top_out.to_html(index=False)}
    </div>
</div>
"""

display(HTML(html))

# %%
# | label: key-insights
# | echo: false

display(
    Markdown(f"""
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
"""),
)
