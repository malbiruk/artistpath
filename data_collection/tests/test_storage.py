"""Tests for collection state persistence."""

import json
import uuid
from collections import deque

import pytest

from collection.storage import load_names, save_state, scan_oldest_ids


def test_save_state_raising_mid_write_leaves_original_file_unchanged(tmp_path, monkeypatch):
    state_path = tmp_path / "collection_state.json"
    original = '{"processed_mbids": ["orig"], "queue": ["q"]}'
    state_path.write_text(original)

    def raising_dump(*args, **kwargs):
        raise ValueError("boom")

    monkeypatch.setattr("collection.storage.json.dump", raising_dump)

    with pytest.raises(ValueError):
        save_state({"new"}, deque(["x"]), str(tmp_path))

    assert state_path.read_text() == original


def test_save_state_round_trips_and_leaves_no_temp_file(tmp_path):
    save_state({"a", "b"}, deque(["c"]), str(tmp_path))

    state = json.loads((tmp_path / "collection_state.json").read_text())
    assert set(state["processed_mbids"]) == {"a", "b"}
    assert state["queue"] == ["c"]
    assert list(tmp_path.iterdir()) == [tmp_path / "collection_state.json"]


def test_load_names_skips_corrupt_lines(tmp_path):
    (tmp_path / "metadata.ndjson").write_text(
        '{"id": "1", "name": "First", "url": "u"}\n'
        "\x00\x00\x00\x00\n"
        '{"id": "2", "name": "Sec\n'
        '{"id": "3", "name": "Third", "url": "u"}\n'
    )

    assert load_names(str(tmp_path)) == {"1": "First", "3": "Third"}


def test_load_names_without_metadata_file(tmp_path):
    assert load_names(str(tmp_path)) == {}


def test_append_to_graph_writes_the_prefix_postprocessing_scans_for(tmp_path):
    from collection.storage import append_to_graph

    append_to_graph("abc", [("def", 0.5)], str(tmp_path))

    assert (tmp_path / "graph.ndjson").read_bytes().startswith(b'{"id": "abc", ')


def _graph_line(artist_id: str) -> str:
    return json.dumps({"id": artist_id, "connections": []}) + "\n"


def test_scan_oldest_ids_returns_ids_in_file_order(tmp_path):
    ids = [str(uuid.uuid4()) for _ in range(5)]
    (tmp_path / "graph.ndjson").write_text("".join(_graph_line(i) for i in ids))

    found, _ = scan_oldest_ids(str(tmp_path), 0, 5)

    assert found == ids


def test_scan_oldest_ids_second_call_continues_from_returned_offset_without_overlap(tmp_path):
    ids = [str(uuid.uuid4()) for _ in range(5)]
    (tmp_path / "graph.ndjson").write_text("".join(_graph_line(i) for i in ids))

    first, offset = scan_oldest_ids(str(tmp_path), 0, 3)
    second, _ = scan_oldest_ids(str(tmp_path), offset, 3)

    assert first + second == ids


def test_scan_oldest_ids_offset_at_eof_wraps_to_start(tmp_path):
    ids = [str(uuid.uuid4()) for _ in range(2)]
    graph_path = tmp_path / "graph.ndjson"
    graph_path.write_text("".join(_graph_line(i) for i in ids))
    eof_offset = graph_path.stat().st_size

    found, _ = scan_oldest_ids(str(tmp_path), eof_offset, 2)

    assert found == ids


def test_scan_oldest_ids_offset_past_shrunk_file_wraps_to_start(tmp_path):
    graph_path = tmp_path / "graph.ndjson"
    graph_path.write_text("".join(_graph_line(str(uuid.uuid4())) for _ in range(5)))
    stale_offset = graph_path.stat().st_size  # cursor from before a compaction

    compacted_id = str(uuid.uuid4())
    graph_path.write_text(_graph_line(compacted_id))  # file is now shorter than stale_offset

    found, _ = scan_oldest_ids(str(tmp_path), stale_offset, 5)

    assert found == [compacted_id]


def test_scan_oldest_ids_leaves_unterminated_final_line_for_the_next_scan(tmp_path):
    graph_path = tmp_path / "graph.ndjson"
    complete_id = str(uuid.uuid4())
    partial_id = str(uuid.uuid4())
    graph_path.write_text(_graph_line(complete_id) + _graph_line(partial_id).rstrip("\n"))

    found, offset = scan_oldest_ids(str(tmp_path), 0, 10)
    assert found == [complete_id]

    with graph_path.open("a") as f:
        f.write("\n")  # the collector finishes the append it was mid-way through
    found_next, _ = scan_oldest_ids(str(tmp_path), offset, 10)

    assert found_next == [partial_id]


def test_scan_oldest_ids_advances_past_a_line_with_an_unreadable_id(tmp_path):
    graph_path = tmp_path / "graph.ndjson"
    garbage_line = "not a graph record at all\n"
    valid_id = str(uuid.uuid4())
    graph_path.write_text(garbage_line + _graph_line(valid_id))

    found, offset = scan_oldest_ids(str(tmp_path), 0, 1)

    assert found == [valid_id]
    assert offset == graph_path.stat().st_size


def test_scan_oldest_ids_yields_only_the_visible_id_from_a_glued_line(tmp_path):
    # Simulates a truncated record with a second, complete record concatenated
    # onto it on one physical line (no newline between them).
    visible_id = str(uuid.uuid4())
    buried_id = str(uuid.uuid4())
    truncated_record = f'{{"id": "{visible_id}", "connections": [["some-trunc'
    glued_line = truncated_record + json.dumps({"id": buried_id, "connections": []}) + "\n"
    (tmp_path / "graph.ndjson").write_text(glued_line)

    found, _ = scan_oldest_ids(str(tmp_path), 0, 10)

    assert found == [visible_id]


def test_scan_oldest_ids_deduplicates_ids_within_one_scan(tmp_path):
    artist_id = str(uuid.uuid4())
    (tmp_path / "graph.ndjson").write_text(_graph_line(artist_id) * 2)

    found, _ = scan_oldest_ids(str(tmp_path), 0, 10)

    assert found == [artist_id]


def test_scan_oldest_ids_without_graph_file_returns_empty(tmp_path):
    assert scan_oldest_ids(str(tmp_path), 0, 10) == ([], 0)
