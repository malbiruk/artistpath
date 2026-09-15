"""Rewrite graph.ndjson keeping only each artist's last record.

The collector only appends, so a re-crawled artist leaves its previous record
in place and one refresh lap writes a second copy of the whole live set. This
reclaims that space.

It is the only destructive operation in the system, so it runs with the
collector stopped, builds its own survivor index against the file as it now
stands — the one postprocessing built is already stale, and compacting against
it would delete everything appended since — and proves the rewrite three ways
before the rename.

check_and_refresh.sh runs this last, after the bins are swapped and verified
healthy, and owns stopping and restarting the collector around it.
"""

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
from rich.progress import Progress

from collection.storage import GRAPH_ID_PREFIX
from postprocessing.graph import SurvivorIndex, build_survivor_index

GB = 1024**3

# Compaction holds both files at once, so it needs live_bytes free -- exact,
# not an estimate: the index knows what the file shrinks to. The margin on top
# only has to keep the box off zero for the minutes both files exist, since the
# caller drops graph.ndjson.old as soon as the collector is back up.
FREE_MARGIN = 10 * GB
_WRITE_BUFFER = 16 * 1024 * 1024

# systemctl reports `deactivating` for up to TimeoutStopSec while the collector
# finishes its batch, and that is precisely when it is still appending. So this
# lists the states that are safe rather than the ones that are not.
_STOPPED_STATES = frozenset({"inactive", "failed"})


def require_collector_stopped() -> None:
    """Nothing may append while the file is being rewritten: a record appended
    after the index was built is absent from it and would be dropped."""
    state = subprocess.run(
        ["systemctl", "--user", "is-active", "artistpath-collector.service"],
        capture_output=True,
        text=True,
        check=False,  # non-zero is how systemctl says "not active"
    ).stdout.strip()
    if state not in _STOPPED_STATES:
        raise SystemExit(
            f"artistpath-collector.service is {state!r}, not stopped; compaction "
            "would delete every record appended after the index was built."
        )


def require_unchanged(graph_file: Path, size_before: int) -> None:
    """Assert nothing has appended since the index was built.

    A record added after it is absent from the new file and would be lost at
    the rename - the one way compaction can destroy data that no output check
    can see, since verify_rewrite never re-reads the original. Append-only
    makes size a complete test rather than a heuristic.
    """
    require_collector_stopped()
    size_now = graph_file.stat().st_size
    if size_now != size_before:
        msg = (
            f"graph.ndjson grew from {size_before:,} to {size_now:,} bytes during "
            "compaction; refusing to replace it and lose what was appended"
        )
        raise RuntimeError(msg)


def read_expected_survivors(data_dir: Path) -> int | None:
    """The survivor count the last rebuild recorded, if there is one.

    Artists are only ever added to graph.ndjson, so this only ever grows. A
    fresh index finding fewer means two independent runs disagree about what
    the file holds, and that has to stop the rename: the alternative is finding
    out from a 10% shrink gate a day later, which cannot see a smaller loss.
    """
    try:
        return int((data_dir / "live_survivors.txt").read_text().strip())
    except (OSError, ValueError):
        return None


def write_survivors(graph_file: Path, index_path: Path, new_file: Path) -> None:
    """Copy each survivor's line to new_file in ascending offset order.

    A survivor's offset is the position of that artist's most recent record, so
    ascending offset is ascending last-crawled time: the compacted file comes
    out oldest-first, which is what makes resetting the sweep cursor to 0
    correct rather than merely convenient. It also makes this a forward sparse
    scan instead of random I/O.
    """
    offsets, lengths = np.load(index_path)
    with (
        graph_file.open("rb") as src,
        new_file.open("wb", buffering=_WRITE_BUFFER) as out,
        Progress() as progress,
    ):
        task = progress.add_task("[green]Writing survivors...", total=offsets.size)
        for pos, length in zip(offsets.tolist(), lengths.tolist()):
            src.seek(pos)
            line = src.read(length)
            # Every indexed offset starts a record by construction, so one that
            # does not means the file changed under us - the collector was
            # still running, or a stale index. Refuse rather than write it.
            if len(line) != length or not line.startswith(GRAPH_ID_PREFIX):
                msg = f"offset {pos} does not start a {length}-byte graph record"
                raise RuntimeError(msg)
            out.write(line)
            progress.advance(task)
        out.flush()
        os.fsync(out.fileno())


def verify_rewrite(index: SurvivorIndex, new_size: int, recheck: SurvivorIndex) -> None:
    """All three checks that must hold before anything destructive happens.

    The size is exact because the index already knows what the file shrinks to;
    the re-indexed count proves nothing was lost; and non_blank == count proves
    every line in the new file is a distinct survivor, i.e. no id survives
    twice. That last one is the actual evidence that supersession was applied.
    """
    if new_size != index.live_bytes:
        msg = f"new file is {new_size:,} bytes, index says {index.live_bytes:,}"
        raise RuntimeError(msg)
    if recheck.count != index.count:
        msg = f"new file re-indexes to {recheck.count:,} survivors, expected {index.count:,}"
        raise RuntimeError(msg)
    if recheck.non_blank != recheck.count:
        msg = (
            f"new file has {recheck.non_blank:,} non-blank lines but only "
            f"{recheck.count:,} survivors: supersession was not applied"
        )
        raise RuntimeError(msg)


def reset_refresh_offset(state_file: Path) -> None:
    """Point the sweep cursor back at the front of the compacted file.

    Done before the rename, so an interruption leaves a valid cursor on the
    intact old file - the sweep just re-laps from the front, which is wasteful
    and harmless. Everything else in the state is carried through untouched;
    zeroing crawled_total would drive check_and_refresh.sh's delta negative and
    silently stop rebuilds until the count caught up again.
    """
    if not state_file.exists():
        print("  no collection_state.json, nothing to reset")
        return
    state = json.loads(state_file.read_bytes())
    state["refresh_offset"] = 0
    tmp_path = state_file.with_suffix(".json.tmp")
    with tmp_path.open("w") as f:
        json.dump(state, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, state_file)


def compact(data_dir: Path) -> None:
    require_collector_stopped()

    graph_file = data_dir / "graph.ndjson"
    new_file = data_dir / "graph.ndjson.new"
    old_file = data_dir / "graph.ndjson.old"
    index_path = data_dir / "compaction-survivors.npy"
    new_index_path = data_dir / "compaction-survivors.new.npy"

    size_before = graph_file.stat().st_size
    print(f"📏 graph.ndjson: {size_before / GB:.1f} GB")

    try:
        print("\n🧭 Indexing survivors")
        index = build_survivor_index(graph_file, index_path)
        print(f"✅ {index.count:,} survivors, {index.live_bytes / GB:.1f} GB live")
        # Every verification below passes vacuously on an empty index (0 == 0
        # three times), so without this a file that indexed to nothing - all
        # lines torn inside the id, a read that came back empty - would be
        # replaced by a zero-byte one and call it a success.
        if index.count == 0:
            raise SystemExit("The survivor index is empty; refusing to replace graph.ndjson.")

        expected = read_expected_survivors(data_dir)
        if expected is not None and index.count < expected:
            raise SystemExit(
                f"Indexed {index.count:,} survivors but the last rebuild recorded "
                f"{expected:,}, and the count only grows; refusing to replace graph.ndjson."
            )

        free = shutil.disk_usage(data_dir).free
        needed = index.live_bytes + FREE_MARGIN
        if free < needed:
            raise SystemExit(
                f"Only {free / GB:.1f} GB free, need {needed / GB:.1f} GB to hold "
                f"the compacted file alongside the original."
            )

        print("\n📝 Writing graph.ndjson.new")
        write_survivors(graph_file, index_path, new_file)

        print("\n🔍 Verifying")
        recheck = build_survivor_index(new_file, new_index_path)
        verify_rewrite(index, new_file.stat().st_size, recheck)
        print(f"✅ {recheck.count:,} survivors, no id survives twice")

        # Before the reset as well as before the rename: this fires exactly when
        # a collector is running, and reset_refresh_offset read-modify-writes a
        # 286 MB state file - a save landing between our read and our replace
        # would be clobbered whole, queue and crawled_total with it, not just
        # the cursor. Refuse before touching it rather than after.
        require_unchanged(graph_file, size_before)

        print("\n↩️  Resetting refresh_offset")
        reset_refresh_offset(data_dir / "collection_state.json")

        # Again, with nothing left between it and the rename: the write above
        # took minutes and the entry guard was one point in time.
        require_unchanged(graph_file, size_before)

        # A hardlink rather than renaming the original out of the way first, so
        # graph.ndjson never stops existing. It is a backup against a logic bug
        # only -- sharing blocks with the original, it survives nothing the
        # original would not -- and the caller drops it once the collector is
        # back, rather than holding 60 GB across the day for that.
        old_file.unlink(missing_ok=True)
        os.link(graph_file, old_file)
        os.replace(new_file, graph_file)
    except BaseException:
        # Worthless bytes on a disk this exists to free, and the next run
        # rewrites it from scratch anyway. The original is untouched either way.
        new_file.unlink(missing_ok=True)
        raise
    finally:
        index_path.unlink(missing_ok=True)
        new_index_path.unlink(missing_ok=True)

    size_after = graph_file.stat().st_size
    reclaimed = (size_before - size_after) / size_before * 100
    print(
        f"\n✅ Compacted {size_before / GB:.1f} GB → {size_after / GB:.1f} GB "
        f"({reclaimed:.0f}% reclaimed), previous file kept as graph.ndjson.old"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("../data"),
        help="Directory holding graph.ndjson and collection_state.json (default: ../data)",
    )
    args = parser.parse_args()
    compact(args.data_dir)


if __name__ == "__main__":
    main()
