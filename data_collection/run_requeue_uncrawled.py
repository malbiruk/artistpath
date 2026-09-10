"""One-off repair: re-queue processed artists that have no graph.ndjson record.

Until 2026-09-08 the collector marked an artist processed even when its name
lookup failed, which it did for every UUID5 artist discovered after a corrupt
metadata line, so tens of thousands were never actually crawled. Artists that
genuinely have no similar artists are re-queued too; re-crawling them is cheap
and postprocessing keeps only the last record per artist.

Stop the collector first: this rewrites collection_state.json.
"""

import json
import subprocess
from collections import deque
from pathlib import Path

from collection.storage import save_state

DATA_DIR = Path("../data")


def crawled_ids(graph_file: Path) -> set[str]:
    ids: set[str] = set()
    with graph_file.open("rb") as f:
        for line in f:
            if line.startswith(b'{"id": "'):
                ids.add(line[8 : line.find(b'"', 8)].decode())
    return ids


def main() -> None:
    active = subprocess.run(
        ["systemctl", "--user", "is-active", "artistpath-collector.service"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    if active == "active":
        raise SystemExit("Stop artistpath-collector.service first; it would overwrite the state.")

    state = json.loads((DATA_DIR / "collection_state.json").read_bytes())
    processed = set(state["processed_mbids"])
    queue = deque(state["queue"])
    uncrawled = processed - crawled_ids(DATA_DIR / "graph.ndjson")
    print(f"{len(processed):,} processed, {len(uncrawled):,} without a graph record")

    queued = set(queue)
    for artist_id in sorted(uncrawled):
        if artist_id not in queued:
            queue.appendleft(artist_id)
    processed -= uncrawled
    save_state(processed, queue, str(DATA_DIR))
    print(f"Saved: {len(processed):,} processed, {len(queue):,} queued")


if __name__ == "__main__":
    main()
