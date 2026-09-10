"""Convert NDJSON graph to binary format and build reverse graph."""

import multiprocessing
import os
import shutil
import struct
import subprocess
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import orjson
from rich.progress import Progress

_pack_uint32 = struct.Struct("<I").pack
_pack_float = struct.Struct("<f").pack
# Reverse edge while collecting: source ordinal + weight (8 bytes instead of
# the 20-byte UUID + weight written to disk).
_REV_EDGE_DTYPE = np.dtype([("src", "<u4"), ("weight", "<f4")])
_OUT_EDGE_DTYPE = np.dtype([("uuid", "S16"), ("weight", "<f4")])
_COPY_BUFFER = 16 * 1024 * 1024

# Sorted S16 blocklist, memory-mapped once per worker by _load_blocklist.
_BLOCKLIST: np.ndarray | None = None


def _load_blocklist(path: str) -> None:
    global _BLOCKLIST
    _BLOCKLIST = np.load(path, mmap_mode="r")


def _uuid_bytes(s: str) -> bytes:
    b = bytes.fromhex(s.replace("-", ""))
    if len(b) != 16:
        raise ValueError(f"not a 16-byte uuid: {s!r}")
    return b


def _uuid_str(b: bytes) -> str:
    h = b.hex()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


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


def _blocked_mask(blocklist: np.ndarray, ids: np.ndarray) -> np.ndarray:
    """True where a 16-byte id occurs in the sorted S16 blocklist."""
    if blocklist.size == 0:
        return np.zeros(ids.size, dtype=bool)
    pos = np.minimum(np.searchsorted(blocklist, ids), blocklist.size - 1)
    return blocklist[pos] == ids


def _process_forward_chunk(
    path: str, start: int, end: int, chunk_path: str
) -> tuple[int, list[tuple[str, int]]]:
    """Worker: write the forward-graph records of a byte range to chunk_path.

    Returns (chunk size, [(artist_id, offset within chunk), ...]). Only the
    record being packed and the chunk's (id, offset) list are in memory; the
    blocklist is a shared memmap.
    """
    blocklist = _BLOCKLIST
    assert blocklist is not None
    forward_ids: list[tuple[str, int]] = []
    offset = 0

    with open(path, "rb") as f, open(chunk_path, "wb") as out:
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

            try:
                artist_bytes = _uuid_bytes(artist_id)
            except ValueError:
                continue

            if _blocked_mask(blocklist, np.array([artist_bytes], dtype="S16"))[0]:
                continue

            conn_ids: list[bytes] = []
            conn_weights: list[float] = []
            for conn_id, weight in data["connections"]:
                try:
                    conn_ids.append(_uuid_bytes(conn_id))
                except ValueError:
                    continue
                conn_weights.append(weight)

            edges = np.empty(len(conn_ids), dtype=_OUT_EDGE_DTYPE)
            edges["uuid"] = conn_ids
            edges["weight"] = conn_weights
            edges = edges[~_blocked_mask(blocklist, edges["uuid"])]

            record = artist_bytes + _pack_uint32(edges.size) + edges.tobytes()
            out.write(record)
            forward_ids.append((artist_id, offset))
            offset += len(record)

    return offset, forward_ids


def process_graph(
    graph_file: Path, data_dir: Path, blocklist: set[str] | None = None
) -> dict:
    """Convert graph.ndjson to graph.bin and rev-graph.bin."""
    graph_bin = data_dir / "graph.bin"
    rev_graph_bin = data_dir / "rev-graph.bin"
    line_count = _count_lines(graph_file)
    n_workers = min(os.cpu_count() or 1, 24)
    n_chunks = n_workers * 4
    print(f"  {line_count:,} lines, {n_workers} workers, {n_chunks} chunks")

    blocked: set[bytes] = set()
    for uuid_str in blocklist or ():
        try:
            blocked.add(_uuid_bytes(uuid_str))
        except ValueError:
            continue
    # Sorted array in a file that every worker memory-maps, instead of each
    # worker holding its own copy of a 1M+ entry set.
    blocklist_path = data_dir / "blocklist.npy"
    np.save(blocklist_path, np.sort(np.array(list(blocked), dtype="S16")))
    boundaries = _find_chunk_boundaries(graph_file, n_chunks)
    chunk_paths = [data_dir / f"graph.chunk{i:03d}.bin" for i in range(n_chunks)]

    # Phase 1: Forward graph. Workers stream records to per-chunk files that
    # are concatenated in order, so no chunk output is ever held in RAM.
    forward_index: dict[str, int] = {}
    total_artists = 0

    try:
        with (
            ProcessPoolExecutor(
                n_workers,
                mp_context=multiprocessing.get_context("spawn"),
                initializer=_load_blocklist,
                initargs=(str(blocklist_path),),
            ) as pool,
            graph_bin.open("wb") as outfile,
            Progress() as progress,
        ):
            futures = [
                pool.submit(
                    _process_forward_chunk,
                    str(graph_file),
                    boundaries[i],
                    boundaries[i + 1],
                    str(chunk_paths[i]),
                )
                for i in range(n_chunks)
            ]
            task = progress.add_task("[green]Building forward graph...", total=n_chunks)
            position = 0

            for i, future in enumerate(futures):
                try:
                    chunk_size, chunk_ids = future.result()
                except BaseException:
                    pool.shutdown(cancel_futures=True)
                    raise
                with chunk_paths[i].open("rb") as chunk_file:
                    shutil.copyfileobj(chunk_file, outfile, _COPY_BUFFER)
                chunk_paths[i].unlink()
                for artist_id, offset in chunk_ids:
                    forward_index[artist_id] = position + offset
                total_artists += len(chunk_ids)
                position += chunk_size
                progress.advance(task)
    finally:
        blocklist_path.unlink(missing_ok=True)
        for chunk_path in chunk_paths:
            chunk_path.unlink(missing_ok=True)

    print(f"  {total_artists:,} artists in forward graph")

    # Phase 2: Reverse graph (sequential). Each target collects (source
    # ordinal, weight) pairs; source UUIDs are looked up by ordinal on write.
    reverse_data: dict[bytes, bytearray] = {}
    source_uuids = bytearray()
    n_sources = 0

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

            if artist_bytes in blocked:
                continue

            src = _pack_uint32(n_sources)
            n_sources += 1
            source_uuids.extend(artist_bytes)

            for conn_id, weight in data["connections"]:
                try:
                    conn_bytes = _uuid_bytes(conn_id)
                except ValueError:
                    continue
                if conn_bytes in blocked:
                    continue

                buf = reverse_data.get(conn_bytes)
                if buf is None:
                    buf = reverse_data[conn_bytes] = bytearray()
                buf.extend(src)
                buf.extend(_pack_float(weight))

    total_conns = sum(len(v) for v in reverse_data.values()) // 8
    print(f"  {total_conns:,} reverse connections collected")

    # Write reverse graph binary
    source_uuid_arr = np.frombuffer(bytes(source_uuids), dtype="S16")
    reverse_index: dict[str, int] = {}

    with rev_graph_bin.open("wb") as outfile, Progress() as progress:
        task = progress.add_task(
            "[green]Writing reverse graph binary...", total=len(reverse_data)
        )

        for target_bytes, conn_buf in reverse_data.items():
            progress.advance(task)
            edges = np.frombuffer(conn_buf, dtype=_REV_EDGE_DTYPE)
            order = np.argsort(-edges["weight"], kind="stable")
            out = np.empty(edges.size, dtype=_OUT_EDGE_DTYPE)
            out["uuid"] = source_uuid_arr[edges["src"][order]]
            out["weight"] = edges["weight"][order]

            reverse_index[_uuid_str(target_bytes)] = outfile.tell()
            outfile.write(target_bytes)
            outfile.write(_pack_uint32(edges.size))
            outfile.write(out.tobytes())

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
