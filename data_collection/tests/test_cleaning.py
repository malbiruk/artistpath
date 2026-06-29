"""Tests for postprocessing.cleaning — behavior of skeleton, segment_name,
_identify_duplicates, _identify_collabs, and compute_in_degrees."""

import orjson
import pytest

from postprocessing.cleaning import (
    _collab_member_keys,
    _decompose,
    _identify_collabs,
    _identify_duplicates,
    _member_cooccurrence,
    _real_band_shape,
    compute_in_degrees,
    fold_x_connectors,
    member_adjacency,
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


@pytest.mark.parametrize(
    "input_,expected",
    [
        ("pharaoh x acid drop king", ["pharaoh", "acid drop king"]),
        ("a x b x c", ["a", "b", "c"]),
    ],
)
def test_segment_name_splits_on_x(input_, expected):
    assert segment_name(input_) == expected


def test_segment_name_boundary_x_not_a_collab():
    # "X Japan" / "X Ambassadors": a leading/trailing "x" yields a single segment,
    # so the node never decomposes into >=2 known artists and is kept.
    assert segment_name("x japan") == ["japan"]


def test_segment_name_single_word_no_split():
    assert segment_name("radiohead") == ["radiohead"]


def test_segment_name_preserves_internal_dot():
    assert segment_name("last past.") == ["last past."]


def test_segment_name_three_way_split():
    assert segment_name("a, b, c") == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# fold_x_connectors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("x_char", ["х", "Х", "χ", "Χ"])
def test_fold_x_connectors_standalone_lookalike_becomes_x(x_char):
    assert fold_x_connectors(f"PHARAOH {x_char} BOULEVARD") == "PHARAOH x BOULEVARD"


def test_fold_x_connectors_word_internal_lookalike_untouched():
    # A "х" inside a word is never a join — leave it for unidecode to romanize.
    assert fold_x_connectors("Мах") == "Мах"


def test_fold_x_connectors_ascii_unchanged():
    assert fold_x_connectors("a x b") == "a x b"


def test_fold_x_connectors_feeds_the_segmenter():
    assert segment_name(fold_x_connectors("foo Х bar")) == ["foo", "bar"]


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


def test_collabs_feature_marker_dropped_despite_centrality():
    # "a feat b" is a hub (in-degree above both members), but a feat/ft marker
    # means it is a credit → dropped regardless of the centrality gate
    phon = {
        "a": ["id_a"],
        "b": ["id_b"],
        "a feat b": ["id_ab"],
    }
    in_deg = {"id_a": 100, "id_b": 80, "id_ab": 500}
    result = _identify_collabs(phon, in_deg, centrality_frac=0.2)
    assert result == {"id_ab"}


def test_collabs_x_pair_marker_still_centrality_gated():
    # "x" is not a feature marker → a central "a x b" survives the gate (kept)
    phon = {"a": ["id_a"], "b": ["id_b"], "a x b": ["id_ab"]}
    in_deg = {"id_a": 100, "id_b": 80, "id_ab": 90}
    result = _identify_collabs(phon, in_deg, centrality_frac=0.2)
    assert result == set()


def test_collabs_x_pair_marker_secondary_dropped():
    # a secondary "a x b" is still dropped by centrality
    phon = {"a": ["id_a"], "b": ["id_b"], "a x b": ["id_ab"]}
    in_deg = {"id_a": 100, "id_b": 80, "id_ab": 5}
    result = _identify_collabs(phon, in_deg, centrality_frac=0.2)
    assert result == {"id_ab"}


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
# member co-occurrence gate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "comps,expected",
    [
        (["bob marley", "the wailers"], True),   # "the ..." backing band
        (["ac", "dc"], True),                    # <=2-char fragments
        (["pharaoh", "jeembo"], False),          # ordinary collaborators
    ],
)
def test_real_band_shape(comps, expected):
    assert _real_band_shape(comps) is expected


def test_decompose_members_and_feature_flag():
    known = {"foo", "bar"}
    assert _decompose("foo & bar", known) == (["foo", "bar"], False)
    assert _decompose("foo feat bar", known) == (["foo", "bar"], True)
    assert _decompose("foo ft. bar", known) == (["foo", "bar"], True)
    assert _decompose("foo x bar", known) == (["foo", "bar"], False)  # x is not a feature marker
    assert _decompose("foo", known) is None                # single token
    assert _decompose("foo & unknown", known) is None      # 'unknown' not a known member


def test_decompose_feature_flag_matches_split_with_glued_punctuation():
    # has_feat comes from the same tokenization as the split, so a glued marker
    # ("x/feat") is detected even though it would dodge a whitespace-only scan
    known = {"foo", "bar"}
    assert _decompose("foo x/feat bar", known) == (["foo", "bar"], True)


def test_collab_member_keys_is_union_of_candidate_members():
    phon = {
        "foo": ["1"],
        "bar": ["2"],
        "baz": ["3"],
        "foo & bar": ["4"],          # candidate -> members foo, bar
        "foo feat unknown": ["5"],   # 'unknown' not known -> not a candidate
        "solo act": ["6"],           # single segment -> not a candidate
    }
    assert _collab_member_keys(phon) == {"foo", "bar"}


def test_member_cooccurrence_fraction():
    adj = {"a": {"b"}, "b": {"a"}}
    assert _member_cooccurrence(["a", "b"], adj) == 1.0
    assert _member_cooccurrence(["a", "b"], {}) == 0.0
    # 3 members, only the a-b pair co-occurs -> 1 of 3 pairs
    assert _member_cooccurrence(["a", "b", "c"], adj) == pytest.approx(1 / 3)


def test_collabs_member_gate_drops_central_cooccurring():
    # central node (survives centrality) whose members co-occur -> dropped
    phon = {"foo": ["id_a"], "bar": ["id_b"], "foo & bar": ["id_ab"]}
    in_deg = {"id_a": 100, "id_b": 80, "id_ab": 90}
    adj = {"foo": {"bar"}, "bar": {"foo"}}
    result = _identify_collabs(phon, in_deg, 0.2, adj=adj)
    assert result == {"id_ab"}


def test_collabs_member_gate_kept_when_no_cooccurrence():
    # central node whose members do NOT co-occur -> kept
    phon = {"foo": ["id_a"], "bar": ["id_b"], "foo & bar": ["id_ab"]}
    in_deg = {"id_a": 100, "id_b": 80, "id_ab": 90}
    result = _identify_collabs(phon, in_deg, 0.2, adj={})
    assert result == set()


def test_collabs_member_gate_spares_real_band_shape():
    # members co-occur but "the ..." shape is spared (X & The Y backing band)
    phon = {
        "bob marley": ["id_bm"],
        "the wailers": ["id_w"],
        "bob marley & the wailers": ["id_bw"],
    }
    in_deg = {"id_bm": 100, "id_w": 80, "id_bw": 200}
    adj = {"bob marley": {"the wailers"}, "the wailers": {"bob marley"}}
    result = _identify_collabs(phon, in_deg, 0.2, adj=adj)
    assert result == set()


def test_member_adjacency_from_stream(tmp_path):
    graph = tmp_path / "graph.ndjson"
    graph.write_bytes(
        b'{"id": "ida", "connections": [["idb", 0.9]]}\n'
        b'{"id": "idb", "connections": []}\n'
        b'{"id": "idc", "connections": []}\n'
    )
    phon = {"a": ["ida"], "b": ["idb"], "c": ["idc"]}
    adj = member_adjacency(graph, phon, {"a", "b", "c"})
    # a->b edge makes the pair adjacent in both directions; c is isolated
    assert adj["a"] == {"b"}
    assert adj["b"] == {"a"}
    assert adj.get("c", set()) == set()


def test_member_adjacency_skips_garbage_and_self_edges(tmp_path):
    graph = tmp_path / "graph.ndjson"
    graph.write_bytes(
        b"\n"                                                # blank line
        b"not json\n"                                        # malformed -> skipped
        b'{"connections": [["ida2", 0.5]]}\n'                # missing id -> skipped
        b'{"id": "ida1", "connections": [["ida2", 0.9]]}\n'  # both ids in group "a" -> self
        b'{"id": "ida1", "connections": [["idb", 0.9]]}\n'   # a -> b
    )
    phon = {"a": ["ida1", "ida2"], "b": ["idb"]}
    adj = member_adjacency(graph, phon, {"a", "b"})
    assert "a" not in adj.get("a", set())  # same-group edge is not a self-loop
    assert adj["a"] == {"b"}
    assert adj["b"] == {"a"}


def test_member_adjacency_empty_member_keys_short_circuits(tmp_path):
    graph = tmp_path / "graph.ndjson"
    graph.write_bytes(b'{"id": "ida", "connections": [["idb", 0.9]]}\n')
    assert member_adjacency(graph, {"a": ["ida"]}, set()) == {}


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
