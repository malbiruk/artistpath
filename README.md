# ArtistPath 🎵

Find the shortest connection path between any two music artists using Last.fm's related artists data.

## Overview

ArtistPath discovers how artists are connected through their musical similarities, like "Six Degrees of Kevin Bacon" for musicians. It builds a graph of artist relationships and finds the shortest path between any two artists.

## Example

```
Taylor Swift → Ed Sheeran → Eminem → Dr. Dre → Snoop Dogg
```

## Project Structure

```
artistpath/
├── data-collection/    # Python scripts to build the artist graph from Last.fm API
├── cli/                # Rust CLI for fast pathfinding queries
└── data/               # Generated graph data (NDJSON format)
```

## Quick Start

### 1. Collect Artist Data

```bash
cd data-collection
uv sync
echo "API_KEY=your_lastfm_api_key" > .env
uv run python main.py
```

This builds a graph of artist connections by crawling Last.fm's similar artists data.

### 2. Find Paths (Coming Soon)

```bash
cd cli
cargo run -- "Taylor Swift" "Metallica"
```

## How It Works

1. **Data Collection**: Starting from a seed artist, the collector uses BFS to explore related artists through Last.fm's API, building a directed graph with similarity scores

2. **Graph Storage**: Artist connections are stored in NDJSON format for efficient streaming and minimal memory usage

3. **Pathfinding**: The CLI loads the graph and uses Dijkstra's algorithm to find the shortest path between any two artists

## Features

- Memory-efficient streaming data collection (~3GB RAM for millions of artists)
- Resume capability for interrupted collection
- Fast pathfinding with Rust CLI
- Support for genre/tag connections as bridge nodes

## Requirements

- Python 3.12+ with [uv](https://github.com/astral-sh/uv)
- Rust 1.70+
- Last.fm API key

## License

MIT
