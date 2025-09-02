# `artistpath`

Explore music artist networks and discover connections using Last.fm's related artists data.

## What is this?

An interactive web application for exploring artist networks and finding paths between artists. Visualize how artists are connected through musical similarity and discover related artists around any musician or along connection paths. Available as both a web interface and command-line tool covering more than 850k artists.

<img width="1920" height="1058" alt="image" src="https://github.com/user-attachments/assets/1d8deea9-946f-47cf-bd6e-af5341e7e4a5" />


## How connections work

Artist connections are based on Last.fm listener overlap — artists are similar if people listen to them together. The graph is directional, meaning that swapping artists gives different results since unpopular artists are often similar to popular ones, but not necessarily the other way around.

## Web Interface

The interactive web interface provides visual exploration and pathfinding with real-time network visualization.

### Features
- **Artist Exploration**: Enter one artist to explore their network of similar artists
- **Path Finding**: Enter two artists to find connection paths between them
- **Visual Network**: Interactive graph showing artists as nodes and similarities as edges
- **Real-time Search**: Instant results as you type and adjust parameters

### Settings
- **Algorithm**: Toggle between "simple" (BFS) and "weighted" (Dijkstra)
- **Max Relations**: Limit connections per artist (1-250)
- **Min Similarity**: Filter weak connections (0.0-1.0)
- **Max Artists**: Budget limit for exploration/pathfinding (10-500)

### Visual Features
- **Blue highlighting**: Selected path/explored artist is highlighted in blue
- **Animated connections**: Hover/tap on nodes or edges to see running ant animations showing connection direction
- **Bidirectional indicators**: When connections exist in both directions, animations overlap creating a "blinking" effect, and the maximum similarity is displayed
- **Dynamic layout**: Stronger connections (higher similarity) appear shorter and more rigid in the network
- **Adaptive text size**: Artist font size reflects their local importance (connection count relative to the current network)

### Algorithms
- **Simple (BFS)**: Wide layer-by-layer exploration, discovers diverse/distant clusters
- **Weighted (Dijkstra)**: Similarity-based exploration, finds tightly connected clusters and smoother musical transitions

## Artist Discovery

Ever wondered how indie folk connects to experimental electronic music? Or what bridges classic rock and modern trap? `artistpath` reveals these hidden connections and helps you discover new artists along unexpected musical journeys.

Try exploring paths between artists from completely different genres — you might find amazing artists you've never heard of sitting right in the middle, acting as musical bridges between worlds.

## The Story

One summer Sunday in Tbilisi, after band rehearsal, my drummer and I went to a small park with some beers and started sharing music from our phones — you know how it is, one artist leads to another, exploring new sounds together.

That's when it hit me: Spotify shows similar artists, so wouldn't it be cool to build a program that finds the shortest path between any two artists through these musical connections?

I googled around and couldn't find anything like this, so I decided to build it myself. Started with Spotify, but of course they deprecated their similar artists API right when I needed it 🙄

So I switched to Last.fm instead — actually turned out better since they have up to 250 similar artists per artist (compared to Spotify's 80) plus similarity scores, and many users scrobble there their data from Spotify anyway.

The data collection took a couple of days because of API rate limits, ended up with 5.5GB of data and **850,658 unique artists**.

Coming from a Python background but wanting to learn Rust, I thought this would be perfect for experimenting with both — Python for data collection, Rust for the actual pathfinding. I even use a Rust function from within Python even though it's totally unnecessary, just because I could 😄

For performance, I couldn't load the whole graph into RAM, so I skipped the fancy graph libraries and implemented BFS and Dijkstra manually with binary files and memory mapping. Now most searches run in under a second!

*I'm a musician myself — check out [flowersinyoureyes.com](https://flowersinyoureyes.com) if you're curious about my band "flowers in your eyes".*

## Installation

### Standalone CLI Tool

```bash
cargo install artistpath
```

The CLI binary installs to `~/.cargo/bin/` and automatically downloads dataset to `~/.artistpath/` on first run.

### Web Interface (Development)

For running the web interface locally:

```bash
git clone https://github.com/malbiruk/artistpath
cd artistpath

# Download and extract binary data (required for web app)
wget https://github.com/malbiruk/artistpath/releases/download/data-v1.0.0/artistpath-data-850k-binary.tar.zst
tar -I zstd -xvf artistpath-data-850k-binary.tar.zst -C data/

# Setup environment
cp .env.example .env
# Edit .env and add your Last.fm API key (for fetching artist cards)
# Put `const API_BASE_URL = "http://localhost:3050/api";` in web/frontend/src/config.js

# Start backend
cd web/backend
cargo run --release

# Start frontend (new terminal)
cd web/frontend
npm install
npm run dev
```

Open http://localhost:3001 in your browser.

### Dataset Information

**Current dataset**: 850k+ artists with MusicBrainz IDs and similarity connections

Available formats from [releases](https://github.com/malbiruk/artistpath/releases/):
- **Binary format** (1.0GB compressed → 2.4GB extracted): Required for web/CLI apps - includes indexing and name lookup for fast performance
- **NDJSON format** (1.2GB compressed → 6GB extracted): For research/analysis - human-readable JSON lines:
  - Graph: `{"id": uuid, "connections": [[uuid, similarity], ...]}`
  - Metadata: `{"id": uuid, "name": "Artist Name", "url": "..."}`

Requires `zstd` for decompression (`apt install zstd` or `brew install zstd`).

### Build Your Own Dataset

1. Get a [Last.fm API key](https://www.last.fm/api/account/create)
2. `cd data_collection && uv sync && echo "API_KEY=your_key" > .env`
3. `uv run python run_collection.py` (takes several days!)
4. `uv run python run_postprocessing.py`
5. Build CLI: `cd cli && cargo build --release`

Requires Python 3.12+ with [uv](https://github.com/astral-sh/uv) and Rust 1.70+.

## Command Line Usage

The CLI version focuses on pathfinding between two specific artists.

```
Usage: artistpath [OPTIONS] <ARTIST1> <ARTIST2>

Arguments:
  <ARTIST1>  First artist name
  <ARTIST2>  Second artist name

Options:
      --data-path <PATH>        Path to data directory (defaults to ~/.artistpath/, auto-downloads if not found)
  -m, --min-match <SIMILARITY>  Only use connections with similarity >= threshold (0.0-1.0) [default: 0.0]
  -t, --top-related <COUNT>     Limit to top N connections per artist [default: 80]
  -w, --weighted                Use weighted pathfinding for best similarity (default: shortest path)
  -u, --hide-urls               Hide artist URLs from output (URLs shown by default)
  -i, --show-ids                Show artist UUIDs in output
  -s, --show-similarity         Show similarity scores between connected artists
      --no-color                Disable colored output
  -v, --verbose                 Verbose mode - show search info and statistics
  -q, --quiet                   Quiet mode - only show the path flow
      --json                    Output as JSON format
  -h, --help                    Print help
```

### Example

```
$ artistpath "Taylor Swift" "Metallica"

"Taylor Swift" → "Halsey" → "Poppy" → "Slipknot" → "Metallica"

1. "Taylor Swift" - https://www.last.fm/music/Taylor+Swift
2. "Halsey" - https://www.last.fm/music/Halsey
3. "Poppy" - https://www.last.fm/music/Poppy
4. "Slipknot" - https://www.last.fm/music/Slipknot
5. "Metallica" - https://www.last.fm/music/Metallica
```

### Try These Connections

Explore some unexpected musical bridges (use `weighted` algorithm for more gradual transitions):
- Classical to Hip-Hop: `"Johann Sebastian Bach" "Kendrick Lamar"`
- Country to Electronic: `"Johnny Cash" "Aphex Twin"`
- Jazz to Death Metal: `"Miles Davis" "Cannibal Corpse"`
- Folk to Trap: `"Bob Dylan" "Future"`

You'll discover artists you never knew existed, sitting right at the crossroads of different musical worlds.

## How It Works

1. **Data Collection**: BFS crawl of Last.fm's similar artists API (Python)
2. **Binary Storage**: Optimized format with memory-mapped access
3. **Pathfinding**: BFS for shortest path, Dijkstra for best similarity (Rust)

## Support

If you find this project useful and want to support its development:

[![Support on Boosty](https://img.shields.io/badge/Support%20on-Boosty-orange)](https://boosty.to/klimkostiuk/donate)

## License

MIT
