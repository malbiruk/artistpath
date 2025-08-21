# ArtistPath 🎵

Find the shortest connection path between any two music artists using Last.fm's related artists data.

## Overview

ArtistPath discovers how artists are connected through their musical similarities, like "Six Degrees of Kevin Bacon" for musicians. It builds a graph of artist relationships and finds the shortest path between any two artists.

## Example

```
$ artistpath "Taylor Swift" "Metallica"

"Taylor Swift" → "Halsey" → "Poppy" → "Slipknot" → "Metallica"

1. "Taylor Swift" - https://www.last.fm/music/Taylor+Swift
2. "Halsey" - https://www.last.fm/music/Halsey
3. "Poppy" - https://www.last.fm/music/Poppy
4. "Slipknot" - https://www.last.fm/music/Slipknot
5. "Metallica" - https://www.last.fm/music/Metallica
```

## Project Structure

```
artistpath/
├── data_collection/    # Python scripts to build the artist graph from Last.fm API
├── artistpath/         # Rust CLI for fast pathfinding queries
└── data/               # Generated graph data (binary format)
```

## Quick Start

### Option 1: Use Pre-built Data (Recommended)

Download the compressed data files from the [latest release](https://github.com/yourusername/artistpath/releases) and extract them to the `data/` directory. This saves several days of API crawling.

```bash
# Download and extract data
wget https://github.com/yourusername/artistpath/releases/latest/download/artistpath-data.tar.zst
tar -xf artistpath-data.tar.zst

# Build and run the CLI
cd artistpath
cargo build --release
./target/release/artistpath "Artist 1" "Artist 2"
```

### Option 2: Collect Your Own Data

If you want to build your own artist graph from scratch:

#### Prerequisites

- Python 3.12+ with [uv](https://github.com/astral-sh/uv)
- Rust 1.70+
- Last.fm API key (get one at https://www.last.fm/api/account/create)

#### 1. Collect Artist Data

```bash
cd data_collection
uv sync
echo "API_KEY=your_lastfm_api_key" > .env
uv run python run_collection.py
```

**Note:** This process can take several days depending on how many artists you want to collect. The collection:
- Starts from a seed artist (default: "Taylor Swift")
- Uses BFS to explore related artists
- Saves data in streaming NDJSON format for memory efficiency
- Supports resuming interrupted collection

#### 2. Post-process Data

```bash
uv run python run_postprocessing.py
```

This converts the NDJSON files to optimized binary formats for faster pathfinding.

#### 3. Find Paths

```bash
cd ../artistpath
cargo build --release
./target/release/artistpath "Artist 1" "Artist 2"
```

## CLI Usage

```bash
# Basic usage
artistpath "Artist 1" "Artist 2"

# Options
--verbose            # Show search statistics
--quiet              # Only show path flow
--show-similarity    # Display similarity scores
--min-match 0.5      # Filter by similarity threshold
--top-related 50     # Limit connections per artist
```

## How It Works

1. **Data Collection**: BFS crawl of Last.fm's similar artists API
2. **Binary Storage**: Optimized format with memory-mapped access
3. **Pathfinding**: BFS or Dijkstra's algorithm for shortest paths

## License

MIT
