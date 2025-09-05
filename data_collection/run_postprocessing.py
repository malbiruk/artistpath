import json
import struct
from pathlib import Path
from uuid import UUID

import psutil
from normalization import clean_str
from rich.progress import track


def _build_binary_entry(artist_id_str: str, connections: list) -> tuple[bytearray | None, int, str]:
    """Build binary entry for a single artist. Returns (entry_data, valid_connections, artist_id_str)."""
    try:
        artist_uuid = UUID(artist_id_str)
        artist_bytes = artist_uuid.bytes
    except ValueError:
        return None, 0, artist_id_str

    entry_data = bytearray()
    entry_data.extend(artist_bytes)  # 16 bytes
    entry_data.extend(struct.pack("<I", len(connections)))  # 4 bytes (will be updated if needed)

    # Process connections with minimal UUID parsing
    valid_connections = 0
    for conn_id, weight in connections:
        try:
            conn_uuid_bytes = UUID(conn_id).bytes
            entry_data.extend(conn_uuid_bytes)  # 16 bytes
            entry_data.extend(struct.pack("<f", weight))  # 4 bytes
            valid_connections += 1
        except ValueError:
            continue  # Skip invalid UUIDs

    # Update connection count if some UUIDs were invalid
    if valid_connections != len(connections):
        struct.pack_into("<I", entry_data, 16, valid_connections)

    return entry_data, valid_connections, artist_id_str


def _flush_buffer_if_needed(
    write_buffer: bytearray,
    outfile,
    position: int,
    buffer_size: int,
    processed_lines: int,
) -> int:
    """Flush write buffer if it's full and return new position."""
    if len(write_buffer) >= buffer_size:
        outfile.write(write_buffer)
        new_position = position + len(write_buffer)
        write_buffer.clear()

        # Memory check
        memory_mb = psutil.Process().memory_info().rss / (1024 * 1024)
        if processed_lines % 100000 == 0:
            print(f"   Memory: {memory_mb:.0f}MB, processed {processed_lines:,} lines")

        return new_position
    return position


def convert_graph_to_binary(graph_file: Path | str, line_count: int | None = None) -> dict:
    """Convert NDJSON graph to binary format with index for faster loading."""
    graph_path = Path(graph_file)
    binary_path = Path("../data/graph.bin")

    index = {}
    total_artists = 0
    total_connections = 0

    # Buffer for batched writes
    write_buffer = bytearray()
    buffer_size = 8 * 1024 * 1024  # 8MB buffer

    # Count lines only if not provided
    if line_count is None:
        print(f"📊 Counting lines in {graph_path.name}...")
        with graph_path.open() as f:
            line_count = sum(1 for line in f if line.strip())
        print(f"   Found {line_count:,} lines to process")

    with graph_path.open() as infile, binary_path.open("wb") as outfile:
        position = 0
        processed_lines = 0

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
                artist_id_str = data["id"]
                connections = data["connections"]

                # Build binary entry
                entry_data, valid_connections, _ = _build_binary_entry(artist_id_str, connections)
                if entry_data is None:
                    print(f"⚠️  Invalid UUID: {artist_id_str}")
                    continue

                # Store byte position for this artist in index
                index[artist_id_str] = position + len(write_buffer)

                # Add to buffer
                write_buffer.extend(entry_data)
                total_artists += 1
                total_connections += valid_connections

                # Flush buffer if needed
                position = _flush_buffer_if_needed(
                    write_buffer,
                    outfile,
                    position,
                    buffer_size,
                    processed_lines,
                )

            except (json.JSONDecodeError, KeyError) as e:
                print(f"⚠️  Skipping malformed line: {e}")
                continue

            processed_lines += 1

        # Write final buffer
        if write_buffer:
            outfile.write(write_buffer)

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


def create_unified_metadata_binary(
    metadata_file: Path | str,
    lookup: dict,
    forward_index: dict,
    reverse_index: dict | None = None,
) -> dict:
    """Create a single binary file with lookup, metadata, forward index, and reverse index."""
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

    # Use empty dict if no reverse index provided
    if reverse_index is None:
        reverse_index = {}

    with binary_path.open("wb") as f:
        # Header: 4 uint32 values for section offsets
        header_pos = f.tell()
        f.write(struct.pack("<IIII", 0, 0, 0, 0))  # Placeholders for section offsets

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

        # Section 3: Forward graph index (passUUID -> file position in graph.bin)
        forward_index_offset = f.tell()
        f.write(struct.pack("<I", len(forward_index)))  # Number of entries

        for uuid_str, position in track(
            forward_index.items(),
            description="[green]Writing forward index...",
        ):
            f.write(UUID(uuid_str).bytes)  # UUID (16 bytes)
            f.write(struct.pack("<Q", position))  # Position (8 bytes, uint64)

        # Section 4: Reverse graph index (UUID -> file position in rev-graph.bin)
        reverse_index_offset = f.tell()
        f.write(struct.pack("<I", len(reverse_index)))  # Number of entries

        for uuid_str, position in track(
            reverse_index.items(),
            description="[green]Writing reverse index...",
        ):
            f.write(UUID(uuid_str).bytes)  # UUID (16 bytes)
            f.write(struct.pack("<Q", position))  # Position (8 bytes, uint64)

        # Update header with section offsets
        end_pos = f.tell()
        f.seek(header_pos)
        f.write(
            struct.pack(
                "<IIII",
                lookup_offset,
                metadata_offset,
                forward_index_offset,
                reverse_index_offset,
            ),
        )
        f.seek(end_pos)

    return {
        "lookup_entries": len(lookup),
        "metadata_entries": len(metadata),
        "forward_index_entries": len(forward_index),
        "reverse_index_entries": len(reverse_index),
        "binary_size": binary_path.stat().st_size,
    }


def _process_graph_line_for_reverse(line: str, reverse_connections: dict) -> int:
    """Process a single graph line and add reverse connections. Returns number of connections added."""
    connections_added = 0

    try:
        data = json.loads(line)
        source_id = data["id"]

        for target_id, similarity in data["connections"]:
            # Always add to current chunk (don't skip processed artists here!)
            if target_id not in reverse_connections:
                reverse_connections[target_id] = []
            reverse_connections[target_id].append((source_id, similarity))
            connections_added += 1

    except (json.JSONDecodeError, ValueError, KeyError) as e:
        print(f"⚠️  Skipping malformed line: {e}")

    return connections_added


# Removed chunking functions - now using simpler collect-all-then-write approach


def build_reverse_graph_binary(graph_file: Path, line_count: int | None = None) -> dict:
    """Build reverse graph from forward graph - collect ALL connections then write."""
    reverse_binary_path = Path("../data/rev-graph.bin")

    # Collect ALL reverse connections in memory first
    reverse_connections = {}  # target_id -> list of (source_id, similarity)
    total_connections = 0

    # Count lines only if not provided
    if line_count is None:
        print(f"📊 Counting lines in {graph_file.name}...")
        with graph_file.open() as f:
            line_count = sum(1 for line in f if line.strip())
        print(f"   Found {line_count:,} lines to process")

    print("📊 Building complete reverse graph in memory...")

    with graph_file.open() as f:
        processed_lines = 0

        for line_ in track(
            f,
            total=line_count,
            description="[green]Collecting reverse connections...",
        ):
            line = line_.strip()
            if not line:
                continue

            # Process this line
            connections_added = _process_graph_line_for_reverse(line, reverse_connections)
            total_connections += connections_added

            processed_lines += 1
            if processed_lines % 200000 == 0:
                print(f"   Processed {processed_lines:,} lines, {total_connections:,} connections")
                print(f"   Unique reverse artists so far: {len(reverse_connections):,}")

                # Memory check
                memory_mb = psutil.Process().memory_info().rss / (1024 * 1024)
                print(f"   Memory usage: {memory_mb:.0f}MB")

    print(f"📊 Writing {len(reverse_connections):,} artists to binary...")

    # Write everything to binary
    rev_index = {}
    with reverse_binary_path.open("wb") as outfile:
        for target_id, connections in track(
            reverse_connections.items(),
            description="[green]Writing reverse graph binary...",
        ):
            try:
                artist_id = UUID(target_id)

                # Sort by similarity (highest first)
                connections.sort(key=lambda x: x[1], reverse=True)

                # Store byte position for this artist in index
                rev_index[target_id] = outfile.tell()

                # Write binary format
                outfile.write(artist_id.bytes)  # 16 bytes
                outfile.write(struct.pack("<I", len(connections)))  # 4 bytes

                for source_id, weight in connections:
                    outfile.write(UUID(source_id).bytes)  # 16 bytes
                    outfile.write(struct.pack("<f", weight))  # 4 bytes

            except (ValueError, KeyError) as e:
                print(f"⚠️  Skipping invalid artist ID: {e}")
                continue

    unique_artists = len(reverse_connections)
    print(
        f"✅ Reverse graph complete: {unique_artists:,} artists, {total_connections:,} connections",
    )

    return {
        "artists": unique_artists,
        "connections": total_connections,
        "binary_size": reverse_binary_path.stat().st_size,
        "index": rev_index,
    }


# Removed _write_reverse_chunk - now writing directly in main function


MB = 1024**2
GB = 1024**3


def main() -> None:
    graph_file = Path("../data/graph.ndjson")
    metadata_file = Path("../data/metadata.ndjson")

    print("🔄 Starting post-processing...")
    print(f"📏 Graph input size: {graph_file.stat().st_size / GB:.1f} GB")
    print(f"📏 Metadata input size: {metadata_file.stat().st_size / MB:.1f} MB")

    # Count graph lines once for both steps 1 and 2
    print(f"\n📊 Counting lines in {graph_file.name}...")
    with graph_file.open() as f:
        graph_line_count = sum(1 for line in f if line.strip())
    print(f"   Found {graph_line_count:,} lines to process")

    # Step 1: Convert forward graph to binary
    print("\n📊 Step 1: Converting forward graph to binary format")
    graph_stats = convert_graph_to_binary(graph_file, graph_line_count)
    print(f"✅ Forward graph: {graph_stats['binary_size'] / MB:.1f} MB")

    # Step 2: Build reverse graph binary
    print("\n📊 Step 2: Building reverse graph binary")
    rev_graph_stats = build_reverse_graph_binary(graph_file, graph_line_count)
    print(f"✅ Reverse graph: {rev_graph_stats['binary_size'] / MB:.1f} MB")

    # Step 3: Create unified metadata binary with lookup and both indexes
    print("\n📊 Step 3: Creating unified metadata binary")
    print("   Building artist lookup...")
    lookup = build_lookup(metadata_file)
    print(f"   ✅ Lookup built with {len(lookup):,} clean names")

    forward_index = graph_stats["index"]
    reverse_index = rev_graph_stats["index"]

    metadata_stats = create_unified_metadata_binary(
        metadata_file,
        lookup,
        forward_index,
        reverse_index,
    )
    print(f"✅ Metadata binary: {metadata_stats['binary_size'] / MB:.1f} MB")
    print(f"   Lookup entries: {metadata_stats['lookup_entries']:,}")
    print(f"   Metadata entries: {metadata_stats['metadata_entries']:,}")
    print(f"   Forward index: {metadata_stats['forward_index_entries']:,} entries")
    print(f"   Reverse index: {metadata_stats['reverse_index_entries']:,} entries")

    # Summary
    print("\n✅ Post-processing complete!")
    print(f"🎵 Artists processed: {graph_stats['artists']:,}")
    print(f"🔗 Forward connections: {graph_stats['connections']:,}")
    print(f"🔄 Reverse connections: {rev_graph_stats['connections']:,}")
    print(f"💾 Forward graph: {graph_stats['binary_size'] / MB:.1f} MB")
    print(f"🔄 Reverse graph: {rev_graph_stats['binary_size'] / MB:.1f} MB")
    print(f"📇 Metadata binary: {metadata_stats['binary_size'] / MB:.1f} MB")

    total_binary_size = (
        graph_stats["binary_size"] + rev_graph_stats["binary_size"] + metadata_stats["binary_size"]
    )
    print(f"📦 Total binary size: {total_binary_size / MB:.1f} MB")

    original_size = graph_file.stat().st_size + metadata_file.stat().st_size
    savings = (original_size - total_binary_size) / original_size * 100
    print(f"💰 Space savings: {savings:.1f}%")
    print("🎉 Done!")


if __name__ == "__main__":
    main()
