"""Build lookup and unified metadata binary from NDJSON."""

import struct
import subprocess
from pathlib import Path

import orjson
from rich.progress import Progress

from normalization import clean_str

_pack_uint16 = struct.Struct("<H").pack
_pack_uint32 = struct.Struct("<I").pack
_pack_uint64 = struct.Struct("<Q").pack


def _uuid_bytes(s: str) -> bytes:
    return bytes.fromhex(s.replace("-", ""))


def _count_lines(path: Path) -> int:
    result = subprocess.run(["wc", "-l", str(path)], capture_output=True, text=True)
    return int(result.stdout.split()[0])


def process_metadata(
    metadata_file: Path,
    data_dir: Path,
    forward_index: dict[str, int],
    reverse_index: dict[str, int],
    blocklist: set[str] | None = None,
) -> dict:
    """Build lookup and metadata from metadata.ndjson, write metadata.bin."""
    binary_path = data_dir / "metadata.bin"
    line_count = _count_lines(metadata_file)
    print(f"  {line_count:,} metadata entries to process")

    blocklist = blocklist or set()
    lookup: dict[str, list[str]] = {}
    metadata: dict[str, dict[str, str]] = {}

    with metadata_file.open("rb") as f, Progress() as progress:
        task = progress.add_task("[green]Building lookup...", total=line_count)

        for raw_line in f:
            progress.advance(task)
            line = raw_line.strip()
            if not line:
                continue

            try:
                entry = orjson.loads(line)
                mbid = entry["id"]
                name = entry["name"]
                url = entry["url"]
            except (orjson.JSONDecodeError, KeyError):
                continue

            if mbid in blocklist:
                continue

            metadata[mbid] = {"name": name, "url": url}

            clean_name = clean_str(name)
            if clean_name not in lookup:
                lookup[clean_name] = []
            lookup[clean_name].append(mbid)

    print(f"  {len(lookup):,} unique clean names, {len(metadata):,} metadata entries")

    # Write unified binary
    with binary_path.open("wb") as f:
        header_pos = f.tell()
        f.write(struct.pack("<IIII", 0, 0, 0, 0))

        # Section 1: Lookup
        lookup_offset = f.tell()
        f.write(_pack_uint32(len(lookup)))

        with Progress() as progress:
            task = progress.add_task("[green]Writing lookup...", total=len(lookup))
            for clean_name, uuid_list in lookup.items():
                progress.advance(task)
                name_bytes = clean_name.encode("utf-8")
                f.write(_pack_uint16(len(name_bytes)))
                f.write(name_bytes)
                f.write(_pack_uint16(len(uuid_list)))
                for uuid_str in uuid_list:
                    f.write(_uuid_bytes(uuid_str))

        # Section 2: Metadata
        metadata_offset = f.tell()
        f.write(_pack_uint32(len(metadata)))

        with Progress() as progress:
            task = progress.add_task("[green]Writing metadata...", total=len(metadata))
            for uuid_str, data in metadata.items():
                progress.advance(task)
                f.write(_uuid_bytes(uuid_str))

                name_bytes = data["name"].encode("utf-8")
                url_bytes = data["url"].encode("utf-8")

                f.write(_pack_uint16(len(name_bytes)))
                f.write(name_bytes)
                f.write(_pack_uint16(len(url_bytes)))
                f.write(url_bytes)

        # Section 3: Forward index
        forward_index_offset = f.tell()
        f.write(_pack_uint32(len(forward_index)))

        with Progress() as progress:
            task = progress.add_task("[green]Writing forward index...", total=len(forward_index))
            for uuid_str, position in forward_index.items():
                progress.advance(task)
                f.write(_uuid_bytes(uuid_str))
                f.write(_pack_uint64(position))

        # Section 4: Reverse index
        reverse_index_offset = f.tell()
        f.write(_pack_uint32(len(reverse_index)))

        with Progress() as progress:
            task = progress.add_task("[green]Writing reverse index...", total=len(reverse_index))
            for uuid_str, position in reverse_index.items():
                progress.advance(task)
                f.write(_uuid_bytes(uuid_str))
                f.write(_pack_uint64(position))

        # Update header
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
