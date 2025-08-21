import json
from pathlib import Path

from rich.progress import track


def build_graph_index(graph_file: Path | str) -> dict[str, int]:
    """Build index mapping artist UUID to byte position in graph file."""
    graph_path = Path(graph_file)
    index = {}

    # Get file size for progress tracking
    file_size = graph_path.stat().st_size

    with graph_path.open("rb") as f:  # Binary mode for byte positions
        position = 0
        mb_processed = 0
        total_mb = file_size // (1024 * 1024)

        progress = track(range(total_mb), description="[green]Indexing graph...")

        while True:
            line = f.readline()
            if not line:
                break

            if line.strip():
                try:
                    line_str = line.decode("utf-8")
                    data = json.loads(line_str)
                    artist_id = data.get("id")

                    if artist_id:
                        index[artist_id] = position

                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass  # Skip malformed lines

            position = f.tell()  # Get current byte position

            # Update progress every MB
            new_mb = position // (1024 * 1024)
            while mb_processed < new_mb and mb_processed < total_mb:
                next(progress)
                mb_processed += 1

    return index


def save_index(index: dict[str, int], output_file: Path | str) -> None:
    """Save index to JSON file."""
    with Path(output_file).open("w") as f:
        json.dump(index, f, separators=(",", ":"))  # Compact JSON


def main() -> None:
    graph_file = Path("../data/graph.ndjson")
    index_file = Path("../data/graph_index.json")

    print(f"🔍 Building graph index from {graph_file}")
    print(f"📏 File size: {graph_file.stat().st_size / (1024**3):.1f} GB")

    # Build index
    index = build_graph_index(graph_file)

    print(f"\n✅ Indexed {len(index):,} artists")

    # Save index
    print(f"💾 Saving index to {index_file}")
    save_index(index, index_file)

    index_size_mb = index_file.stat().st_size / (1024**2)
    print(f"📊 Index size: {index_size_mb:.1f} MB")
    print("🎉 Done!")


if __name__ == "__main__":
    main()
