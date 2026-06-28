"""Graph-aware cleaning: emit UUIDs to blocklist for two noise classes.

  1. Duplicates  — same artist written differently (punctuation/zero-width junk,
     accents, homoglyph spoofs, stylization). Nodes are grouped by a VISUAL key
     (homoglyph skeleton); within a group we keep the highest in-degree spelling
     and drop the differently-spelled variants. Byte-identical names are kept
     (genuine same-name different artists / MBID splits — homonym-safe), and
     distinct CJK/Cyrillic *letters* yield distinct skeletons so different
     non-Latin artists are not merged.
     NOTE: cross-script transliteration dedup (Cyrillic/CJK -> Latin via unidecode)
     was tried and DROPPED — a labeled check showed ~67% precision (many distinct
     artists romanize alike, e.g. Russian "Мот" vs Korean "MoT").

  2. Collabs/features — "A feat. B", "A & B", "A, B, C" credit nodes that are
     their own entity. A name is split on structural delimiters (, & / + * |)
     plus the standardized "feat"/"ft" marker; if it decomposes fully into >=2
     known artist nodes AND the credit node is far less central than its members
     (in-degree < CENTRALITY_FRAC x biggest member), it's dropped.

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


# --- collab delimiter segmentation -------------------------------------------

# Word split-markers: only the standardized feature word + abbreviations. The
# keep/drop decision is made by graph centrality, not by which word joined.
_STRONG_CONNECTORS: frozenset[str] = frozenset({"feat", "ft", "feats", "featuring", "feature"})
# Structural delimiter chars that split collaborators even when glued to a token
# ("поливокс," -> "поливокс"). unidecode maps "•" -> "*".
_SPLIT_CHARS = ",/&+*|"
_SPLIT_RE = re.compile(f"([{re.escape(_SPLIT_CHARS)}])")
_PUNCT = string.punctuation


def segment_name(norm: str) -> list[str]:
    """Split a normalized name into collaborator segments on connector tokens and
    delimiter chars. Other punctuation inside a name (the dot in "last past.") is
    preserved."""
    segs: list[str] = []
    cur: list[str] = []
    for tok in norm.split():
        for p in _SPLIT_RE.split(tok):
            if not p:
                continue
            if p in _SPLIT_CHARS:
                if cur:
                    segs.append(" ".join(cur))
                    cur = []
            elif p.strip(_PUNCT) in _STRONG_CONNECTORS:
                if cur:
                    segs.append(" ".join(cur))
                    cur = []
            else:
                cur.append(p)
    if cur:
        segs.append(" ".join(cur))
    return [s for s in segs if s]


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


def _identify_collabs(
    phon_groups: dict[str, list[str]],
    in_deg: dict[str, int],
    centrality_frac: float,
) -> set[str]:
    """Drop credit nodes that decompose into >=2 known artists and are far less
    central than their biggest member."""
    known = phon_groups.keys()
    rep_in: dict[str, int] = {}

    def max_in(nm: str) -> int:
        v = rep_in.get(nm)
        if v is None:
            v = max(in_deg.get(i, 0) for i in phon_groups[nm])
            rep_in[nm] = v
        return v

    collab: set[str] = set()
    for name, ids in phon_groups.items():
        if " " not in name:
            continue
        segs = segment_name(name)
        if len(segs) < 2:
            continue
        comps = [s for s in segs if s != name and s in known]
        if len(comps) < 2 or len(comps) != len(segs):
            continue  # require a full decomposition into known artists
        max_comp = max(max_in(s) for s in comps)
        if max_comp and max_in(name) < centrality_frac * max_comp:
            collab.update(ids)
    return collab


def identify_cleaning_uuids(
    graph_file: Path,
    metadata_file: Path,
    centrality_frac: float = CENTRALITY_FRAC,
    skip: set[str] = frozenset(),
) -> tuple[set[str], set[str]]:
    """Return (duplicate_uuids, collab_uuids) to blocklist. `skip` (e.g. the
    sentinel blocklist) is excluded from grouping. Reads NDJSON only; never writes."""
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
            phon_groups[clean_str(name)].append(aid)
            skel_groups[skeleton(name)].append(aid)
            progress.advance(task)

    dup = _identify_duplicates(skel_groups, name_of, in_deg)
    collab = _identify_collabs(phon_groups, in_deg, centrality_frac)
    return dup, collab


def main() -> None:
    """Dry run: report blocklist sizes without building anything."""
    from .blocklist import identify_blocklisted_uuids

    data_dir = Path("../data")
    metadata_file = data_dir / "metadata.ndjson"
    sentinels = identify_blocklisted_uuids(metadata_file)
    dup, collab = identify_cleaning_uuids(
        data_dir / "graph.ndjson", metadata_file, skip=sentinels
    )
    print(f"\nsentinels:        {len(sentinels):,}")
    print(f"duplicates:       {len(dup):,}")
    print(f"collabs/features: {len(collab):,}")
    print(f"overlap:          {len(dup & collab):,}")
    print(f"total to drop:    {len(sentinels | dup | collab):,}")


if __name__ == "__main__":
    main()
