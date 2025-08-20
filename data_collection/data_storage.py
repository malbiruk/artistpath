"""Data storage utilities for NDJSON and state management."""

import json
from collections import deque
from pathlib import Path


def load_existing_data(output_dir: str = "../data") -> tuple[dict, dict, set, deque]:
    """Load existing data from NDJSON files."""
    graph = {}
    artist_metadata = {}
    processed_mbids = set()
    queue = deque()

    graph_path = Path(output_dir) / "graph.ndjson"
    metadata_path = Path(output_dir) / "metadata.ndjson"
    state_path = Path(output_dir) / "collection_state.json"

    # Load graph
    if graph_path.exists():
        print(f"Loading existing graph from {graph_path}")
        with Path(graph_path).open() as f:
            for line in f:
                if line.strip():
                    entry = json.loads(line)
                    graph[entry["id"]] = entry["connections"]

    # Load metadata
    if metadata_path.exists():
        print(f"Loading existing metadata from {metadata_path}")
        with Path(metadata_path).open() as f:
            for line in f:
                if line.strip():
                    entry = json.loads(line)
                    artist_metadata[entry["id"]] = {
                        "name": entry["name"],
                        "url": entry["url"],
                    }

    # Load state (processed artists and queue)
    if state_path.exists():
        print(f"Loading state from {state_path}")
        with Path(state_path).open() as f:
            state = json.load(f)
            processed_mbids = set(state.get("processed_mbids", []))
            queue = deque(state.get("queue", []))

    print(f"Loaded {len(graph)} graph nodes, {len(artist_metadata)} metadata entries")
    print(f"Resuming with {len(processed_mbids)} processed artists, {len(queue)} in queue")

    return graph, artist_metadata, processed_mbids, queue


def save_state(processed_mbids: set, queue: deque, output_dir: str = "../data") -> None:
    """Save current state for resume capability."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    state_path = Path(output_dir) / "collection_state.json"
    state = {"processed_mbids": list(processed_mbids), "queue": list(queue)}
    with Path(state_path).open("w") as f:
        json.dump(state, f, indent=2)


def append_to_graph(node_id: str, connections: list, output_dir: str = "../data") -> None:
    """Append a node to the graph NDJSON file."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    graph_path = Path(output_dir) / "graph.ndjson"
    entry = {"id": node_id, "connections": connections}
    with Path(graph_path).open("a") as f:
        f.write(json.dumps(entry) + "\n")


def append_to_metadata(node_id: str, name: str, url: str, output_dir: str = "../data") -> None:
    """Append metadata to the NDJSON file."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    metadata_path = Path(output_dir) / "metadata.ndjson"
    entry = {"id": node_id, "name": name, "url": url}
    with Path(metadata_path).open("a") as f:
        f.write(json.dumps(entry) + "\n")
