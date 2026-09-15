"""Tests for run_compaction: the only destructive pass over graph.ndjson."""

import json
import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import run_compaction
from postprocessing.graph import SurvivorIndex, build_survivor_index


def write_ndjson(path: Path, records: list) -> None:
    """Write dicts as NDJSON lines; raw strings are written verbatim (malformed lines)."""
    lines = [r if isinstance(r, str) else json.dumps(r) for r in records]
    path.write_text("\n".join(lines) + "\n")


# Captured before the autouse fixture replaces them on the module.
real_collector_guard = run_compaction.require_collector_stopped
REAL_FREE_MARGIN = run_compaction.FREE_MARGIN


def stub_systemctl(monkeypatch, status: str) -> None:
    """Stubs subprocess.run process-wide, so only the two guard tests use it."""
    monkeypatch.setattr(
        run_compaction.subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess([], 0, stdout=f"{status}\n", stderr=""),
    )


@pytest.fixture(autouse=True)
def compactable(monkeypatch):
    """Never consult the real service: the live collector is usually running and
    no test may act on what it says. FREE_MARGIN is sized for the 1 TB disk this
    runs on, which tmp_path on a small tmpfs would never satisfy."""
    monkeypatch.setattr(run_compaction, "require_collector_stopped", lambda: None)
    monkeypatch.setattr(run_compaction, "FREE_MARGIN", 0)


@pytest.fixture
def ids() -> list[str]:
    return [str(uuid.uuid4()) for _ in range(6)]


def lines(path: Path) -> list[bytes]:
    return path.read_bytes().splitlines(keepends=True)


def ids_in(path: Path) -> list[str]:
    return [json.loads(line)["id"] for line in lines(path)]


def test_superseded_records_are_dropped_and_the_last_one_survives(tmp_path, ids):
    a, b, old_target, new_target = ids[:4]
    graph = tmp_path / "graph.ndjson"
    write_ndjson(
        graph,
        [
            {"id": a, "connections": [[old_target, 0.9]]},
            {"id": b, "connections": []},
            {"id": a, "connections": [[new_target, 0.8]]},
        ],
    )
    original = lines(graph)

    run_compaction.compact(tmp_path)

    assert ids_in(graph) == [b, a]
    assert lines(graph) == [original[1], original[2]]


def test_survivors_are_written_oldest_first(tmp_path, ids):
    """A survivor's offset is where that artist was last crawled, so ascending
    offset is ascending staleness: offset 0 of the compacted file is the oldest
    surviving record, which is what makes resetting the cursor to 0 correct."""
    a, b, c = ids[:3]
    graph = tmp_path / "graph.ndjson"
    write_ndjson(
        graph,
        [
            {"id": a, "connections": []},  # superseded below, so a is the newest
            {"id": b, "connections": []},
            {"id": c, "connections": []},
            {"id": a, "connections": [[b, 1.0]]},
        ],
    )

    run_compaction.compact(tmp_path)

    assert ids_in(graph) == [b, c, a]


def test_a_torn_recrawl_does_not_supersede_the_record_it_follows(tmp_path, ids):
    a, b = ids[:2]
    graph = tmp_path / "graph.ndjson"
    write_ndjson(
        graph,
        [
            {"id": a, "connections": [[b, 1.0]]},
            '{"id": "%s", "connections": [["%s", 0.1' % (a, b),
        ],
    )
    original = lines(graph)

    run_compaction.compact(tmp_path)

    assert lines(graph) == [original[0]]


def test_a_glued_line_is_carried_through_as_the_torn_ids_survivor(tmp_path, ids):
    """The live file holds a truncated record with a whole record concatenated
    onto it. build_survivor_index indexes it under the first id and leaves the
    buried one invisible; compaction copies it verbatim rather than trying to
    repair it, so nothing a reader can see changes."""
    torn, buried, target = ids[:3]
    graph = tmp_path / "graph.ndjson"
    glued = '{"id": "%s", "connections": [["%s", 0.5' % (torn, target)
    write_ndjson(
        graph,
        [
            glued + json.dumps({"id": buried, "connections": [[target, 0.9]]}),
            {"id": target, "connections": []},
        ],
    )
    original = lines(graph)

    run_compaction.compact(tmp_path)

    assert lines(graph) == original


def test_blank_and_unreadable_lines_are_dropped(tmp_path, ids):
    graph = tmp_path / "graph.ndjson"
    write_ndjson(graph, ["", {"id": ids[0], "connections": []}, '{"id": "trunc'])
    original = lines(graph)

    run_compaction.compact(tmp_path)

    assert lines(graph) == [original[1]]


# --- verification ----------------------------------------------------------


def double_index(monkeypatch, doctor):
    """Let the re-index report something the first index disagrees with."""
    real = build_survivor_index
    calls = []

    def wrapped(graph_file, index_path):
        result = real(graph_file, index_path)
        calls.append(result)
        return doctor(result) if len(calls) == 2 else result

    monkeypatch.setattr(run_compaction, "build_survivor_index", wrapped)


def short_write(monkeypatch):
    """Lose a byte on the way out, so the new file is not the size the index says."""
    real = run_compaction.write_survivors

    def wrapped(graph_file, index_path, new_file):
        real(graph_file, index_path, new_file)
        with new_file.open("r+b") as f:
            f.truncate(new_file.stat().st_size - 1)

    monkeypatch.setattr(run_compaction, "write_survivors", wrapped)


@pytest.mark.parametrize(
    "break_it, match",
    [
        (short_write, "index says"),
        (lambda m: double_index(m, lambda r: r._replace(count=r.count + 1)), "re-indexes to"),
        (
            lambda m: double_index(m, lambda r: r._replace(non_blank=r.non_blank + 1)),
            "supersession was not applied",
        ),
    ],
    ids=["size", "survivor_count", "duplicate_id"],
)
def test_a_failed_verification_leaves_the_original_untouched(
    tmp_path, ids, monkeypatch, break_it, match
):
    a, b = ids[:2]
    graph = tmp_path / "graph.ndjson"
    write_ndjson(
        graph,
        [
            {"id": a, "connections": [[b, 1.0]]},
            {"id": b, "connections": []},
            {"id": a, "connections": []},
        ],
    )
    (tmp_path / "collection_state.json").write_text(json.dumps({"refresh_offset": 42}))
    before = graph.read_bytes()
    break_it(monkeypatch)

    with pytest.raises(RuntimeError, match=match):
        run_compaction.compact(tmp_path)

    assert graph.read_bytes() == before
    assert not (tmp_path / "graph.ndjson.old").exists()
    assert not (tmp_path / "graph.ndjson.new").exists()
    assert not list(tmp_path.glob("*.npy"))  # the finally clause runs on this path too
    # The cursor reset comes after verification, so it has not run either.
    assert json.loads((tmp_path / "collection_state.json").read_text())["refresh_offset"] == 42


def test_verify_rewrite_accepts_a_clean_compaction():
    """Non-blank lines exceeding survivors is normal for the file being read;
    only the file being written has to have one line per survivor."""
    run_compaction.verify_rewrite(SurvivorIndex(3, 300, 5), 300, SurvivorIndex(3, 300, 3))


@pytest.mark.parametrize(
    "new_size, recheck, match",
    [
        (299, SurvivorIndex(3, 299, 3), "index says"),
        (300, SurvivorIndex(2, 300, 2), "re-indexes to"),
        # Unreachable while the two above hold for whole-record output, which is
        # the point: it is the backstop that catches a rewrite whose line
        # boundaries stopped matching its record boundaries.
        (300, SurvivorIndex(3, 300, 4), "supersession was not applied"),
    ],
    ids=["size", "survivor_count", "duplicate_id"],
)
def test_verify_rewrite_rejects_each_way_a_rewrite_can_be_wrong(new_size, recheck, match):
    with pytest.raises(RuntimeError, match=match):
        run_compaction.verify_rewrite(SurvivorIndex(3, 300, 5), new_size, recheck)


def test_write_survivors_refuses_an_offset_that_is_not_a_record(tmp_path, ids):
    """A stale index means the file changed under us — a collector that was
    still running, a truncated file. Writing it out would be silent loss."""
    graph = tmp_path / "graph.ndjson"
    write_ndjson(graph, [{"id": ids[0], "connections": []}, {"id": ids[1], "connections": []}])
    index_path = tmp_path / "survivors.npy"
    build_survivor_index(graph, index_path)
    write_ndjson(graph, [{"id": ids[0], "connections": []}])  # second record gone

    with pytest.raises(RuntimeError, match="does not start a"):
        run_compaction.write_survivors(graph, index_path, tmp_path / "out.ndjson")


# --- refusals --------------------------------------------------------------


def test_the_disk_preflight_refuses_when_free_space_is_short(tmp_path, ids, monkeypatch):
    graph = tmp_path / "graph.ndjson"
    write_ndjson(graph, [{"id": ids[0], "connections": []}])
    before = graph.read_bytes()
    monkeypatch.setattr(run_compaction, "FREE_MARGIN", 40 * run_compaction.GB)
    monkeypatch.setattr(
        run_compaction.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(free=39 * run_compaction.GB),
    )

    with pytest.raises(SystemExit, match="free"):
        run_compaction.compact(tmp_path)

    assert graph.read_bytes() == before
    assert not (tmp_path / "graph.ndjson.new").exists()


def test_it_refuses_to_run_while_the_collector_is_active(tmp_path, ids, monkeypatch):
    graph = tmp_path / "graph.ndjson"
    write_ndjson(graph, [{"id": ids[0], "connections": []}, {"id": ids[0], "connections": []}])
    before = graph.read_bytes()
    monkeypatch.setattr(run_compaction, "require_collector_stopped", real_collector_guard)
    stub_systemctl(monkeypatch, "active")

    with pytest.raises(SystemExit, match="active"):
        run_compaction.compact(tmp_path)

    assert graph.read_bytes() == before


@pytest.mark.parametrize(
    "state, stopped",
    [
        ("inactive", True),
        ("failed", True),
        ("active", False),
        # Reported for up to TimeoutStopSec while the collector finishes its
        # batch, which is exactly when it is still appending.
        ("deactivating", False),
        ("activating", False),
        ("", False),
    ],
)
def test_the_collector_guard_proceeds_only_when_the_unit_is_fully_stopped(
    monkeypatch, state, stopped
):
    stub_systemctl(monkeypatch, state)

    if stopped:
        real_collector_guard()
    else:
        with pytest.raises(SystemExit, match="not stopped"):
            real_collector_guard()


def test_it_refuses_an_empty_survivor_index(tmp_path, monkeypatch):
    """Every verification passes vacuously at zero survivors, so nothing below
    would stop a file that indexed to nothing from being installed empty."""
    graph = tmp_path / "graph.ndjson"
    graph.write_bytes(b'{"id": "torn-inside-the-id\n')
    before = graph.read_bytes()

    with pytest.raises(SystemExit, match="empty"):
        run_compaction.compact(tmp_path)

    assert graph.read_bytes() == before
    assert not (tmp_path / "graph.ndjson.new").exists()


# --- state and bookkeeping -------------------------------------------------


def test_the_sweep_cursor_is_reset_and_the_rest_of_the_state_is_preserved(tmp_path, ids):
    write_ndjson(tmp_path / "graph.ndjson", [{"id": ids[0], "connections": []}])
    state = {
        "processed_mbids": [ids[1], ids[2], ids[0]],
        "queue": [ids[3], ids[4]],
        "refresh_queue": [ids[5]],
        "refresh_offset": 987_654_321,
        "crawled_total": 6_200_000,
    }
    state_file = tmp_path / "collection_state.json"
    state_file.write_text(json.dumps(state))

    run_compaction.compact(tmp_path)

    assert json.loads(state_file.read_text()) == {**state, "refresh_offset": 0}
    assert not (tmp_path / "collection_state.json.tmp").exists()


def test_an_interruption_before_the_rename_leaves_a_valid_cursor_on_the_old_file(
    tmp_path, ids, monkeypatch
):
    """The documented failure mode, and the reason the reset comes before the
    rename rather than after: cursor 0 against an intact old file just makes
    the sweep re-lap from the front. Wasteful, harmless."""
    graph = tmp_path / "graph.ndjson"
    write_ndjson(graph, [{"id": ids[0], "connections": []}, {"id": ids[0], "connections": []}])
    (tmp_path / "collection_state.json").write_text(json.dumps({"refresh_offset": 42}))
    before = graph.read_bytes()
    monkeypatch.setattr(run_compaction.os, "link", lambda *a: 1 / 0)

    with pytest.raises(ZeroDivisionError):
        run_compaction.compact(tmp_path)

    assert graph.read_bytes() == before
    assert json.loads((tmp_path / "collection_state.json").read_text())["refresh_offset"] == 0
    assert not (tmp_path / "graph.ndjson.new").exists()


def test_the_previous_file_is_kept_as_old(tmp_path, ids):
    graph = tmp_path / "graph.ndjson"
    write_ndjson(graph, [{"id": ids[0], "connections": []}, {"id": ids[0], "connections": []}])
    before = graph.read_bytes()

    run_compaction.compact(tmp_path)

    assert (tmp_path / "graph.ndjson.old").read_bytes() == before
    assert graph.read_bytes() != before


def test_a_second_compaction_replaces_the_previous_old_file(tmp_path, ids):
    graph = tmp_path / "graph.ndjson"
    write_ndjson(graph, [{"id": ids[0], "connections": []}, {"id": ids[0], "connections": []}])
    run_compaction.compact(tmp_path)
    compacted = graph.read_bytes()

    run_compaction.compact(tmp_path)

    assert (tmp_path / "graph.ndjson.old").read_bytes() == compacted
    assert graph.read_bytes() == compacted


def test_no_index_files_are_left_behind(tmp_path, ids):
    write_ndjson(tmp_path / "graph.ndjson", [{"id": ids[0], "connections": []}])

    run_compaction.compact(tmp_path)

    assert sorted(p.name for p in tmp_path.iterdir()) == ["graph.ndjson", "graph.ndjson.old"]


def test_a_final_line_without_a_newline_is_left_behind(tmp_path, ids):
    """A record with no trailing newline is one the collector had not finished
    appending, whatever its id parses to. Carrying it through would end the
    compacted file mid-record and the next append would glue onto it, losing
    both. The collector re-crawls it within a lap."""
    a, b = ids[:2]
    graph = tmp_path / "graph.ndjson"
    complete = json.dumps({"id": a, "connections": []})
    torn_tail = json.dumps({"id": b, "connections": []})  # no trailing newline
    graph.write_bytes((complete + "\n" + torn_tail).encode())

    run_compaction.compact(tmp_path)

    assert graph.read_bytes() == (complete + "\n").encode()
    assert ids_in(graph) == [a]


def test_a_torn_tail_is_dropped_and_the_newline_comes_back(tmp_path, ids):
    """A crash can truncate the record being appended. It does not supersede,
    so the earlier complete record survives and the compacted file ends with a
    newline again -- compaction repairs this tail rather than carrying it."""
    a = ids[0]
    graph = tmp_path / "graph.ndjson"
    complete = json.dumps({"id": a, "connections": []})
    graph.write_bytes((complete + "\n" + '{"id": "%s", "connections": [' % a).encode())

    run_compaction.compact(tmp_path)

    assert graph.read_bytes() == (complete + "\n").encode()


# --- input-side guards ------------------------------------------------------
#
# The three output checks never re-read the original, so they are blind to the
# file changing underneath. These are the guards that close that.


def append_during_write(monkeypatch, record: str) -> None:
    """A collector started by hand mid-write. Its record is absent from the
    index built before it, so the rename would drop it and no output check
    could tell."""
    real = run_compaction.write_survivors

    def wrapped(graph_file, index_path, new_file):
        real(graph_file, index_path, new_file)
        with graph_file.open("a") as f:
            f.write(record + "\n")

    monkeypatch.setattr(run_compaction, "write_survivors", wrapped)


def test_it_refuses_when_graph_ndjson_grew_during_the_write(tmp_path, ids, monkeypatch):
    a, b, late = ids[:3]
    graph = tmp_path / "graph.ndjson"
    write_ndjson(graph, [{"id": a, "connections": []}, {"id": b, "connections": []}])
    appended = json.dumps({"id": late, "connections": []})
    expected = graph.read_bytes() + (appended + "\n").encode()
    (tmp_path / "collection_state.json").write_text(json.dumps({"refresh_offset": 42}))
    append_during_write(monkeypatch, appended)

    with pytest.raises(RuntimeError, match="grew from"):
        run_compaction.compact(tmp_path)

    # Everything survives, the late append included -- that is the whole point.
    assert graph.read_bytes() == expected
    assert not (tmp_path / "graph.ndjson.old").exists()
    assert not (tmp_path / "graph.ndjson.new").exists()
    # Untouched: the guard runs before the reset too, because a refusal means a
    # collector is running and rewriting its 286 MB state file underneath one
    # would clobber a concurrent save whole, not just the cursor.
    assert json.loads((tmp_path / "collection_state.json").read_text())["refresh_offset"] == 42


def test_the_collector_is_re_checked_immediately_before_the_rename(tmp_path, ids, monkeypatch):
    """Passing at entry proves nothing: the write takes minutes."""
    graph = tmp_path / "graph.ndjson"
    write_ndjson(graph, [{"id": ids[0], "connections": []}, {"id": ids[0], "connections": []}])
    before = graph.read_bytes()
    calls = []

    def guard():
        calls.append(1)
        if len(calls) > 1:
            raise SystemExit("artistpath-collector.service is 'active', not stopped")

    monkeypatch.setattr(run_compaction, "require_collector_stopped", guard)

    with pytest.raises(SystemExit, match="not stopped"):
        run_compaction.compact(tmp_path)

    assert len(calls) == 2
    assert graph.read_bytes() == before
    assert not (tmp_path / "graph.ndjson.old").exists()
    assert not (tmp_path / "graph.ndjson.new").exists()


@pytest.mark.parametrize(
    "recorded, refuses",
    [
        ("3", True),  # more than the file holds: two runs disagree about it
        ("2", False),  # equal
        ("1", False),  # lower: an artist was discovered since the rebuild
        (None, False),  # no rebuild has recorded one yet
        ("", False),  # half-written
        ("not a number", False),
    ],
    ids=["above", "equal", "below", "absent", "empty", "junk"],
)
def test_the_survivor_count_may_not_fall_below_the_last_rebuilds(
    tmp_path, ids, recorded, refuses
):
    a, b = ids[:2]
    graph = tmp_path / "graph.ndjson"
    write_ndjson(graph, [{"id": a, "connections": []}, {"id": b, "connections": []}])
    before = graph.read_bytes()
    if recorded is not None:
        (tmp_path / "live_survivors.txt").write_text(recorded + "\n")

    if not refuses:
        run_compaction.compact(tmp_path)
        assert ids_in(graph) == [a, b]
        return

    with pytest.raises(SystemExit, match="only grows"):
        run_compaction.compact(tmp_path)
    assert graph.read_bytes() == before
    assert not (tmp_path / "graph.ndjson.new").exists()


def test_the_disk_preflight_needs_live_bytes_plus_the_real_margin(tmp_path, ids, monkeypatch):
    """The rest of the suite runs with FREE_MARGIN zeroed so tmp_path on a small
    tmpfs can satisfy it; this one pins the arithmetic with the real constant,
    and that it is the live set being reserved for, not the file size."""
    a, b = ids[:2]
    graph = tmp_path / "graph.ndjson"
    write_ndjson(
        graph,
        [
            {"id": a, "connections": [[b, 1.0]]},  # superseded two lines down
            {"id": b, "connections": []},
            {"id": a, "connections": []},
        ],
    )
    before = graph.read_bytes()
    live_bytes = sum(len(line) for line in lines(graph)[1:])
    assert live_bytes < graph.stat().st_size  # the margin sits on the live set
    assert REAL_FREE_MARGIN == 10 * run_compaction.GB
    needed = live_bytes + REAL_FREE_MARGIN
    free = [needed - 1]
    monkeypatch.setattr(run_compaction, "FREE_MARGIN", REAL_FREE_MARGIN)
    monkeypatch.setattr(
        run_compaction.shutil, "disk_usage", lambda path: SimpleNamespace(free=free[0])
    )

    with pytest.raises(SystemExit, match="free"):
        run_compaction.compact(tmp_path)
    assert graph.read_bytes() == before

    free[0] = needed
    run_compaction.compact(tmp_path)

    assert graph.stat().st_size == live_bytes


def corrupt_index_lengths(monkeypatch, shrink: int, delta: int, grow: int | None = None) -> None:
    """Take `delta` bytes off one survivor's recorded length, optionally giving
    them to another so the index still sums to live_bytes."""
    real = run_compaction.write_survivors

    def wrapped(graph_file, index_path, new_file):
        index = np.load(index_path)
        index[1][shrink] -= delta
        if grow is not None:
            index[1][grow] += delta
        np.save(index_path, index)
        real(graph_file, index_path, new_file)

    monkeypatch.setattr(run_compaction, "write_survivors", wrapped)


@pytest.mark.parametrize(
    "delta, grow, match",
    [
        # Uncompensated, so the output is simply short: check 1.
        (20, None, "index says"),
        # Compensated, so the lengths still sum right and check 1 is blind to
        # it. Survivor 0 loses its newline and survivor 1 glues onto it, so a
        # line goes missing: check 2.
        (20, 1, "re-indexes to"),
        # Same, but survivor 1's over-read is too short to carry a whole id, so
        # the fragment it leaves in front of survivor 2 makes that line start
        # `{"id"{"id": "` -- caught a step earlier, by the prefix guard the
        # postprocessing spec put there for a drifting writer.
        (1, 1, "do not start with"),
    ],
    ids=["uncompensated", "glued_records", "one_byte_shift"],
)
def test_a_mis_sized_index_entry_is_caught_before_the_rename(
    tmp_path, ids, monkeypatch, delta, grow, match
):
    """A wrong length cannot corrupt a record -- records are copied verbatim --
    but it can truncate one so the next glues onto it, and no count of the
    output bytes alone would see that."""
    graph = tmp_path / "graph.ndjson"
    write_ndjson(graph, [{"id": i, "connections": [[ids[0], 1.0]]} for i in ids[:4]])
    before = graph.read_bytes()
    corrupt_index_lengths(monkeypatch, shrink=0, delta=delta, grow=grow)

    with pytest.raises(RuntimeError, match=match):
        run_compaction.compact(tmp_path)

    assert graph.read_bytes() == before
    assert not (tmp_path / "graph.ndjson.old").exists()
    assert not (tmp_path / "graph.ndjson.new").exists()
