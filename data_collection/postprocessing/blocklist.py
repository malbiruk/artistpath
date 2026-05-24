"""Sentinel name filter for postprocessing."""

from pathlib import Path

import orjson
from rich.progress import Progress

# Last.fm uses bracket-wrapped names as sentinels (e.g. "[unknown]" for
# unidentified artists on tracks/scrobbles). They pollute search and
# pathfinding with no semantic value.
BLOCKLISTED_NAMES: set[str] = {
    "[unknown]",
}


def identify_blocklisted_uuids(metadata_file: Path) -> set[str]:
    """Pre-scan metadata.ndjson and return UUIDs whose name is in BLOCKLISTED_NAMES."""
    blocked: set[str] = set()
    with metadata_file.open("rb") as f, Progress() as progress:
        task = progress.add_task("[yellow]Scanning for blocklisted names...", total=None)
        for raw_line in f:
            progress.advance(task)
            line = raw_line.strip()
            if not line:
                continue
            try:
                entry = orjson.loads(line)
                if entry["name"] in BLOCKLISTED_NAMES:
                    blocked.add(entry["id"])
            except (orjson.JSONDecodeError, KeyError):
                continue
    return blocked
