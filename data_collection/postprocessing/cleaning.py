"""Graph-aware cleaning: emit UUIDs to blocklist for three noise classes.

  1. Duplicates  — same artist written differently (punctuation/zero-width junk,
     accents, homoglyph spoofs, stylization). Nodes are grouped by a VISUAL key
     (homoglyph skeleton); within a group we keep the highest in-degree spelling
     and drop the differently-spelled variants. Byte-identical names are kept
     (genuine same-name different artists / MBID splits — homonym-safe), and
     distinct CJK/Cyrillic *letters* yield distinct skeletons so different
     non-Latin artists are not merged.

  2. Transliteration variants — the same artist across scripts (a Cyrillic
     original and its Latin romanizations), which the visual skeleton misses
     because the spellings share no letters. Names are grouped by a loose
     transliteration key (translit_key — folds я=ia/ya/ja, х=kh/h, doubled
     letters, ...) and the highest in-degree spelling kept, but ONLY when a direct
     similarity edge links the spellings' representative nodes. A look-alike string
     alone is ~50% precise (distinct artists romanize alike, e.g. Russian "Мот" vs
     Korean "MoT"); the edge gate lifts that to ~100% in a labeled check, at the
     cost of reach — it only catches dups popular enough for their nodes to be
     linked (~13% of candidates, but the most user-visible ones). A looser overlap
     gate (shared neighbours, no edge) was tried and DROPPED — it readmits the
     false merges (~67% precision).

  3. Collabs/features — "A feat. B", "A & B", "A, B, C", "A x B" credit nodes
     that are their own entity. A name is split on structural delimiters
     (, & / + * |) plus the "feat"/"ft" and "x" pairing markers (a standalone
     Cyrillic/Greek "x" look-alike folds to "x" first, so Russian "A Х B" credits
     split too — see fold_x_connectors). It must decompose
     fully into >=2 known artist nodes; then a "feat"/"ft" marker drops it outright
     (no real artist name carries one). Otherwise it is dropped if the credit node
     is far less central than its members (in-degree < CENTRALITY_FRAC x biggest
     member) OR its named members actually co-occur in the graph (>= MM_FRAC of
     member pairs share an edge) — the latter catches central collabs that the
     centrality gate spares (e.g. "ЛСП & PHARAOH", more linked than either member),
     while skipping real-band shapes ("X & The Y" backing bands, <=2-char fragments
     like AC/DC -> ac+dc) that would otherwise be false positives.
     NOTE: a 2-hop variant (drop if members SHARE neighbours, not just link
     directly) was prototyped and DROPPED — it does not separate. Viral-collab
     members don't share top similar-artists (the collab pages were their only
     bridge: max Jaccard ~0), while real duos do (Jay-Z & Kanye ~0.14, Bob Marley
     & The Wailers ~0.61), so it would add false positives and catch none of the
     targets. Graph structure is exhausted for those residuals; only vocabulary
     (the connector + full decomposition) distinguishes them.

Nothing is merged and no edges are rewritten — only nodes are removed, and only
from the binary build. The source NDJSON is untouched (still used for growing).

Validated in graph_analysis/dataset_cleaning/ (collab threshold set from a
labeled precision sweep: r<0.2 ~= 99.4% precision).
"""

import re
import string
import unicodedata
from collections import defaultdict
from pathlib import Path

import orjson
from rich.progress import Progress

from normalization import clean_str

# Decision threshold for collab centrality (see module docstring / EDA sweep).
CENTRALITY_FRAC = 0.2
# Min fraction of member pairs that must co-occur in the graph for the
# member-adjacency gate to drop a centrality survivor (see EDA: ~99.3% precision).
MM_FRAC = 0.5
# Max spellings in a transliteration block. translit_key is intentionally lossy,
# so a bigger bucket is almost certainly a degenerate key conflating distinct
# short names; the edge gate was only validated on small blocks, so skip the rest.
MAX_TRANSLIT_BLOCK = 8

# --- visual key (homoglyph skeleton) -----------------------------------------

# Confusable characters that *look like* a Latin letter but live in another
# script, folded to that letter. Covers the dominant Cyrillic/Greek-in-Latin
# spoof case; not a full Unicode TR39 table.
_HOMOGLYPHS: dict[str, str] = {
    "а": "a", "в": "b", "е": "e", "ѕ": "s", "і": "i", "ј": "j", "к": "k",
    "м": "m", "н": "h", "о": "o", "р": "p", "с": "c", "т": "t", "у": "y",
    "х": "x", "ԁ": "d", "ԛ": "q", "ԝ": "w", "г": "r", "ӏ": "i", "ё": "e",
    "α": "a", "β": "b", "ε": "e", "η": "n", "ι": "i", "κ": "k", "μ": "u",
    "ν": "v", "ο": "o", "ρ": "p", "τ": "t", "υ": "u", "χ": "x", "ζ": "z",
    "γ": "y", "π": "n",
}


def skeleton(s: str) -> str:
    """Visual normal form: strip accents (NFKD), fold confusables to Latin,
    lowercase, drop punctuation, collapse whitespace."""
    if s.isascii():
        lo = s.lower()
        return " ".join(
            "".join(c if (c.isalnum() or c.isspace()) else " " for c in lo).split()
        )
    out: list[str] = []
    for ch in unicodedata.normalize("NFKD", s):
        if unicodedata.combining(ch):
            continue
        folded = _HOMOGLYPHS.get(ch.lower(), ch.lower())
        out.append(folded if (folded.isalnum() or folded.isspace()) else " ")
    return " ".join("".join(out).split())


# --- transliteration block key -----------------------------------------------

# Multi-letter romanizations of single Cyrillic letters that scribes spell
# inconsistently; folded so the variants land in one block (candidate only).
_TRANSLIT_DIGRAPHS: tuple[tuple[str, str], ...] = (
    ("shch", "sc"), ("sch", "sc"),           # щ
    ("kh", "h"),                             # х (unidecode -> kh; others h/x)
    ("zh", "z"),                             # ж
    ("tch", "c"), ("ts", "c"), ("ch", "c"),  # ч / ц
)


def translit_key(clean: str) -> str:
    """Loose transliteration block key over a clean_str result. Folds the common
    Slavic/Cyrillic romanization ambiguities (я=ia/ya/ja and й/ы via j,y->i,
    х=kh/h, doubled letters) so alternate spellings of one artist collide. Lossy
    and aggressive ON PURPOSE: it only proposes merge candidates — a direct graph
    edge gates the real merge (_identify_translit_dups). Not shared with Rust and
    never used for search; clean_str stays the serving key."""
    s = clean
    for a, b in _TRANSLIT_DIGRAPHS:
        s = s.replace(a, b)
    s = s.replace("j", "i").replace("y", "i")
    out: list[str] = []
    for ch in s:
        if not out or out[-1] != ch:
            out.append(ch)
    return "".join(out)


# --- collab delimiter segmentation -------------------------------------------

# Feature/credit markers: a real standalone artist essentially never carries one
# of these in its name, so a full decomposition split on them is dropped
# REGARDLESS of centrality. Without this, the graph-aware gate spares dense-scene
# collabs that are themselves hubs (e.g. "JEEMBO ft. PHARAOH", in-degree > both).
_FEATURE_MARKERS: frozenset[str] = frozenset({"feat", "ft", "feats", "featuring", "feature"})
# Pairing token: splits "A x B" (the "×" sign folds to "x" via clean_str), but
# stays centrality-gated — "x" is a weaker credit signal. Validated at 97.5%.
_PAIR_MARKERS: frozenset[str] = frozenset({"x"})
# Both kinds mark WHERE to split; whether a feature marker was used decides if
# the centrality gate applies (see _identify_collabs).
_STRONG_CONNECTORS: frozenset[str] = _FEATURE_MARKERS | _PAIR_MARKERS
# Structural delimiter chars that split collaborators even when glued to a token
# ("поливокс," -> "поливокс"). unidecode maps "•" -> "*".
_SPLIT_CHARS = ",/&+*|"
_SPLIT_RE = re.compile(f"([{re.escape(_SPLIT_CHARS)}])")
_PUNCT = string.punctuation

# Standalone tokens that LOOK like the Latin "x" pairing marker but live in
# another script (Cyrillic Х/х, Greek Χ/χ). Russian credits write "A Х B", but
# clean_str runs the letter through unidecode -> "kh", hiding the split. We fold
# a whole-token look-alike to "x" BEFORE clean_str (a word-internal "х" is never
# a join, so it's left alone). Collab path only: clean_str is shared byte-for-byte
# with the Rust serving code (string_normalization.rs) and must stay unchanged.
_X_LOOKALIKES: frozenset[str] = frozenset("хХχΧ")


def fold_x_connectors(name: str) -> str:
    """Fold a standalone Cyrillic/Greek "x" look-alike token to Latin "x" so the
    collab segmenter can split "A Х B" credits (see _X_LOOKALIKES)."""
    if name.isascii():
        return name
    return " ".join(
        "x" if tok.strip(_PUNCT) in _X_LOOKALIKES else tok for tok in name.split()
    )


def _segment(norm: str) -> tuple[list[str], bool]:
    """Split a normalized name into collaborator segments on connector tokens and
    delimiter chars, and report whether a feature marker (feat/ft) drove a split.
    Both come from the same tokenization so they can't disagree. Other punctuation
    inside a name (the dot in "last past.") is preserved."""
    segs: list[str] = []
    cur: list[str] = []
    has_feat = False
    for tok in norm.split():
        for p in _SPLIT_RE.split(tok):
            if not p:
                continue
            if p in _SPLIT_CHARS:
                if cur:
                    segs.append(" ".join(cur))
                    cur = []
            elif (core := p.strip(_PUNCT)) in _STRONG_CONNECTORS:
                if cur:
                    segs.append(" ".join(cur))
                    cur = []
                has_feat = has_feat or core in _FEATURE_MARKERS
            else:
                cur.append(p)
    if cur:
        segs.append(" ".join(cur))
    return [s for s in segs if s], has_feat


def segment_name(norm: str) -> list[str]:
    """Collaborator segments of a normalized name (see _segment)."""
    return _segment(norm)[0]


# --- in-degree ---------------------------------------------------------------


def compute_in_degrees(graph_file: Path) -> dict[str, int]:
    """Count incoming edges per node by streaming graph.ndjson once."""
    indeg: dict[str, int] = defaultdict(int)
    with graph_file.open("rb") as f, Progress() as progress:
        task = progress.add_task("[cyan]Counting in-degrees...", total=None)
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                data = orjson.loads(line)
            except orjson.JSONDecodeError:
                continue
            for conn_id, _weight in data.get("connections", []):
                indeg[conn_id] += 1
            progress.advance(task)
    return indeg


# --- the two rules -----------------------------------------------------------


def _identify_duplicates(
    skel_groups: dict[str, list[str]],
    name_of: dict[str, str],
    in_deg: dict[str, int],
) -> set[str]:
    """Drop same-script decoration variants (junk/punctuation/accents/homoglyphs),
    keeping the highest in-degree spelling. Byte-identical names are kept (homonym
    safety). Distinct CJK/Cyrillic letters produce distinct skeletons, so different
    non-Latin artists are not merged."""
    dup: set[str] = set()
    for key, ids in skel_groups.items():
        if not key or len(ids) < 2:
            continue
        canonical = max(ids, key=lambda i: in_deg.get(i, 0))
        cname = name_of[canonical]
        for i in ids:
            if name_of[i] != cname:
                dup.add(i)
    return dup


def _edge_components(nodes: list[str], adj: dict[str, set[str]]) -> list[list[str]]:
    """Connected components of `nodes` under adjacency `adj` (union-find); edges to
    anything outside `nodes` are ignored."""
    nodeset = set(nodes)
    parent = {n: n for n in nodes}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a in nodes:
        for b in adj.get(a, ()):
            if b in nodeset:
                parent[find(a)] = find(b)
    comp: dict[str, list[str]] = defaultdict(list)
    for n in nodes:
        comp[find(n)].append(n)
    return list(comp.values())


def _stream_adjacency(
    graph_file: Path, node_key: dict[str, str], label: str
) -> dict[str, set[str]]:
    """One streaming pass over graph.ndjson: symmetric adjacency between the keyed
    nodes (uuid -> group key), an edge recorded between two keys whenever a node of
    one links a node of the other. Restricted to the keyed universe, so memory
    stays bounded by that subgraph rather than the whole graph."""
    adj: dict[str, set[str]] = defaultdict(set)
    with graph_file.open("rb") as f, Progress() as progress:
        task = progress.add_task(label, total=None)
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                data = orjson.loads(line)
            except orjson.JSONDecodeError:
                continue
            ku = node_key.get(data.get("id"))
            if ku is None:
                continue
            for conn_id, _weight in data.get("connections", []):
                kv = node_key.get(conn_id)
                if kv is not None and kv != ku:
                    adj[ku].add(kv)
                    adj[kv].add(ku)
            progress.advance(task)
    return adj


def _identify_translit_dups(
    graph_file: Path,
    phon_groups: dict[str, list[str]],
    in_deg: dict[str, int],
) -> set[str]:
    """Drop cross-script transliteration variants the visual skeleton can't reach.
    Spellings of one artist (Cyrillic original + romanizations) share a loose
    translit_key but different skeletons; within a block keep the highest in-degree
    spelling and drop the others' representative nodes — but ONLY when a direct
    graph edge links those reps (string look-alike alone is ~50% precise; the edge
    gate lifts it to ~100%). Validated in graph_analysis/dataset_cleaning."""
    rep_id: dict[str, str] = {}
    rep_in: dict[str, int] = {}
    for clean, ids in phon_groups.items():
        best = max(ids, key=lambda i: in_deg.get(i, 0))
        d = in_deg.get(best, 0)
        if d > 0:  # a dead (in=0) spelling is never the survivor; merging it is pointless
            rep_id[clean] = best
            rep_in[clean] = d

    blocks: dict[str, list[str]] = defaultdict(list)
    for clean in rep_id:
        blocks[translit_key(clean)].append(clean)
    # >=2 spellings to be a duplicate set; cap the size (see MAX_TRANSLIT_BLOCK).
    blocks = {
        tk: cleans
        for tk, cleans in blocks.items()
        if 2 <= len(cleans) <= MAX_TRANSLIT_BLOCK
    }
    if not blocks:
        return set()

    rep_key = {rep_id[c]: c for cleans in blocks.values() for c in cleans}
    adj = _stream_adjacency(graph_file, rep_key, "[cyan]Transliteration edges...")

    drop: set[str] = set()
    for cleans in blocks.values():
        for group in _edge_components(cleans, adj):
            if len(group) < 2:
                continue
            survivor = max(group, key=lambda c: rep_in[c])
            # Drop only each losing spelling's representative (its highest in-degree
            # node) — the validated unit. Weaker nodes / byte-identical homonyms
            # under the same clean_str are left alone (homonym-safe; under-cleans).
            for c in group:
                if c != survivor:
                    drop.add(rep_id[c])
    return drop


def _real_band_shape(comps: list[str]) -> bool:
    """A decomposition that more likely names a real band than a collaboration: a
    "the ..." backing band (X & The Y) or a <=2-char fragment (AC/DC -> ac+dc).
    These shapes carried nearly all the member-gate false positives in EDA."""
    return any(len(s) <= 2 or s.startswith("the ") for s in comps)


def _member_cooccurrence(comps: list[str], adj: dict[str, set[str]]) -> float:
    """Fraction of member pairs that share a graph edge. Checks one direction
    only, relying on `adj` being symmetric (member_adjacency guarantees it)."""
    pairs = total = 0
    for a in range(len(comps)):
        for b in range(a + 1, len(comps)):
            total += 1
            if comps[b] in adj.get(comps[a], ()):
                pairs += 1
    return pairs / total if total else 0.0


def _decompose(name: str, known) -> tuple[list[str], bool] | None:
    """If `name` fully decomposes into >=2 known artist members, return
    (members, has_feature_marker); else None. Single source of truth for what
    counts as a collab candidate — both the member-universe scan and the collab
    decision use it, so their candidate sets cannot desync."""
    if " " not in name:
        return None
    segs, has_feat = _segment(name)
    if len(segs) < 2:
        return None
    comps = [s for s in segs if s != name and s in known]
    if len(comps) < 2 or len(comps) != len(segs):
        return None
    return comps, has_feat


def _collab_member_keys(phon_groups: dict[str, list[str]]) -> set[str]:
    """Artist keys that appear as members of some decomposable name — the only
    nodes whose adjacency the member co-occurrence gate needs."""
    known = phon_groups.keys()
    members: set[str] = set()
    for name in phon_groups:
        d = _decompose(name, known)
        if d is not None:
            members.update(d[0])
    return members


def member_adjacency(
    graph_file: Path,
    phon_groups: dict[str, list[str]],
    member_keys: set[str],
) -> dict[str, set[str]]:
    """For each member key, the set of other member keys it shares an edge with
    (either direction). Maps every node of each member group to its key, then
    streams once — restricted to the member universe (see _stream_adjacency)."""
    if not member_keys:
        return {}
    node_key = {i: k for k in member_keys for i in phon_groups[k]}
    return _stream_adjacency(graph_file, node_key, "[cyan]Member adjacency...")


def _identify_collabs(
    phon_groups: dict[str, list[str]],
    in_deg: dict[str, int],
    centrality_frac: float,
    adj: dict[str, set[str]] | None = None,
    mm_frac: float = MM_FRAC,
) -> set[str]:
    """Drop credit nodes that decompose into >=2 known artists. A feature marker
    (feat/ft) drops the node outright; otherwise it is dropped if it is far less
    central than its biggest member (centrality gate) OR its members co-occur in
    the graph (member-adjacency gate) — the latter skipped for real-band shapes."""
    known = phon_groups.keys()
    adj = adj or {}
    rep_in: dict[str, int] = {}

    def max_in(nm: str) -> int:
        v = rep_in.get(nm)
        if v is None:
            v = max(in_deg.get(i, 0) for i in phon_groups[nm])
            rep_in[nm] = v
        return v

    collab: set[str] = set()
    for name, ids in phon_groups.items():
        decomp = _decompose(name, known)
        if decomp is None:
            continue
        comps, has_feat = decomp
        if has_feat:
            collab.update(ids)
            continue
        max_comp = max(max_in(s) for s in comps)
        if max_comp and max_in(name) < centrality_frac * max_comp:
            collab.update(ids)
            continue
        # Central survivor: drop only if the named members really co-occur and the
        # name is not a real-band shape (X & The Y, or a <=2-char fragment).
        if not _real_band_shape(comps) and _member_cooccurrence(comps, adj) >= mm_frac:
            collab.update(ids)
    return collab


def identify_cleaning_uuids(
    graph_file: Path,
    metadata_file: Path,
    centrality_frac: float = CENTRALITY_FRAC,
    skip: set[str] = frozenset(),
) -> tuple[set[str], set[str], set[str]]:
    """Return (duplicate_uuids, translit_uuids, collab_uuids) to blocklist. `skip`
    (e.g. the sentinel blocklist) is excluded from grouping. Reads NDJSON only;
    never writes."""
    in_deg = compute_in_degrees(graph_file)

    name_of: dict[str, str] = {}
    phon_groups: dict[str, list[str]] = defaultdict(list)
    skel_groups: dict[str, list[str]] = defaultdict(list)
    with metadata_file.open("rb") as f, Progress() as progress:
        task = progress.add_task("[cyan]Grouping names...", total=None)
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                e = orjson.loads(line)
                aid, name = e["id"], e["name"]
            except (orjson.JSONDecodeError, KeyError):
                continue
            if aid in skip or not isinstance(name, str):
                continue
            name_of[aid] = name
            phon_groups[clean_str(fold_x_connectors(name))].append(aid)
            skel_groups[skeleton(name)].append(aid)
            progress.advance(task)

    dup = _identify_duplicates(skel_groups, name_of, in_deg)
    translit = _identify_translit_dups(graph_file, phon_groups, in_deg)
    member_keys = _collab_member_keys(phon_groups)
    adj = member_adjacency(graph_file, phon_groups, member_keys)
    collab = _identify_collabs(phon_groups, in_deg, centrality_frac, adj)
    return dup, translit, collab


def main() -> None:
    """Dry run: report blocklist sizes without building anything."""
    from .blocklist import identify_blocklisted_uuids

    data_dir = Path("../data")
    metadata_file = data_dir / "metadata.ndjson"
    sentinels = identify_blocklisted_uuids(metadata_file)
    dup, translit, collab = identify_cleaning_uuids(
        data_dir / "graph.ndjson", metadata_file, skip=sentinels
    )
    print(f"\nsentinels:        {len(sentinels):,}")
    print(f"duplicates:       {len(dup):,}")
    print(f"translit dups:    {len(translit):,}")
    print(f"collabs/features: {len(collab):,}")
    print(f"total to drop:    {len(sentinels | dup | translit | collab):,}")


if __name__ == "__main__":
    main()
