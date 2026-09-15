"""Data storage utilities for NDJSON and state management."""

import json
import os
from collections import deque
from pathlib import Path


def load_existing_data(output_dir: str = "../data") -> tuple[dict, dict, set, deque]:
    graph = {}
    artist_metadata = {}
    processed_mbids = set()
    queue = deque()

    graph_path = Path(output_dir) / "graph.ndjson"
    metadata_path = Path(output_dir) / "metadata.ndjson"
    state_path = Path(output_dir) / "collection_state.json"

    if graph_path.exists():
        print(f"Loading existing graph from {graph_path}")
        with graph_path.open() as f:
            for line in f:
                if line.strip():
                    entry = json.loads(line)
                    graph[entry["id"]] = entry["connections"]

    if metadata_path.exists():
        print(f"Loading existing metadata from {metadata_path}")
        with metadata_path.open() as f:
            for line in f:
                if line.strip():
                    entry = json.loads(line)
                    artist_metadata[entry["id"]] = {
                        "name": entry["name"],
                        "url": entry["url"],
                    }

    if state_path.exists():
        print(f"Loading state from {state_path}")
        with state_path.open() as f:
            state = json.load(f)
            processed_mbids = set(state.get("processed_mbids", []))
            queue = deque(state.get("queue", []))

    print(f"Loaded {len(graph)} graph nodes, {len(artist_metadata)} metadata entries")
    print(f"Resuming with {len(processed_mbids)} processed artists, {len(queue)} in queue")

    return graph, artist_metadata, processed_mbids, queue


def load_names(output_dir: str = "../data") -> dict[str, str]:
    """Map every metadata id to its name. Lines corrupted by a past crash are skipped."""
    names: dict[str, str] = {}
    metadata_path = Path(output_dir) / "metadata.ndjson"
    if not metadata_path.exists():
        return names
    with metadata_path.open() as f:
        for line in f:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                names[entry["id"]] = entry["name"]
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
    return names


# Exactly what append_to_graph's json.dumps emits, and the only definition of
# it: postprocessing reads ids out of lines the same way, and a reader that
# disagrees with the writer would silently drop every record.
GRAPH_ID_PREFIX = b'{"id": "'
_UUID_LEN = 36
_UUID_DASHES = (8, 13, 18, 23)


def _extract_graph_id(line: bytes) -> str | None:
    """Read the id out of a graph record without parsing the whole line."""
    start = len(GRAPH_ID_PREFIX)
    if not line.startswith(GRAPH_ID_PREFIX):
        return None
    artist_id = line[start : start + _UUID_LEN]
    if len(artist_id) != _UUID_LEN or line[start + _UUID_LEN : start + _UUID_LEN + 1] != b'"':
        return None
    if any(artist_id[p : p + 1] != b"-" for p in _UUID_DASHES):
        return None
    return artist_id.decode()


def scan_oldest_ids(output_dir: str, offset: int, limit: int) -> tuple[list[str], int]:
    """Collect up to `limit` distinct ids from graph.ndjson starting at `offset`.

    Returns them in file order plus the offset just past the last line read.
    Byte position is the only staleness proxy the append-only file has, so
    scanning forward from 0 yields the least recently crawled artists first.
    An offset at or past EOF restarts from the beginning, covering both being
    caught up and a compaction shrinking the file. Only whole lines are
    consumed, so a record the collector is midway through appending is left for
    the next scan.
    """
    graph_path = Path(output_dir) / "graph.ndjson"
    if not graph_path.exists():
        return [], 0

    if offset >= graph_path.stat().st_size:
        offset = 0

    ids: list[str] = []
    seen: set[str] = set()
    # Bounded so a region dense in superseded duplicates cannot pull tens of GB
    # through one synchronous scan hunting for `limit` distinct ids. A short
    # chunk just means the next refill picks up where this one stopped.
    lines_left = limit * 2
    with graph_path.open("rb") as f:
        f.seek(offset)
        while len(ids) < limit and lines_left:
            line = f.readline()
            if not line.endswith(b"\n"):
                break
            lines_left -= 1
            offset += len(line)
            artist_id = _extract_graph_id(line)
            if artist_id is not None and artist_id not in seen:
                seen.add(artist_id)
                ids.append(artist_id)

    return ids, offset


def save_state(
    processed_mbids: set,
    queue: deque,
    output_dir: str = "../data",
    *,
    refresh_queue: deque | None = None,
    refresh_offset: int = 0,
    crawled_total: int = 0,
) -> None:
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    state_path = Path(output_dir) / "collection_state.json"
    tmp_path = state_path.with_suffix(".json.tmp")
    state = {
        "processed_mbids": list(processed_mbids),
        "queue": list(queue),
        "refresh_queue": list(refresh_queue or ()),
        "refresh_offset": refresh_offset,
        "crawled_total": crawled_total,
    }
    with tmp_path.open("w") as f:
        json.dump(state, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, state_path)


def append_to_graph(node_id: str, connections: list, output_dir: str = "../data") -> None:
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    graph_path = Path(output_dir) / "graph.ndjson"
    entry = {"id": node_id, "connections": connections}
    with graph_path.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def append_to_metadata(node_id: str, name: str, url: str, output_dir: str = "../data") -> None:
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    metadata_path = Path(output_dir) / "metadata.ndjson"
    entry = {"id": node_id, "name": name, "url": url}
    with metadata_path.open("a") as f:
        f.write(json.dumps(entry) + "\n")
