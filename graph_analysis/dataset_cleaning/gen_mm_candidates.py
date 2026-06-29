"""Generate collab candidates and compute member<->member co-occurrence for the
SURVIVORS of the current rule (no feat marker, centrality ratio >= 0.2) — the
nodes the m<->m gate would newly delete. Saves them with fields for FP analysis."""
import json
import re
import string
from pathlib import Path

from rich.progress import Progress

from analyze import load_names
from binio import GraphStore, uuid_to_bytes
from keys import clean_str

_FEATURE_MARKERS = frozenset({"feat", "ft", "feats", "featuring", "feature"})
_PAIR_MARKERS = frozenset({"x"})
_CONN = _FEATURE_MARKERS | _PAIR_MARKERS
_SPLIT_CHARS = ",/&+*|"
_SPLIT_RE = re.compile(f"([{re.escape(_SPLIT_CHARS)}])")
_PUNCT = string.punctuation
FRAC = 0.2


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


def has_feat(norm):
    return any(p.strip(_PUNCT) in _FEATURE_MARKERS for p in norm.split())


def main():
    store = GraphStore(Path("oldbins").resolve())
    data = load_names(Path("../../data/metadata.ndjson"))
    phon, names, known = data["phon_groups"], data["names"], set(data["phon_groups"])

    icache, ocache = {}, {}

    def max_in(nn):
        v = icache.get(nn)
        if v is None:
            v = max((store.in_degree(uuid_to_bytes(i)) for i in phon[nn]), default=0)
            icache[nn] = v
        return v

    def out_union(nn):
        v = ocache.get(nn)
        if v is None:
            v = set()
            for i in phon[nn]:
                v |= store.out_neighbors(uuid_to_bytes(i))
            ocache[nn] = v
        return v

    def ids_of(nn):
        return {uuid_to_bytes(i) for i in phon[nn]}

    n_cand = n_feat = n_secondary = 0
    survivors = []
    with Progress() as pr:
        t = pr.add_task("scanning candidates...", total=len(phon))
        for name in phon:
            pr.advance(t)
            if " " not in name:
                continue
            segs = segment_name(name)
            if len(segs) < 2:
                continue
            comps = [s for s in segs if s != name and s in known]
            if len(comps) < 2 or len(comps) != len(segs):
                continue
            n_cand += 1
            if has_feat(name):
                n_feat += 1
                continue
            mc = max(max_in(s) for s in comps)
            ci = max_in(name)
            if mc and ci < FRAC * mc:
                n_secondary += 1
                continue
            # survivor of the current rule: compute member<->member co-occurrence
            pairs = tot = 0
            for a in range(len(comps)):
                for b in range(a + 1, len(comps)):
                    tot += 1
                    if (ids_of(comps[a]) & out_union(comps[b])) or (ids_of(comps[b]) & out_union(comps[a])):
                        pairs += 1
            mm = pairs / tot if tot else 0.0
            survivors.append({
                "name": names[phon[name][0]],
                "norm": name,
                "comps": comps,
                "ratio": round(ci / mc, 3) if mc else None,
                "mm": round(mm, 3),
                "n_seg": len(comps),
                "has_the": any(s.startswith("the ") for s in comps),
                "min_seg_len": min(len(s) for s in comps),
            })

    Path("results/mm_survivors.json").write_bytes(
        json.dumps(survivors, ensure_ascii=False).encode()
    )
    new_del = [s for s in survivors if s["mm"] >= 0.5]
    print(f"\ntotal decomposable candidates: {n_cand:,}")
    print(f"  deleted now by feat marker:  {n_feat:,}")
    print(f"  deleted now by centrality<0.2: {n_secondary:,}")
    print(f"  survivors (kept now):        {len(survivors):,}")
    print(f"    of which m<->m >= 0.5 (NEW deletions): {len(new_del):,}")
    for thr in (1.0, 0.5):
        nd = [s for s in survivors if s["mm"] >= thr]
        the = sum(1 for s in nd if s["has_the"])
        print(f"    mm>={thr}: {len(nd):,} new deletions  ({the:,} have a 'the ...' segment)")


if __name__ == "__main__":
    main()
