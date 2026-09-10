"""Tests for collection state persistence."""

import json
from collections import deque

import pytest

from collection.storage import load_names, save_state


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
