"""Tests for postprocessing.cleaning — behavior of skeleton, segment_name,
_identify_duplicates, _identify_collabs, and compute_in_degrees."""

import orjson
import pytest

from postprocessing.cleaning import (
    _identify_collabs,
    _identify_duplicates,
    compute_in_degrees,
    segment_name,
    skeleton,
)


# ---------------------------------------------------------------------------
# skeleton
# ---------------------------------------------------------------------------


def test_skeleton_cyrillic_homoglyph_folded():
    # Cyrillic С (U+0421) looks like Latin C — must fold to 'c'
    assert skeleton("Сream") == "cream"


def test_skeleton_dot_becomes_space_and_collapses():
    assert skeleton("Taylor.Swift") == "taylor swift"


def test_skeleton_leading_bullet_stripped():
    assert skeleton("●Taylor  Swift") == "taylor swift"


def test_skeleton_ascii_fast_path_lowercased():
    assert skeleton("Hello World") == "hello world"


def test_skeleton_ascii_punct_becomes_space():
    assert skeleton("AC/DC") == "ac dc"


def test_skeleton_extra_whitespace_collapsed():
    assert skeleton("  foo   bar  ") == "foo bar"


def test_skeleton_empty_string():
    assert skeleton("") == ""


# ---------------------------------------------------------------------------
# segment_name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("feat_word", ["feat.", "feat", "ft", "featuring"])
def test_segment_name_splits_on_feat(feat_word):
    assert segment_name(f"a {feat_word} b") == ["a", "b"]


@pytest.mark.parametrize("input_", ["a, b", "a & b", "a / b", "a + b"])
def test_segment_name_splits_on_structural_delimiter(input_):
    assert segment_name(input_) == ["a", "b"]


def test_segment_name_no_split_on_x():
    assert segment_name("pharaoh x acid drop king") == ["pharaoh x acid drop king"]


def test_segment_name_single_word_no_split():
    assert segment_name("radiohead") == ["radiohead"]


def test_segment_name_preserves_internal_dot():
    assert segment_name("last past.") == ["last past."]


def test_segment_name_three_way_split():
    assert segment_name("a, b, c") == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# _identify_duplicates
# ---------------------------------------------------------------------------


def test_duplicates_empty_skel_key_skipped():
    # Symbol/emoji-only names (!!!, +/-, ✝✝✝) all normalise to "" — must not merge
    skel = {"": ["id1", "id2", "id3"]}
    name_of = {"id1": "!!!", "id2": "+/-", "id3": "✝✝✝"}
    in_deg = {"id1": 100, "id2": 50, "id3": 10}
    result = _identify_duplicates(skel, name_of, in_deg)
    assert result == set()


def test_duplicates_skel_drops_decoration_variant():
    # "Taylor.Swift" shares skeleton "taylor swift" with "Taylor Swift" → dropped
    skel = {"taylor swift": ["id1", "id2"]}
    name_of = {"id1": "Taylor Swift", "id2": "Taylor.Swift"}
    in_deg = {"id1": 100, "id2": 5}
    result = _identify_duplicates(skel, name_of, in_deg)
    assert result == {"id2"}


def test_duplicates_skel_canonical_not_dropped():
    skel = {"daft punk": ["id1", "id2"]}
    name_of = {"id1": "Daft Punk", "id2": "Daft.Punk"}
    in_deg = {"id1": 200, "id2": 3}
    result = _identify_duplicates(skel, name_of, in_deg)
    assert "id1" not in result


def test_duplicates_skel_identical_names_both_kept():
    # Two MBID-split nodes sharing the same raw name — neither dropped
    skel = {"john williams": ["id1", "id2"]}
    name_of = {"id1": "John Williams", "id2": "John Williams"}
    in_deg = {"id1": 50, "id2": 10}
    result = _identify_duplicates(skel, name_of, in_deg)
    assert result == set()


def test_duplicates_singleton_group_no_drops():
    skel = {"solo": ["id1"]}
    name_of = {"id1": "Solo"}
    in_deg = {"id1": 5}
    result = _identify_duplicates(skel, name_of, in_deg)
    assert result == set()


# ---------------------------------------------------------------------------
# _identify_collabs
# ---------------------------------------------------------------------------


def test_collabs_secondary_collab_dropped():
    phon = {
        "a": ["id_a"],
        "b": ["id_b"],
        "a, b": ["id_ab"],
    }
    in_deg = {"id_a": 100, "id_b": 80, "id_ab": 5}
    result = _identify_collabs(phon, in_deg, centrality_frac=0.2)
    assert result == {"id_ab"}


def test_collabs_central_node_kept():
    # in-degree of "a & b" >= 20 % of max member → treated as a real duo
    phon = {
        "a": ["id_a"],
        "b": ["id_b"],
        "a & b": ["id_ab"],
    }
    in_deg = {"id_a": 100, "id_b": 80, "id_ab": 90}
    result = _identify_collabs(phon, in_deg, centrality_frac=0.2)
    assert result == set()


def test_collabs_unknown_segment_keeps_node():
    # One segment is not a known artist → not a full decomposition → kept
    phon = {
        "a": ["id_a"],
        "a feat unknown": ["id_collab"],
    }
    in_deg = {"id_a": 100, "id_collab": 5}
    result = _identify_collabs(phon, in_deg, centrality_frac=0.2)
    assert result == set()


def test_collabs_single_segment_kept():
    # A multi-word name that produces only one segment cannot be a collab
    phon = {"solo artist": ["id1"]}
    in_deg = {"id1": 100}
    result = _identify_collabs(phon, in_deg, centrality_frac=0.2)
    assert result == set()


def test_collabs_all_ids_of_dropped_node_removed():
    # When a collab node has multiple IDs (e.g. MBID duplicates), all are dropped
    phon = {
        "a": ["id_a"],
        "b": ["id_b"],
        "a, b": ["id_ab1", "id_ab2"],
    }
    in_deg = {"id_a": 100, "id_b": 80, "id_ab1": 3, "id_ab2": 2}
    result = _identify_collabs(phon, in_deg, centrality_frac=0.2)
    assert result == {"id_ab1", "id_ab2"}


# ---------------------------------------------------------------------------
# compute_in_degrees
# ---------------------------------------------------------------------------


def test_compute_in_degrees_counts_incoming_edges(tmp_path):
    graph = tmp_path / "graph.ndjson"
    lines = [
        {"id": "n1", "connections": [["n2", 0.5], ["n3", 0.8]]},
        {"id": "n2", "connections": [["n3", 0.3]]},
    ]
    graph.write_bytes(b"\n".join(orjson.dumps(line) for line in lines))
    result = compute_in_degrees(graph)
    assert result["n2"] == 1
    assert result["n3"] == 2


def test_compute_in_degrees_source_node_absent(tmp_path):
    # A node that only points outward has no incoming edges — absent from result
    graph = tmp_path / "graph.ndjson"
    graph.write_bytes(orjson.dumps({"id": "n1", "connections": [["n2", 1.0]]}))
    result = compute_in_degrees(graph)
    assert "n1" not in result


def test_compute_in_degrees_empty_connections(tmp_path):
    graph = tmp_path / "graph.ndjson"
    graph.write_bytes(orjson.dumps({"id": "n1", "connections": []}))
    result = compute_in_degrees(graph)
    assert "n1" not in result
