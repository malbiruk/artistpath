"""Tests for postprocessing.graph.process_graph."""

import json
import struct
import uuid
from pathlib import Path

import pytest

from postprocessing.graph import process_graph

_RECORD_HEADER = struct.Struct("<16sI")
_EDGE = struct.Struct("<16sf")


def write_ndjson(path: Path, records: list) -> None:
    """Write dicts as NDJSON lines; raw strings are written verbatim (malformed lines)."""
    lines = [r if isinstance(r, str) else json.dumps(r) for r in records]
    path.write_text("\n".join(lines) + "\n")


def parse_bin(path: Path) -> dict[str, tuple[int, list[tuple[str, float]]]]:
    """Parse graph.bin/rev-graph.bin into {uuid_str: (offset, [(uuid_str, weight), ...])}."""
    data = path.read_bytes()
    out = {}
    pos = 0
    while pos < len(data):
        offset = pos
        key_bytes, count = _RECORD_HEADER.unpack_from(data, pos)
        pos += _RECORD_HEADER.size
        edges = []
        for _ in range(count):
            edge_bytes, weight = _EDGE.unpack_from(data, pos)
            pos += _EDGE.size
            edges.append((str(uuid.UUID(bytes=edge_bytes)), weight))
        out[str(uuid.UUID(bytes=key_bytes))] = (offset, edges)
    return out


@pytest.fixture
def ids() -> list[str]:
    return [str(uuid.uuid4()) for _ in range(6)]


def test_graph_bin_records_and_forward_index(tmp_path, ids):
    a, b, c = ids[:3]
    write_ndjson(
        tmp_path / "graph.ndjson",
        [
            {"id": a, "connections": [[b, 1.5], [c, 2.0]]},
            {"id": b, "connections": []},
        ],
    )

    result = process_graph(tmp_path / "graph.ndjson", tmp_path, None)
    parsed = parse_bin(tmp_path / "graph.bin")

    assert parsed[a][1] == [(b, pytest.approx(1.5)), (c, pytest.approx(2.0))]
    assert parsed[b][1] == []
    assert parsed[a][0] == result["forward_index"][a]
    assert parsed[b][0] == result["forward_index"][b]


def test_rev_graph_bin_groups_by_target_sorted_desc_stable(tmp_path, ids):
    a, b, c, t1, t2 = ids[:5]
    write_ndjson(
        tmp_path / "graph.ndjson",
        [
            {"id": a, "connections": [[t1, 1.0], [t2, 5.0]]},
            {"id": b, "connections": [[t1, 3.0]]},
            {"id": c, "connections": [[t1, 3.0]]},
        ],
    )

    result = process_graph(tmp_path / "graph.ndjson", tmp_path, None)
    parsed = parse_bin(tmp_path / "rev-graph.bin")

    # Descending weight, ties broken by encounter order (b before c).
    assert [src for src, _ in parsed[t1][1]] == [b, c, a]
    assert parsed[t2][1] == [(a, pytest.approx(5.0))]
    assert parsed[t1][0] == result["reverse_index"][t1]
    assert parsed[t2][0] == result["reverse_index"][t2]


def test_blocklist_removes_ids_as_both_source_and_target(tmp_path, ids):
    a, b, c = ids[:3]
    write_ndjson(
        tmp_path / "graph.ndjson",
        [
            {"id": a, "connections": [[b, 1.0], [c, 2.0]]},
            {"id": b, "connections": [[a, 1.0]]},
        ],
    )

    result = process_graph(
        tmp_path / "graph.ndjson", tmp_path, {b, "not-a-valid-uuid"}
    )

    parsed_fwd = parse_bin(tmp_path / "graph.bin")
    assert set(parsed_fwd) == {a}
    assert parsed_fwd[a][1] == [(c, pytest.approx(2.0))]

    parsed_rev = parse_bin(tmp_path / "rev-graph.bin")
    assert set(parsed_rev) == {c}
    assert result["artists"] == 1


def test_skips_malformed_lines_without_error(tmp_path, ids):
    a, b, torn_id = ids[:3]
    ndjson_path = tmp_path / "graph.ndjson"
    write_ndjson(
        ndjson_path,
        [
            json.dumps({"id": a, "connections": [[b, 1.0], ["not-a-uuid", 9.0]]}),
            "",
            json.dumps({"id": "not-a-uuid", "connections": []}),
            json.dumps({"id": b, "connections": []}),
            '{"id": "' + torn_id,  # truncated/unparseable last line
        ],
    )

    result = process_graph(ndjson_path, tmp_path, None)
    parsed = parse_bin(tmp_path / "graph.bin")

    assert set(parsed) == {a, b}
    assert parsed[a][1] == [(b, pytest.approx(1.0))]
    assert result["artists"] == 2


def test_no_temporary_files_remain_after_processing(tmp_path, ids):
    write_ndjson(tmp_path / "graph.ndjson", [{"id": ids[0], "connections": []}])

    process_graph(tmp_path / "graph.ndjson", tmp_path, None)

    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "graph.bin",
        "graph.ndjson",
        "rev-graph.bin",
    ]


def test_empty_connections_and_empty_blocklist_produce_zero_count_record(
    tmp_path, ids
):
    a = ids[0]
    write_ndjson(tmp_path / "graph.ndjson", [{"id": a, "connections": []}])

    result = process_graph(tmp_path / "graph.ndjson", tmp_path, set())

    assert parse_bin(tmp_path / "graph.bin")[a] == (0, [])
    assert parse_bin(tmp_path / "rev-graph.bin") == {}
    assert result["artists"] == 1
    assert result["forward_connections"] == 0


def test_reverse_pass_stops_at_the_forward_snapshot_boundary(tmp_path, monkeypatch):
    """Records appended after the chunk boundaries were computed (the collector
    keeps writing during a build) must not leak into the reverse graph."""
    import postprocessing.graph as graph_module

    src1, src2, tgt_early, tgt_late = (str(uuid.uuid4()) for _ in range(4))
    write_ndjson(tmp_path / "graph.ndjson", [{"id": src1, "connections": [[tgt_early, 0.5]]}])
    snapshot_size = (tmp_path / "graph.ndjson").stat().st_size
    with (tmp_path / "graph.ndjson").open("a") as f:
        f.write(json.dumps({"id": src2, "connections": [[tgt_late, 0.9]]}) + "\n")
    monkeypatch.setattr(graph_module, "_find_chunk_boundaries", lambda path, n: [0] + [snapshot_size] * n)

    stats = process_graph(tmp_path / "graph.ndjson", tmp_path)

    assert set(stats["forward_index"]) == {src1}
    assert set(stats["reverse_index"]) == {tgt_early}


def test_last_record_wins_for_recrawled_artists(tmp_path):
    src, old_target, new_target, other = (str(uuid.uuid4()) for _ in range(4))
    write_ndjson(
        tmp_path / "graph.ndjson",
        [
            {"id": src, "connections": [[old_target, 0.9], [other, 0.5]]},
            {"id": src, "connections": [[new_target, 0.8], [other, 0.5]]},
            '{"id": "%s", "connections": [["%s", 0.1' % (src, old_target),  # torn re-crawl: ignored
        ],
    )

    stats = process_graph(tmp_path / "graph.ndjson", tmp_path)

    forward = parse_bin(tmp_path / "graph.bin")
    reverse = parse_bin(tmp_path / "rev-graph.bin")
    assert list(forward) == [src]
    assert [t for t, _ in forward[src][1]] == [new_target, other]
    assert set(reverse) == {new_target, other}
    assert reverse[other][1] == [(src, 0.5)]  # not doubled
    assert stats["artists"] == 1


def test_blocked_mask_handles_ids_with_trailing_nul_bytes():
    import numpy as np
    from postprocessing.graph import _blocked_mask

    blocked = np.sort(np.array([b"ab" + b"\x00" * 14, b"\xff" * 15 + b"\x00"], dtype="S16"))
    ids = np.array([b"ab" + b"\x00" * 14, b"ab" + b"\x00" * 13 + b"\x01", b"\xff" * 16], dtype="S16")

    assert _blocked_mask(blocked, ids).tolist() == [True, False, False]
    assert _blocked_mask(np.array([], dtype="S16"), ids).tolist() == [False, False, False]
