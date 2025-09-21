# Data Collection Pipeline

Scripts for collecting and processing Last.fm artist similarity data.

## Scripts

### 1. `run_collection.py`
**Purpose:** Collects artist similarity data from Last.fm API
**Output:**
- `graph.ndjson` - Artist connections (ID → list of similar artists with weights)
- `metadata.ndjson` - Artist names and URLs
- `collection_state.json` - Resume checkpoint

**Requirements:**
- Last.fm API key in `.env` file
- ~6GB disk space

### 2. `run_postprocessing.py`
**Purpose:** Converts NDJSON to binary format for fast loading
**Output:**
- `graph.bin` - Forward graph (who points to whom)
- `rev-graph.bin` - Reverse graph (who is pointed to by whom)
- `metadata.bin` - Unified lookup + metadata + indexes

**Space savings:** ~60% compression vs NDJSON

### 3. `run_embedding.py`
**Purpose:** Generate graph embeddings for visualization
**Method:**
1. FastRP (128D) - Graph structure embedding using random projections
2. PCA - Dimensionality reduction to optimal dims (preserving 90% variance)
3. PaCMAP (2D) - Final reduction for visualization

**Output:**
- `embeddings_128d_fastrp_chunked.npz` - High-dimensional embeddings
- `embeddings_2d_fastrp_chunked.ndjson` - 2D coordinates (human-readable)
- `embeddings_2d_fastrp_chunked.bin` - 2D coordinates (binary format)

**Memory:** Uses chunked processing + memory mapping for 16GB RAM constraint

## Typical Workflow

```bash
# 1. Set up environment
cd data_collection
uv sync
echo "API_KEY=your_lastfm_key" > .env

# 2. Collect data (takes days)
uv run python run_collection.py

# 3. Convert to binary (15 min)
uv run python run_postprocessing.py

# 4. Generate embeddings (30 min)
uv run python run_embedding.py
```

## Data Format

**graph.ndjson:**
```json
{"id": "uuid", "connections": [["uuid", 0.95], ["uuid", 0.87], ...]}
```

**metadata.ndjson:**
```json
{"id": "uuid", "name": "Artist Name", "url": "https://last.fm/..."}
```

**embeddings_2d.ndjson:**
```json
{"id": "uuid", "x": -12.34, "y": 56.78}
```
