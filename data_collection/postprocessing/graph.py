"""Convert NDJSON graph to binary format and build reverse graph."""

import multiprocessing
import os
import shutil
import struct
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import orjson
from rich.progress import Progress

from collection.storage import GRAPH_ID_PREFIX

_pack_uint32 = struct.Struct("<I").pack
_pack_float = struct.Struct("<f").pack
# Reverse edge while collecting: source ordinal + weight (8 bytes instead of
# the 20-byte UUID + weight written to disk).
_REV_EDGE_DTYPE = np.dtype([("src", "<u4"), ("weight", "<f4")])
_OUT_EDGE_DTYPE = np.dtype([("uuid", "S16"), ("weight", "<f4")])
_COPY_BUFFER = 16 * 1024 * 1024

# Deliberately looser than storage._extract_graph_id, which also checks uuid
# shape: that is the right test for "can we re-crawl this", but as a dedup key
# anything _uuid_bytes accepts must index, or a dashless id would be dropped.
_ID_START = len(GRAPH_ID_PREFIX)

# A survivor's offset and record length share one int64 dict value; a tuple
# would add ~400 MB of object overhead over 6.1M entries.
_LEN_BITS = 21
_MAX_RECORD_LEN = 1 << _LEN_BITS
_MAX_UNPARSABLE = 64
# Every pass reads only what the survivor index lists, so a line without this
# prefix is dropped from the build entirely. 0 of 6.1M live lines mismatch, so
# anything but noise means the writer's format drifted and must fail loudly
# instead of shrinking the graph.
_MAX_PREFIX_MISMATCH_FRAC = 1e-6

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


def build_survivor_index(graph_file: Path, index_path: Path) -> int:
    """Index the records that survive supersession — the collector appends, so a
    re-crawled artist's last record wins — and return how many there are.

    Saves a (2, n) int64 array: ascending byte offsets, then record lengths.
    Indexing survivors rather than the superseded set is what keeps this
    bounded: there is one survivor per artist however many refresh laps have
    run, while superseded records grow by the whole live set every lap. The
    lengths are what let the forward phase split the work by survivor bytes.
    """
    last_record: dict[bytes, int] = {}
    non_blank = mismatched = 0
    with graph_file.open("rb") as f:
        while True:
            pos = f.tell()
            line = f.readline()
            if not line:
                break
            if line.isspace():
                continue
            non_blank += 1
            if not line.startswith(GRAPH_ID_PREFIX):
                mismatched += 1
                continue
            quote = line.find(b'"', _ID_START)
            if quote < 0:  # torn inside the id
                continue
            if len(line) >= _MAX_RECORD_LEN:
                raise RuntimeError(
                    f"graph record at offset {pos} is {len(line):,} bytes, too long "
                    f"to pack into {_LEN_BITS} length bits"
                )
            artist_id = line[_ID_START:quote]
            if artist_id in last_record:
                try:  # a torn re-crawl must not supersede a valid record
                    orjson.loads(line)
                except orjson.JSONDecodeError:
                    continue
            last_record[artist_id] = pos << _LEN_BITS | len(line)

    if mismatched > non_blank * _MAX_PREFIX_MISMATCH_FRAC:
        raise RuntimeError(
            f"{mismatched:,} of {non_blank:,} graph lines do not start with "
            f"{GRAPH_ID_PREFIX!r}; they would be dropped from the build silently"
        )

    packed = np.fromiter(last_record.values(), dtype=np.int64, count=len(last_record))
    packed.sort()
    np.save(index_path, np.stack([packed >> _LEN_BITS, packed & (_MAX_RECORD_LEN - 1)]))
    dropped = non_blank - mismatched - packed.size
    print(f"  {packed.size:,} surviving records, {dropped:,} superseded or unreadable")
    return int(packed.size)


def survivor_offsets(index_path: Path) -> np.ndarray:
    """Ascending survivor byte offsets, memory-mapped: a pass in another process
    is handed this path rather than 49 MB of offsets to unpickle."""
    return np.load(index_path, mmap_mode="r")[0]


def _chunk_bounds(lengths: np.ndarray, n_chunks: int) -> list[int]:
    """Survivor-array index boundaries splitting the work into n_chunks of
    roughly equal survivor BYTES. Edges per byte is near constant across the
    file but records per byte varies ~8x, and mid-lap the oldest region is
    all-superseded while the tail is all-live, so neither equal record counts
    nor equal byte spans keep the workers busy."""
    if lengths.size == 0:
        return [0] * (n_chunks + 1)
    cumulative = np.cumsum(lengths)
    targets = cumulative[-1] * np.arange(1, n_chunks) / n_chunks
    return [0, *(np.searchsorted(cumulative, targets) + 1).tolist(), int(lengths.size)]


def _blocked_mask(blocklist: np.ndarray, ids: np.ndarray) -> np.ndarray:
    """True where a 16-byte id occurs in the sorted S16 blocklist."""
    if blocklist.size == 0:
        return np.zeros(ids.size, dtype=bool)
    pos = np.minimum(np.searchsorted(blocklist, ids), blocklist.size - 1)
    return blocklist[pos] == ids


def _process_forward_chunk(
    path: str, offsets: np.ndarray, chunk_path: str
) -> tuple[int, list[tuple[str, int]], tuple[int, int, int]]:
    """Worker: write the forward-graph records at `offsets` to chunk_path.

    Returns (chunk size, [(artist_id, offset within chunk), ...], (json, uuid,
    blocklist) rejection counts). The counts let the parent prove every assigned
    survivor was either emitted or rejected for a named reason. Only the record
    being packed and the chunk's (id, offset) list are in memory; the blocklist
    is a shared memmap.
    """
    blocklist = _BLOCKLIST
    assert blocklist is not None
    forward_ids: list[tuple[str, int]] = []
    offset = 0
    json_rejects = uuid_rejects = blocked_rejects = 0

    with open(path, "rb") as f, open(chunk_path, "wb") as out:
        for pos in offsets:
            f.seek(pos)
            line = f.readline().strip()

            # Every indexed offset starts a record by construction, so a line
            # that does not means a bad seek - a truncated file, a stale index.
            # Without this it would land in json_rejects and balance the
            # accounting, which is exactly the silent loss the counts exist for.
            if not line.startswith(GRAPH_ID_PREFIX):
                msg = f"offset {pos} does not start a graph record"
                raise RuntimeError(msg)

            try:
                data = orjson.loads(line)
            except orjson.JSONDecodeError:
                json_rejects += 1
                continue

            artist_id = data["id"]

            try:
                artist_bytes = _uuid_bytes(artist_id)
            except ValueError:
                uuid_rejects += 1
                continue

            if _blocked_mask(blocklist, np.array([artist_bytes], dtype="S16"))[0]:
                blocked_rejects += 1
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

    return offset, forward_ids, (json_rejects, uuid_rejects, blocked_rejects)


def process_graph(
    graph_file: Path,
    data_dir: Path,
    blocklist: set[str] | None = None,
    survivor_index: Path | None = None,
) -> dict:
    """Convert graph.ndjson to graph.bin and rev-graph.bin.

    `survivor_index` is a build_survivor_index file; it also fixes the snapshot
    both binaries describe, since the collector keeps appending during a build.
    One is built here and removed again when the caller has none.
    """
    graph_bin = data_dir / "graph.bin"
    rev_graph_bin = data_dir / "rev-graph.bin"
    own_index = survivor_index is None
    if own_index:
        survivor_index = data_dir / "survivors.npy"
        build_survivor_index(graph_file, survivor_index)
    offsets, lengths = np.load(survivor_index)
    n_workers = min(os.cpu_count() or 1, 24)
    n_chunks = n_workers * 4
    print(f"  {offsets.size:,} survivors, {n_workers} workers, {n_chunks} chunks")

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
    bounds = _chunk_bounds(lengths, n_chunks)
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
                    offsets[bounds[i] : bounds[i + 1]],
                    str(chunk_paths[i]),
                )
                for i in range(n_chunks)
            ]
            task = progress.add_task("[green]Building forward graph...", total=n_chunks)
            position = 0
            rejected = [0, 0, 0]

            for i, future in enumerate(futures):
                try:
                    chunk_size, chunk_ids, rejects = future.result()
                    if chunk_paths[i].stat().st_size != chunk_size:
                        raise RuntimeError(f"{chunk_paths[i]} is not the size its worker reported")
                    assigned = bounds[i + 1] - bounds[i]
                    if len(chunk_ids) + sum(rejects) != assigned:
                        raise RuntimeError(
                            f"chunk {i} emitted {len(chunk_ids):,} and rejected {sum(rejects):,} "
                            f"of the {assigned:,} survivors assigned to it"
                        )
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
                rejected = [a + b for a, b in zip(rejected, rejects)]
                progress.advance(task)
    finally:
        blocklist_path.unlink(missing_ok=True)
        if own_index:
            survivor_index.unlink(missing_ok=True)
        for chunk_path in chunk_paths:
            chunk_path.unlink(missing_ok=True)

    json_rejects, uuid_rejects, blocked_rejects = rejected
    print(
        f"  {total_artists:,} artists in forward graph "
        f"({json_rejects:,} unparsable, {uuid_rejects:,} bad id, {blocked_rejects:,} blocked)"
    )
    # Blocked and bad-id counts are legitimately large, but only a record torn
    # by a crash is unparsable, so this is bounded by crash count rather than
    # file size - an absolute allowance, not a fraction. These rejects satisfy
    # the per-chunk accounting either way, and a loss under 10% clears the
    # shrink gate in check_and_refresh.sh unnoticed.
    if json_rejects > _MAX_UNPARSABLE:
        msg = f"{json_rejects:,} survivors failed to parse; the graph file looks damaged"
        raise RuntimeError(msg)

    # Phase 2: Reverse graph (sequential). Each target collects (source
    # ordinal, weight) pairs; source UUIDs are looked up by ordinal on write.
    # Reads exactly the records the forward phase covered, so both binaries
    # describe the same snapshot even while the collector keeps appending.
    reverse_data: dict[bytes, bytearray] = {}
    source_uuids = bytearray()
    n_sources = 0

    with graph_file.open("rb") as infile, Progress() as progress:
        task = progress.add_task(
            "[green]Collecting reverse connections...", total=offsets.size
        )

        for pos in offsets:
            infile.seek(pos)
            line = infile.readline().strip()
            progress.advance(task)

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
