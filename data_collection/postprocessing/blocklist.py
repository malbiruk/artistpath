"""Sentinel name filter for postprocessing."""

import unicodedata
from pathlib import Path

import orjson
from rich.progress import Progress

# Last.fm uses bracket-wrapped names as sentinels (e.g. "[unknown]" for
# unidentified artists on tracks/scrobbles). They pollute search and
# pathfinding with no semantic value.
BLOCKLISTED_NAMES: set[str] = {
    "[unknown]",
}


def _has_no_visible_content(name: str) -> bool:
    """True if every character is whitespace, control, or format (so the name
    renders as nothing — e.g. a lone U+200E left-to-right mark)."""
    for c in name:
        if unicodedata.category(c)[0] not in ("C", "Z"):
            return False
    return True


def identify_blocklisted_uuids(metadata_file: Path) -> set[str]:
    """Pre-scan metadata.ndjson and return UUIDs to drop: exact-match against
    BLOCKLISTED_NAMES, plus any name with no visible content."""
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
                name = entry["name"]
                if name in BLOCKLISTED_NAMES or _has_no_visible_content(name):
                    blocked.add(entry["id"])
            except (orjson.JSONDecodeError, KeyError):
                continue
    return blocked
