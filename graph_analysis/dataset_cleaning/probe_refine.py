"""Cheap separation probe for two proposed refinements, run BEFORE any label cycle.

A. Cyrillic-X fold: Last.fm Russian collabs use the Cyrillic letter "Х/х" (U+0425/
   U+0445) as the "x" pairing token ("PHARAOH Х BOULEVARD DEPO"). clean_str runs it
   through unidecode -> "kh", so it never splits. We fold a STANDALONE Cyrillic/Greek
   x-look-alike token to Latin "x" *before* clean_str (collab path only; clean_str
   itself is shared byte-for-byte with Rust and must not change). Report how many
   names become NEW collab candidates and how the existing gates would classify them.

B. 2-hop shared-neighbour co-occurrence: the live 1-hop gate drops a central
   survivor only if members point AT EACH OTHER. Members of a viral collab usually
   don't, but they sit in the same neighbourhood. 2-hop asks: do the members' top-K
   similar-artist sets OVERLAP? Risk: real bands' members share genre neighbours too.
   So we DON'T validate precision yet -- we first check whether 2-hop even SEPARATES
   known cluster collabs from real own-entity acts. If it doesn't, the idea is dead.
"""
import json
import re
import string
from itertools import combinations
from pathlib import Path

from analyze import load_names
from binio import GraphStore, uuid_to_bytes
from keys import clean_str

# --- shared collab segmentation (mirror of postprocessing) -------------------
_FEATURE_MARKERS = frozenset({"feat", "ft", "feats", "featuring", "feature"})
_PAIR_MARKERS = frozenset({"x"})
_CONN = _FEATURE_MARKERS | _PAIR_MARKERS
_SPLIT_CHARS = ",/&+*|"
_SPLIT_RE = re.compile(f"([{re.escape(_SPLIT_CHARS)}])")
_PUNCT = string.punctuation

# Standalone tokens that LOOK like the Latin "x" pairing marker but live in another
# script. Folded to "x" only as a whole token (a word-internal "х" is never a join).
_X_LOOKALIKES = {"х", "Х", "χ", "Χ"}


def fold_connectors(name: str) -> str:
    return " ".join("x" if t.strip(_PUNCT) in _X_LOOKALIKES else t for t in name.split())


def segment(norm):
    segs, cur, has_feat = [], [], False
    for tok in norm.split():
        for p in _SPLIT_RE.split(tok):
            if not p:
                continue
            if p in _SPLIT_CHARS:
                if cur:
                    segs.append(" ".join(cur)); cur = []
            elif (core := p.strip(_PUNCT)) in _CONN:
                if cur:
                    segs.append(" ".join(cur)); cur = []
                has_feat = has_feat or core in _FEATURE_MARKERS
            else:
                cur.append(p)
    if cur:
        segs.append(" ".join(cur))
    return [s for s in segs if s], has_feat


def decompose(norm, known):
    if " " not in norm:
        return None
    segs, has_feat = segment(norm)
    if len(segs) < 2:
        return None
    comps = [s for s in segs if s != norm and s in known]
    if len(comps) < 2 or len(comps) != len(segs):
        return None
    return comps, has_feat


REAL_ACTS = [  # real own-entity acts that MIGHT decompose into known members
    "AC/DC", "Simon & Garfunkel", "Hall & Oates", "Brooks & Dunn",
    "Florence + the Machine", "Earth, Wind & Fire", "Belle & Sebastian",
    "Mumford & Sons", "Crosby, Stills & Nash", "Iron & Wine", "Above & Beyond",
    "Sly & The Family Stone", "Bob Marley & The Wailers", "Nick Cave & The Bad Seeds",
    "Chase & Status", "Sonny & Cher", "Robert Plant & Alison Krauss",
    "Brian Eno & David Byrne", "Young P&H", "Modeselektor", "Daryl Hall & John Oates",
    "Angus & Julia Stone", "Brian Eno & Harold Budd", "Tomato & Tabasco",
    "She & Him", "Jay-Z & Kanye West", "Macklemore & Ryan Lewis",
]


def main():
    data_dir = Path("../../data")  # LIVE cleaned binaries (members are present)
    store = GraphStore(data_dir.resolve())
    data = load_names(data_dir / "metadata.ndjson")
    names, phon = data["names"], data["phon_groups"]
    known_plain = set(phon)

    icache, tcache = {}, {}

    def max_in(nn):
        v = icache.get(nn)
        if v is None:
            v = max((store.in_degree(uuid_to_bytes(i)) for i in phon.get(nn, [])), default=0)
            icache[nn] = v
        return v

    def topk(nn, k, s):  # union top-k neighbours over the phon group's ids
        key = (nn, k, s)
        v = tcache.get(key)
        if v is None:
            v = set()
            for i in phon.get(nn, []):
                v |= store.top_neighbors(uuid_to_bytes(i), k, s)
            tcache[key] = v
        return v

    # =========================================================================
    # A. Cyrillic-X fold: NEW collab candidates unlocked by folding
    # =========================================================================
    print("=== A. Cyrillic/Greek-x fold ===")
    folded_phon = {}
    for aid, nm in names.items():
        folded_phon.setdefault(clean_str(fold_connectors(nm)), []).append(aid)
    known_folded = set(folded_phon)

    n_changed = n_new = 0
    by_gate = {"feat": 0, "centrality": 0, "needs_mm": 0}
    examples = []
    for nm in names.values():
        plain = clean_str(nm)
        folded = clean_str(fold_connectors(nm))
        if folded == plain:
            continue
        n_changed += 1
        if decompose(plain, known_plain) is not None:
            continue  # already caught without the fold
        d = decompose(folded, known_folded)
        if d is None:
            continue
        n_new += 1
        comps, has_feat = d
        mc = max(max_in(s) for s in comps)
        ci = max_in(folded)
        if has_feat:
            gate = "feat"
        elif mc and ci < 0.2 * mc:
            gate = "centrality"
        else:
            gate = "needs_mm"
        by_gate[gate] += 1
        if len(examples) < 40:
            examples.append((nm, comps, gate, round(ci / mc, 2) if mc else None))

    print(f"  names whose key changed under fold: {n_changed:,}")
    print(f"  NEW decomposable collab candidates: {n_new:,}")
    print(f"    by existing gate -> feat-drop={by_gate['feat']}  "
          f"centrality-drop={by_gate['centrality']}  survive-to-mm={by_gate['needs_mm']}")
    print("  examples (name | members | gate | indeg-ratio):")
    for nm, comps, gate, ratio in examples:
        print(f"    {nm[:42]:44} {str(comps)[:46]:48} {gate:11} r={ratio}")

    # =========================================================================
    # B. 2-hop separation: cluster collabs (positive) vs real acts (negative)
    # =========================================================================
    print("\n=== B. 2-hop shared-neighbour separation ===")
    cluster = [n["name"] for n in json.load(
        open("/tmp/claude-1000/-var-home-klimasos-Services-artistpath/"
             "8fb0b623-4dfd-4e80-b625-9b3ecd90dfe3/scratchpad/cluster_live.json"))["nodes"]]

    CONFIGS = [(25, 0.0), (50, 0.0), (50, 0.2)]
    JTHRS = [0.05, 0.10, 0.20]

    def jaccard(a, b):
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    def one_hop_frac(comps):  # current live signal, for comparison
        tot = hit = 0
        for x, y in combinations(comps, 2):
            tot += 1
            ix = {uuid_to_bytes(i) for i in phon.get(x, [])}
            iy = {uuid_to_bytes(i) for i in phon.get(y, [])}
            if (ix & topk(y, 250, 0.0)) or (iy & topk(x, 250, 0.0)):
                hit += 1
        return hit / tot if tot else 0.0

    def row(name, known):
        norm = fold_connectors(name)
        norm = clean_str(norm)
        d = decompose(norm, known)
        if d is None:
            return None
        comps, _ = d
        oh = one_hop_frac(comps)
        cells = {}
        for k, s in CONFIGS:
            js = [jaccard(topk(comps[a], k, s), topk(comps[b], k, s))
                  for a, b in combinations(range(len(comps)), 2)]
            cells[(k, s)] = js
        return name, comps, oh, cells

    def show(title, items, known):
        print(f"\n  --- {title} ---")
        hdr = f"  {'name':40} {'1hop':>5} " + " ".join(
            f"K{k}s{s}/maxJ" for k, s in CONFIGS)
        print(hdr)
        rows = [r for r in (row(n, known) for n in items) if r]
        for name, comps, oh, cells in sorted(rows, key=lambda r: -r[2]):
            maxjs = " ".join(f"{max(cells[(k, s)]):>9.2f}" for k, s in CONFIGS)
            print(f"  {name[:40]:40} {oh:>5.0%} {maxjs}   {comps}")
        print(f"  ({len(rows)} of {len(items)} decompose)")
        # threshold sweep on mm2 (fraction of pairs over Jaccard threshold), config K50 s0
        cfg = (50, 0.0)
        print(f"  mm2 sweep @ {cfg} (fraction of member pairs with Jaccard>=thr):")
        for j in JTHRS:
            ge = sum(1 for _, _, _, c in rows
                     if (lambda js: sum(x >= j for x in js) / len(js) if js else 0)(c[cfg]) >= 0.5)
            print(f"    Jthr={j}: {ge}/{len(rows)} acts have mm2>=0.5")

    # cluster: keep only decomposable nodes that aren't obviously the hub artist
    show("CLUSTER (collabs, expect HIGH overlap)", cluster, known_plain)
    show("REAL ACTS (own entities, expect LOW overlap)", REAL_ACTS, known_plain)


if __name__ == "__main__":
    main()
