# `artistpath`

Find the shortest connection path between any two music artists using Last.fm's related artists data.

## What is this?

A command-line tool that finds how any two artists are connected through musical similarity. Think of it as exploring the hidden pathways of musical influence and listener behavior across more than 850k artists.

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

## Installation

**With pre-built data** (recommended - saves days of API crawling):
```bash
# Download data from releases (coming soon!)
# For now, you'll need to build your own dataset

# Build and run
cd artistpath
cargo build --release
./target/release/artistpath "Taylor Swift" "Metallica"
```

**Build your own dataset:**
1. Get a [Last.fm API key](https://www.last.fm/api/account/create)
2. `cd data_collection && uv sync && echo "API_KEY=your_key" > .env`
3. `uv run python run_collection.py` (takes several days!)
4. `uv run python run_postprocessing.py`
5. `cd ../artistpath && cargo build --release`

Requires Python 3.12+ with [uv](https://github.com/astral-sh/uv) and Rust 1.70+.

## CLI Usage

```bash
Usage: artistpath [OPTIONS] <ARTIST1> <ARTIST2>

Arguments:
  <ARTIST1>  First artist name
  <ARTIST2>  Second artist name

Options:
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

## Two Algorithms

**BFS (default)** - Finds the shortest path by number of hops:
```
"Taylor Swift" → "Halsey" → "Poppy" → "Slipknot" → "Metallica"
```

**Dijkstra (--weighted)** - Finds the path with best similarity scores:
```
"Taylor Swift" → "Olivia Rodrigo" → "Sabrina Carpenter" → ... → "Metallica"
```
(20 steps but smoother musical transitions)

## Try These Connections

Explore some unexpected musical bridges (use "weighted" option for more gradual transitions):
- Classical to Hip-Hop: `"Johann Sebastian Bach" "Kendrick Lamar"`
- Country to Electronic: `"Johnny Cash" "Aphex Twin"`
- Jazz to Death Metal: `"Miles Davis" "Cannibal Corpse"`
- Folk to Trap: `"Bob Dylan" "Future"`

You'll discover artists you never knew existed, sitting right at the crossroads of different musical worlds.

## How It Works

1. **Data Collection**: BFS crawl of Last.fm's similar artists API (Python)
2. **Binary Storage**: Optimized format with memory-mapped access
3. **Pathfinding**: BFS for shortest path, Dijkstra for best similarity (Rust)

## License

MIT
