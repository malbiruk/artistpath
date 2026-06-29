"""Prototype: does neighbor-coverage separate redundant collabs from real bands?

For a node C that decomposes into known members M1..Mk, coverage =
|out(C) ∩ (members ∪ ⋃ out(Mi))| / |out(C)|  — the fraction of C's similar-artists
that are already 'explained' by its members. A redundant collab should be ~1.0;
a real band (its own distinct audience) should be lower. Uses the old (full)
forward graph for out-neighbours."""
import json
import re
import string
from pathlib import Path

from analyze import load_names
from binio import GraphStore, uuid_to_bytes
from keys import clean_str

_FEATURE_MARKERS = frozenset({"feat", "ft", "feats", "featuring", "feature"})
_PAIR_MARKERS = frozenset({"x"})
_CONN = _FEATURE_MARKERS | _PAIR_MARKERS
_SPLIT_CHARS = ",/&+*|"
_SPLIT_RE = re.compile(f"([{re.escape(_SPLIT_CHARS)}])")
_PUNCT = string.punctuation

REAL_BANDS = [
    "AC/DC", "Simon & Garfunkel", "Hall & Oates", "Brooks & Dunn",
    "Florence + the Machine", "Earth, Wind & Fire", "Belle & Sebastian",
    "Mumford & Sons", "Crosby, Stills & Nash", "Iron & Wine", "Above & Beyond",
    "Sly & The Family Stone", "Bob Marley & The Wailers", "Nick Cave & The Bad Seeds",
]


def segment_name(norm):
    segs, cur = [], []
    for tok in norm.split():
        for p in _SPLIT_RE.split(tok):
            if not p:
                continue
            if p in _SPLIT_CHARS:
                if cur:
                    segs.append(" ".join(cur)); cur = []
            elif p.strip(_PUNCT) in _CONN:
                if cur:
                    segs.append(" ".join(cur)); cur = []
            else:
                cur.append(p)
    if cur:
        segs.append(" ".join(cur))
    return [s for s in segs if s]


def main():
    sp = "/tmp/claude-1000/-var-home-klimasos-Services-artistpath/8fb0b623-4dfd-4e80-b625-9b3ecd90dfe3/scratchpad/explore.json"
    cluster = [n["name"] for n in json.load(open(sp))["nodes"]]

    store = GraphStore(Path("oldbins").resolve())
    data = load_names(Path("../../data/metadata.ndjson"))
    phon, known = data["phon_groups"], set(data["phon_groups"])
    ncache, dcache = {}, {}

    def out_union(nn):  # union out-neighbours over a phon group
        v = ncache.get(nn)
        if v is None:
            v = set()
            for i in phon.get(nn, []):
                v |= store.out_neighbors(uuid_to_bytes(i))
            ncache[nn] = v
        return v

    def indeg(nn):
        v = dcache.get(nn)
        if v is None:
            v = max((store.in_degree(uuid_to_bytes(i)) for i in phon.get(nn, [])), default=0)
            dcache[nn] = v
        return v

    def ids_of(nn):
        return {uuid_to_bytes(i) for i in phon.get(nn, [])}

    def analyze(name):
        norm = clean_str(name)
        segs = segment_name(norm)
        comps = [s for s in segs if s != norm and s in known]
        if len(segs) < 2 or len(comps) < 2 or len(comps) != len(segs):
            return None
        c_ids, c_out = ids_of(norm), out_union(norm)
        # member <-> collab adjacency (either direction)
        adj = 0
        for s in comps:
            m_ids, m_out = ids_of(s), out_union(s)
            if (m_ids & c_out) or (c_ids & m_out):
                adj += 1
        frac_adj = adj / len(comps)
        # member <-> member adjacency: fraction of member pairs that co-occur
        pairs = tot = 0
        for i in range(len(comps)):
            for j in range(i + 1, len(comps)):
                tot += 1
                ai, aj = ids_of(comps[i]), ids_of(comps[j])
                if (ai & out_union(comps[j])) or (aj & out_union(comps[i])):
                    pairs += 1
        mm = pairs / tot if tot else 0
        return (name, comps, frac_adj, mm, indeg(norm), max(indeg(s) for s in comps))

    def show(title, names):
        print(f"\n=== {title} ===")
        print(f"{'name':40} {'m<->C':>6} {'m<->m':>6} {'ratio':>6}  members")
        rows = [r for r in (analyze(n) for n in names) if r]
        for name, comps, fa, mm, ci, mc in sorted(rows, key=lambda r: -r[3]):
            ratio = ci / mc if mc else 0
            print(f"{name[:40]:40} {fa:>6.0%} {mm:>6.0%} {ratio:>6.2f}  {comps}")
        print(f"  ({len(rows)} of {len(names)} decompose into >=2 known)")

    show("CLUSTER collabs (expect HIGH coverage)", cluster)
    show("REAL BANDS (expect LOW coverage)", REAL_BANDS)


if __name__ == "__main__":
    main()
