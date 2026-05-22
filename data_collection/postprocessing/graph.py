"""Convert NDJSON graph to binary format and build reverse graph."""

import os
import struct
import subprocess
from pathlib import Path

import orjson
from joblib import Parallel, delayed
from rich.progress import Progress

_pack_uint32 = struct.Struct("<I").pack
_pack_float = struct.Struct("<f").pack
_unpack_float = struct.Struct("<f").unpack


def _uuid_bytes(s: str) -> bytes:
    return bytes.fromhex(s.replace("-", ""))


def _count_lines(path: Path) -> int:
    result = subprocess.run(["wc", "-l", str(path)], capture_output=True, text=True)
    return int(result.stdout.split()[0])


def _find_chunk_boundaries(path: Path, n_chunks: int) -> list[int]:
    file_size = path.stat().st_size
    boundaries = [0]
    with path.open("rb") as f:
        for i in range(1, n_chunks):
            f.seek(file_size * i // n_chunks)
            f.readline()
            boundaries.append(f.tell())
    boundaries.append(file_size)
    return boundaries


def _process_forward_chunk(
    path: str, start: int, end: int
) -> tuple[bytes, list[tuple[str, int]]]:
    """Worker: build forward graph binary from a byte range. No reverse data."""
    forward_buf = bytearray()
    forward_ids: list[tuple[str, int]] = []

    with open(path, "rb") as f:
        f.seek(start)
        while f.tell() < end:
            line = f.readline().strip()
            if not line:
                continue

            try:
                data = orjson.loads(line)
            except orjson.JSONDecodeError:
                continue

            artist_id = data["id"]
            connections = data["connections"]

            try:
                artist_bytes = _uuid_bytes(artist_id)
            except ValueError:
                continue

            offset = len(forward_buf)
            valid_conns = 0
            conn_data = bytearray()

            for conn_id, weight in connections:
                try:
                    conn_bytes = _uuid_bytes(conn_id)
                except ValueError:
                    continue

                conn_data.extend(conn_bytes)
                conn_data.extend(_pack_float(weight))
                valid_conns += 1

            forward_buf.extend(artist_bytes)
            forward_buf.extend(_pack_uint32(valid_conns))
            forward_buf.extend(conn_data)
            forward_ids.append((artist_id, offset))

    return bytes(forward_buf), forward_ids


def process_graph(graph_file: Path, data_dir: Path) -> dict:
    """Convert graph.ndjson to graph.bin and rev-graph.bin."""
    graph_bin = data_dir / "graph.bin"
    rev_graph_bin = data_dir / "rev-graph.bin"
    line_count = _count_lines(graph_file)
    n_workers = min(os.cpu_count() or 1, 24)
    print(f"  {line_count:,} lines, {n_workers} workers")

    boundaries = _find_chunk_boundaries(graph_file, n_workers)

    # Phase 1: Forward graph (parallel, low memory)
    forward_index: dict[str, int] = {}
    total_artists = 0

    results = Parallel(n_jobs=n_workers, return_as="generator")(
        delayed(_process_forward_chunk)(
            str(graph_file), boundaries[i], boundaries[i + 1]
        )
        for i in range(n_workers)
    )

    with graph_bin.open("wb") as outfile, Progress() as progress:
        task = progress.add_task("[green]Building forward graph...", total=n_workers)
        position = 0

        for chunk_buf, chunk_ids in results:
            outfile.write(chunk_buf)
            for artist_id, offset in chunk_ids:
                forward_index[artist_id] = position + offset
            total_artists += len(chunk_ids)
            position += len(chunk_buf)
            progress.advance(task)

    print(f"  {total_artists:,} artists in forward graph")

    # Phase 2: Reverse graph (sequential, ~12-15 GB with packed bytes)
    reverse_data: dict[str, bytearray] = {}

    with graph_file.open("rb") as infile, Progress() as progress:
        task = progress.add_task(
            "[green]Collecting reverse connections...", total=line_count
        )

        for raw_line in infile:
            progress.advance(task)
            line = raw_line.strip()
            if not line:
                continue

            try:
                data = orjson.loads(line)
            except orjson.JSONDecodeError:
                continue

            try:
                artist_bytes = _uuid_bytes(data["id"])
            except ValueError:
                continue

            for conn_id, weight in data["connections"]:
                try:
                    _uuid_bytes(conn_id)
                except ValueError:
                    continue

                if conn_id not in reverse_data:
                    reverse_data[conn_id] = bytearray()
                reverse_data[conn_id].extend(artist_bytes)
                reverse_data[conn_id].extend(_pack_float(weight))

    total_conns = sum(len(v) // 20 for v in reverse_data.values())
    print(f"  {total_conns:,} reverse connections collected")

    # Write reverse graph binary
    reverse_index: dict[str, int] = {}

    with rev_graph_bin.open("wb") as outfile, Progress() as progress:
        task = progress.add_task(
            "[green]Writing reverse graph binary...", total=len(reverse_data)
        )

        for target_id, conn_buf in reverse_data.items():
            progress.advance(task)
            try:
                target_bytes = _uuid_bytes(target_id)
            except ValueError:
                continue

            n_conns = len(conn_buf) // 20
            chunks = [conn_buf[i : i + 20] for i in range(0, len(conn_buf), 20)]
            chunks.sort(key=lambda c: _unpack_float(c[16:20])[0], reverse=True)

            reverse_index[target_id] = outfile.tell()
            outfile.write(target_bytes)
            outfile.write(_pack_uint32(n_conns))
            for chunk in chunks:
                outfile.write(chunk)

    return {
        "forward_index": forward_index,
        "reverse_index": reverse_index,
        "artists": total_artists,
        "forward_connections": total_conns,
        "reverse_connections": total_conns,
        "reverse_artists": len(reverse_data),
        "graph_bin_size": graph_bin.stat().st_size,
        "rev_graph_bin_size": rev_graph_bin.stat().st_size,
    }
