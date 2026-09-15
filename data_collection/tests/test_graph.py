"""Tests for postprocessing.graph.process_graph."""

import json
import struct
import uuid
from pathlib import Path

import numpy as np
import pytest

import postprocessing.graph as graph_module
from postprocessing.graph import _chunk_bounds, build_survivor_index, process_graph

_RECORD_HEADER = struct.Struct("<16sI")
_EDGE = struct.Struct("<16sf")


def write_ndjson(path: Path, records: list) -> None:
    """Write dicts as NDJSON lines; raw strings are written verbatim (malformed lines)."""
    lines = [r if isinstance(r, str) else json.dumps(r) for r in records]
    path.write_text("\n".join(lines) + "\n")


def line_offsets(path: Path) -> list[int]:
    """Byte offset of every line in the file, in order."""
    offsets, pos = [], 0
    for line in path.read_bytes().splitlines(keepends=True):
        offsets.append(pos)
        pos += len(line)
    return offsets


def survivor_index(graph: Path, tmp_path: Path) -> tuple[list[int], list[int]]:
    """Build an index for `graph` and return its (offsets, lengths) as lists."""
    index_path = tmp_path / "survivors.npy"
    build_survivor_index(graph, index_path)
    offsets, lengths = np.load(index_path)
    return offsets.tolist(), lengths.tolist()


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


def test_both_passes_stop_at_the_snapshot_the_survivor_index_took(tmp_path):
    """Records appended after the survivor index was built (the collector keeps
    writing during a build) must not leak into either binary."""
    src1, src2, tgt_early, tgt_late = (str(uuid.uuid4()) for _ in range(4))
    graph = tmp_path / "graph.ndjson"
    write_ndjson(graph, [{"id": src1, "connections": [[tgt_early, 0.5]]}])
    index_path = tmp_path / "survivors.npy"
    build_survivor_index(graph, index_path)
    with graph.open("a") as f:
        f.write(json.dumps({"id": src2, "connections": [[tgt_late, 0.9]]}) + "\n")

    stats = process_graph(graph, tmp_path, survivor_index=index_path)

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


def test_survivor_index_drops_the_earlier_copy_of_a_recrawled_artist(tmp_path, ids):
    a, b = ids[:2]
    graph = tmp_path / "graph.ndjson"
    write_ndjson(
        graph,
        [
            {"id": a, "connections": []},
            {"id": b, "connections": []},
            {"id": a, "connections": [[b, 1.0]]},
        ],
    )

    offsets, lengths = survivor_index(graph, tmp_path)

    pos = line_offsets(graph)
    assert offsets == [pos[1], pos[2]]  # ascending, so still file order
    assert lengths == [pos[2] - pos[1], graph.stat().st_size - pos[2]]


def test_survivor_index_keeps_the_earlier_record_when_the_later_copy_is_torn(tmp_path, ids):
    a, b = ids[:2]
    graph = tmp_path / "graph.ndjson"
    write_ndjson(
        graph,
        [
            {"id": a, "connections": [[b, 1.0]]},
            '{"id": "%s", "connections": [["%s", 0.1' % (a, b),
        ],
    )

    offsets, _ = survivor_index(graph, tmp_path)

    assert offsets == [line_offsets(graph)[0]]


def test_survivor_index_skips_blank_lines(tmp_path, ids):
    graph = tmp_path / "graph.ndjson"
    write_ndjson(graph, ["", {"id": ids[0], "connections": []}, ""])

    offsets, _ = survivor_index(graph, tmp_path)

    assert offsets == [line_offsets(graph)[1]]


def test_glued_first_occurrence_is_indexed_but_never_emitted(tmp_path, ids):
    """The live file holds a truncated record with a whole record concatenated
    onto it. It carries a valid prefix, so it is indexed under the first id and
    then dropped by the worker's parse; the buried record stays invisible."""
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

    offsets, _ = survivor_index(graph, tmp_path)
    stats = process_graph(graph, tmp_path)

    assert offsets == line_offsets(graph)
    assert set(stats["forward_index"]) == {target}
    assert stats["reverse_index"] == {}


def test_survivor_index_rejects_a_file_whose_writer_changed_the_id_prefix(tmp_path, ids):
    """Prefix-mismatched lines are dropped from the build, so a writer switching
    to e.g. orjson's `{"id":` must fail the rebuild instead of silently
    shrinking the graph."""
    graph = tmp_path / "graph.ndjson"
    write_ndjson(graph, [f'{{"id":"{i}","connections":[]}}' for i in ids[:3]])

    with pytest.raises(RuntimeError, match="do not start with"):
        build_survivor_index(graph, tmp_path / "survivors.npy")


def test_survivor_index_tolerates_a_mismatched_line_below_the_epsilon(tmp_path, ids, monkeypatch):
    monkeypatch.setattr(graph_module, "_MAX_PREFIX_MISMATCH_FRAC", 0.5)
    graph = tmp_path / "graph.ndjson"
    write_ndjson(graph, ["not json at all", {"id": ids[0], "connections": []}])

    offsets, _ = survivor_index(graph, tmp_path)

    assert offsets == [line_offsets(graph)[1]]


def test_survivor_index_rejects_a_record_too_long_to_pack(tmp_path, ids, monkeypatch):
    """Offset and length share one int64, so a record that overflows the length
    field must stop the build rather than produce a corrupt offset."""
    monkeypatch.setattr(graph_module, "_MAX_RECORD_LEN", 32)
    graph = tmp_path / "graph.ndjson"
    write_ndjson(graph, [{"id": ids[0], "connections": []}])

    with pytest.raises(RuntimeError, match="too long"):
        build_survivor_index(graph, tmp_path / "survivors.npy")


def test_chunk_bounds_split_by_survivor_bytes_not_record_count():
    lengths = np.array([10, 10, 10, 10, 60, 10], dtype=np.int64)

    bounds = _chunk_bounds(lengths, 3)

    # 110 bytes over 3 chunks: the fat record is worth a whole chunk on its own
    chunk_bytes = [int(lengths[bounds[i] : bounds[i + 1]].sum()) for i in range(3)]
    assert chunk_bytes == [40, 60, 10]
    assert bounds[0] == 0 and bounds[-1] == lengths.size
    assert bounds == sorted(bounds)  # tiles the array, so no survivor is lost


def test_chunk_bounds_of_an_empty_index_are_all_empty():
    assert _chunk_bounds(np.array([], dtype=np.int64), 4) == [0, 0, 0, 0, 0]


def test_worker_accounts_for_every_survivor_assigned_to_it(tmp_path, ids, monkeypatch):
    """emitted + json + uuid + blocklist rejects == survivors assigned, the
    invariant the parent checks."""
    good, blocked, torn = ids[:3]
    monkeypatch.setattr(
        graph_module, "_BLOCKLIST", np.array([uuid.UUID(blocked).bytes], dtype="S16")
    )
    graph = tmp_path / "graph.ndjson"
    write_ndjson(
        graph,
        [
            {"id": good, "connections": []},
            {"id": "not-a-uuid", "connections": []},
            {"id": blocked, "connections": []},
            '{"id": "%s", "connections": [' % torn,
        ],
    )
    offsets, _ = survivor_index(graph, tmp_path)

    size, forward_ids, rejects = graph_module._process_forward_chunk(
        str(graph), np.array(offsets, dtype=np.int64), str(tmp_path / "chunk.bin")
    )

    assert [i for i, _ in forward_ids] == [good]
    assert rejects == (1, 1, 1)  # json, uuid, blocklist
    assert len(forward_ids) + sum(rejects) == len(offsets)
    assert size == (tmp_path / "chunk.bin").stat().st_size
