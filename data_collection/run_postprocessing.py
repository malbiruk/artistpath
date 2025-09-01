import json
import struct
from pathlib import Path
from uuid import UUID

from normalization import clean_str
from rich.progress import track


def convert_graph_to_binary(graph_file: Path | str) -> dict:
    """Convert NDJSON graph to binary format with index for faster loading."""
    graph_path = Path(graph_file)
    binary_path = Path("../data/graph.bin")

    index = {}
    total_artists = 0
    total_connections = 0

    # Count lines for progress tracking
    with graph_path.open() as f:
        line_count = sum(1 for line in f if line.strip())

    with graph_path.open() as infile, binary_path.open("wb") as outfile:
        position = 0

        for line_ in track(
            infile,
            total=line_count,
            description="[green]Converting graph to binary...",
        ):
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
                continue

    return {
        "artists": total_artists,
        "connections": total_connections,
        "binary_size": binary_path.stat().st_size,
        "index": index,
    }


def build_lookup(metadata_file: Path | str) -> dict:
    """Build clean name lookup dictionary from NDJSON metadata file."""
    metadata_path = Path(metadata_file)
    lookup = {}

    with metadata_path.open() as f:
        # Get total for progress bar
        total = sum(1 for _ in f)
        f.seek(0)

        # Process with progress bar
        for line in track(f, description="[green]Building lookup...", total=total):
            if not line.strip():
                continue

            entry = json.loads(line)
            mbid = entry["id"]
            name = entry["name"]

            # Build clean name lookup - store lists of artists
            clean_name = clean_str(name)
            if clean_name not in lookup:
                lookup[clean_name] = []
            lookup[clean_name].append(mbid)

    return lookup


def create_unified_metadata_binary(metadata_file: Path | str, lookup: dict, index: dict) -> dict:
    """Create a single binary file with lookup, metadata, and index."""
    metadata_path = Path(metadata_file)
    binary_path = Path("../data/metadata.bin")

    # Parse metadata into memory first
    metadata = {}
    with metadata_path.open() as f:
        total = sum(1 for _ in f)
        f.seek(0)

        for line in track(f, description="[green]Loading metadata...", total=total):
            if not line.strip():
                continue
            entry = json.loads(line)
            metadata[entry["id"]] = {"name": entry["name"], "url": entry["url"]}

    with binary_path.open("wb") as f:
        # Header: 3 uint32 values for section offsets
        header_pos = f.tell()
        f.write(struct.pack("<III", 0, 0, 0))  # Placeholders for section offsets

        # Section 1: Lookup (clean_name -> list of UUIDs)
        lookup_offset = f.tell()
        f.write(struct.pack("<I", len(lookup)))  # Number of entries

        for clean_name, uuid_list in track(lookup.items(), description="[green]Writing lookup..."):
            name_bytes = clean_name.encode("utf-8")
            f.write(struct.pack("<H", len(name_bytes)))  # Name length (2 bytes)
            f.write(name_bytes)  # Name
            f.write(struct.pack("<H", len(uuid_list)))  # Number of UUIDs (2 bytes)
            for uuid_str in uuid_list:
                f.write(UUID(uuid_str).bytes)  # UUID (16 bytes)

        # Section 2: Metadata (UUID -> name + url)
        metadata_offset = f.tell()
        f.write(struct.pack("<I", len(metadata)))  # Number of entries

        for uuid_str, data in track(metadata.items(), description="[green]Writing metadata..."):
            f.write(UUID(uuid_str).bytes)  # UUID (16 bytes)

            name_bytes = data["name"].encode("utf-8")
            url_bytes = data["url"].encode("utf-8")

            f.write(struct.pack("<H", len(name_bytes)))  # Name length (2 bytes)
            f.write(name_bytes)  # Name
            f.write(struct.pack("<H", len(url_bytes)))  # URL length (2 bytes)
            f.write(url_bytes)  # URL

        # Section 3: Graph index (UUID -> file position)
        index_offset = f.tell()
        f.write(struct.pack("<I", len(index)))  # Number of entries

        for uuid_str, position in track(index.items(), description="[green]Writing index..."):
            f.write(UUID(uuid_str).bytes)  # UUID (16 bytes)
            f.write(struct.pack("<Q", position))  # Position (8 bytes, uint64)

        # Update header with section offsets
        end_pos = f.tell()
        f.seek(header_pos)
        f.write(struct.pack("<III", lookup_offset, metadata_offset, index_offset))
        f.seek(end_pos)

    return {
        "lookup_entries": len(lookup),
        "metadata_entries": len(metadata),
        "index_entries": len(index),
        "binary_size": binary_path.stat().st_size,
    }


def main() -> None:
    graph_file = Path("../data/graph.ndjson")
    metadata_file = Path("../data/metadata.ndjson")

    print("🔄 Starting post-processing...")
    print(f"📏 Graph input size: {graph_file.stat().st_size / (1024**3):.1f} GB")
    print(f"📏 Metadata input size: {metadata_file.stat().st_size / (1024**2):.1f} MB")

    # Step 1: Convert graph to binary
    print("\n📊 Step 1: Converting graph to binary format")
    graph_stats = convert_graph_to_binary(graph_file)

    # Step 2: Build lookup
    print("\n📊 Step 2: Building artist lookup")
    lookup = build_lookup(metadata_file)

    # Step 3: Create unified metadata binary
    print("\n📊 Step 3: Creating unified metadata binary")
    metadata_stats = create_unified_metadata_binary(metadata_file, lookup, graph_stats["index"])

    # Summary
    print("\n✅ Post-processing complete!")
    print(f"🎵 Artists processed: {graph_stats['artists']:,}")
    print(f"🔗 Total connections: {graph_stats['connections']:,}")
    print(f"💾 Graph binary size: {graph_stats['binary_size'] / (1024**2):.1f} MB")
    print(f"📇 Metadata binary size: {metadata_stats['binary_size'] / (1024**2):.1f} MB")
    print(
        f"📦 Total binary size: {(graph_stats['binary_size'] + metadata_stats['binary_size']) / (1024**2):.1f} MB",
    )

    original_size = graph_file.stat().st_size + metadata_file.stat().st_size
    binary_size = graph_stats["binary_size"] + metadata_stats["binary_size"]
    savings = (original_size - binary_size) / original_size * 100
    print(f"💰 Space savings: {savings:.1f}%")
    print("🎉 Done!")


if __name__ == "__main__":
    main()
