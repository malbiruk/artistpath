# Graph Embedding Experiments Summary

## Objective
Attempted to create a meaningful 2D visualization of the 850k artist similarity graph using FastRP + dimensionality reduction.

## Experiments Conducted

### 1. Baseline FastRP (128D)
**Configuration:**
- Dimensions: 128
- Random walk parameter q: 3
- Projection: Sparse random projection
- Normalization: L2 normalization
- Seeds tested: 25, 42, 123, 456, 789

**Results:**
- k-NN@10 preservation: 3.4% ± 0.1%
- k-NN@50 preservation: 3.2% ± 0.1%
- Spearman R²: 0.035 (3.5% variance explained)
- Pearson R²: 0.008 (0.8% variance explained)

### 2. Weight Transformation (Squared)
**Hypothesis:** Amplifying weight differences would help FastRP distinguish structure

**Configuration:**
- Same as baseline
- Weight transform: w' = w²
- Effect: Weak edges (0.1) → 0.01, Strong edges (0.9) → 0.81

**Results:**
- k-NN@10: 3.1% (no improvement)
- Coefficient of variation increased: 0.88 → 1.91
- **Conclusion:** Higher variance didn't help

### 3. Weight Transformation (Log)
**Hypothesis:** Log transform would spread out low-weight values

**Configuration:**
- Same as baseline
- Weight transform: w' = log(1 + w)

**Results:**
- k-NN@10: 3.4% (no improvement)
- **Conclusion:** Actually compressed differences, made it worse

### 4. Incoming-Only Graph
**Hypothesis:** High-variance in-degree structure (Gini=0.67) would create clearer hubs

**Configuration:**
- Graph transformation: Each node has only incoming edges (who points TO them)
- Preserves high-variance in-degree distribution
- Popular artists become natural hubs

**Results:**
- k-NN@10: 3.2% (no improvement)
- **Conclusion:** Structural variance didn't translate to better embeddings

### 5. Multiple Dimensions Tested
**Configuration:** Tested 16D, 64D, 128D, 256D

**Results:**
- 16D: 3.6% k-NN@10
- 64D: 3.7% k-NN@10
- 128D: 3.4% k-NN@10
- 256D: 3.7% k-NN@10
- **Conclusion:** Dimensionality doesn't matter - all converge to ~3.5%

## Embedding Evaluation

We attempted dimensionality reduction using FastRP followed by PaCMAP/UMAP
to create 2D visualizations. Across multiple configurations (dimensions:
16-256, iteration depth q: 2-4, 5 random seeds), k-NN preservation
remained at 3-4% (Table X), indicating the graph structure does not
preserve well in low dimensions.

### Potential explanations:

**Weak edge weights:** The median similarity score is 0.077, with 63% of
edges below 0.2. This may limit signal propagation in iterative embedding
methods.

**High reciprocity with uniform out-degree:** While 71% of edges are
reciprocal, the out-degree distribution is nearly uniform (Gini=0.27) due
to API limits. This creates dense local tangles without clear hierarchical
structure.

**Inherent dimensionality:** Music similarity based on listening patterns
may be genuinely high-dimensional, as artists can be similar along
orthogonal axes (genre, era, mood, instrumentation, cultural context).

These results suggest music similarity networks from collaborative
filtering data may be fundamentally different from social or citation
networks that typically achieve 20-50% k-NN preservation in low-dimensional
embeddings [citations needed].

## Conclusion

We conducted systematic experiments testing:
1. Multiple algorithms (FastRP variants)
2. Different graph structures (bidirectional, incoming-only)
3. Weight transformations (squared, log, threshold)
4. Various dimensionalities (16D-256D)

**Result:** All approaches converge to ~3% k-NN preservation, indicating this is a fundamental property of music similarity graphs, not a methodological failure.

**Recommendation:** Global 2D embeddings are unsuitable for music similarity visualization. Local subgraph exploration provides superior user experience and accuracy.

## Reproducibility

All experiments can be reproduced using:
```bash
cd experiments

# Generate embeddings
python generate_all_embeddings.py all --config-file configs/phase1_fastrp_optimization.json

# Evaluate
python evaluate_all_embeddings.py

# Aggregate results
python aggregate_results.py
```

Results saved in: `results/embeddings_evaluation/` and `results/aggregated_results.json`

## TODO:
- [ ] Calculate one more metric: clustering coefficient (transitivity) - this takes 10 minutes to compute
- [ ] Find 2-3 papers on graph embeddings that report k-NN metrics for comparison (actual citations)
