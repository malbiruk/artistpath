import json
import struct
from pathlib import Path
from uuid import UUID

from rich.progress import track


def convert_to_binary(graph_file: Path | str) -> dict:
    """Convert NDJSON graph to binary format with index for faster loading."""
    graph_path = Path(graph_file)
    binary_path = Path("../data/graph.bin")
    index_path = Path("../data/graph_binary_index.json")

    index = {}
    total_artists = 0
    total_connections = 0

    # Count lines for progress tracking
    with graph_path.open() as f:
        line_count = sum(1 for line in f if line.strip())

    with graph_path.open() as infile, binary_path.open("wb") as outfile:
        position = 0

        for line_ in track(infile, total=line_count, description="[green]Converting to binary..."):
            line = line_.strip()
            if not line:
                continue

            try:
                data = json.loads(line)
                artist_id = UUID(data["id"])
                connections = data["connections"]

                # Store byte position for this artist in index
                index[str(artist_id)] = position

                # Write binary format:
                # - UUID (16 bytes)
                # - Connection count (4 bytes, uint32)
                # - Each connection: UUID (16 bytes) + weight (4 bytes, float32)

                outfile.write(artist_id.bytes)  # 16 bytes
                outfile.write(struct.pack("<I", len(connections)))  # 4 bytes

                for conn_id, weight in connections:
                    outfile.write(UUID(conn_id).bytes)  # 16 bytes
                    outfile.write(struct.pack("<f", weight))  # 4 bytes

                position = outfile.tell()
                total_artists += 1
                total_connections += len(connections)

            except (json.JSONDecodeError, ValueError, KeyError) as e:
                print(f"⚠️  Skipping malformed line: {e}")
                print(f"Line content: {line[:200]!r}...")
                continue

    # Save the index mapping artist UUIDs to file positions
    with index_path.open("w") as f:
        json.dump(index, f, separators=(",", ":"))  # Compact JSON

    return {
        "artists": total_artists,
        "connections": total_connections,
        "binary_size": binary_path.stat().st_size,
        "index_size": index_path.stat().st_size,
        "original_size": graph_path.stat().st_size,
    }


def main() -> None:
    graph_file = Path("../data/graph.ndjson")

    print(f"🔄 Converting {graph_file} to binary format")
    print(f"📏 Input size: {graph_file.stat().st_size / (1024**3):.1f} GB")

    stats = convert_to_binary(graph_file)

    print("\n✅ Conversion complete!")
    print(f"🎵 Artists processed: {stats['artists']:,}")
    print(f"🔗 Total connections: {stats['connections']:,}")
    print(f"📊 Original size: {stats['original_size'] / (1024**2):.1f} MB")
    print(f"💾 Binary size: {stats['binary_size'] / (1024**2):.1f} MB")
    print(f"📇 Index size: {stats['index_size'] / (1024**2):.1f} MB")
    print(f"📦 Total binary: {(stats['binary_size'] + stats['index_size']) / (1024**2):.1f} MB")

    savings = (
        (stats["original_size"] - stats["binary_size"] - stats["index_size"])
        / stats["original_size"]
        * 100
    )
    print(f"💰 Space savings: {savings:.1f}%")
    print("🎉 Done!")


if __name__ == "__main__":
    main()
