"""Step A of the translit-dup validation: build cross-spelling candidate groups
and measure how often the GRAPH connects them. No API calls.

A candidate group = a loose translit_key shared by >=2 distinct clean_str
representatives (each representative = the highest-inbound node for its clean_str,
i.e. the node that would survive dedup). For every group we record pairwise
direct edges, out-neighbour overlap, and whether the reps form one connected
component via direct edges. Dumps results/translit_candidates.json + prints stats."""
import json
from itertools import combinations
from pathlib import Path

from analyze import load_names
from binio import GraphStore, uuid_to_bytes
from translit_key import translit_key

DATA = Path("../../data")
MAX_REPS = 8  # groups bigger than this are almost certainly a degenerate key


def components(rep_ids, edges):
    """Connected components of rep_ids under undirected `edges` (set of frozenset pairs)."""
    parent = {r: r for r in rep_ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        parent[find(a)] = find(b)
    comp: dict = {}
    for r in rep_ids:
        comp.setdefault(find(r), []).append(r)
    return list(comp.values())


def main():
    store = GraphStore(DATA.resolve())
    data = load_names(DATA / "metadata.ndjson")
    names, phon = data["names"], data["phon_groups"]

    tgroups: dict[str, set[str]] = {}
    for clean in phon:
        tgroups.setdefault(translit_key(clean), set()).add(clean)
    multi = {tk: cs for tk, cs in tgroups.items() if len(cs) >= 2}
    interesting_cleans = {c for cs in multi.values() for c in cs}
    print(f"translit buckets: {len(tgroups)} | multi-spelling (>=2 clean_str): {len(multi)}")

    rep: dict[str, dict] = {}
    for clean in interesting_cleans:
        best_id, best_in = None, -1
        for aid in phon[clean]:
            d = store.in_degree(uuid_to_bytes(aid))
            if d > best_in:
                best_id, best_in = aid, d
        rep[clean] = {"id": best_id, "name": names[best_id], "in": best_in, "clean": clean}

    groups = []
    degenerate = 0
    for tk, cleans in multi.items():
        reps = [rep[c] for c in cleans if rep[c]["in"] > 0]
        if len(reps) < 2:
            continue
        if len(reps) > MAX_REPS:
            degenerate += 1
            continue
        ids = [r["id"] for r in reps]
        nbrs = {i: store.out_neighbors(uuid_to_bytes(i)) for i in ids}
        edges = set()
        pair_feats = []
        for a, b in combinations(reps, 2):
            ia, ib = a["id"], b["id"]
            ba, bb = uuid_to_bytes(ia), uuid_to_bytes(ib)
            e_ab = bb in nbrs[ia]
            e_ba = ba in nbrs[ib]
            inter = len(nbrs[ia] & nbrs[ib])
            union = len(nbrs[ia] | nbrs[ib]) or 1
            if e_ab or e_ba:
                edges.add(frozenset((ia, ib)))
            pair_feats.append({
                "a": a["name"], "b": b["name"], "a_clean": a["clean"], "b_clean": b["clean"],
                "edge": e_ab or e_ba, "shared": inter, "jaccard": round(inter / union, 3),
                "in_a": a["in"], "in_b": b["in"],
            })
        comps = components(ids, edges)
        groups.append({
            "tkey": tk, "n_reps": len(reps),
            "reps": [{"name": r["name"], "clean": r["clean"], "in": r["in"]} for r in reps],
            "rep_ids": ids,
            "connected": len(comps) == 1,            # all reps in one edge-component
            "any_edge": len(edges) > 0,
            "largest_comp_frac": round(max(len(c) for c in comps) / len(reps), 3),
            "max_shared": max(p["shared"] for p in pair_feats),
            "max_jaccard": max(p["jaccard"] for p in pair_feats),
            "pairs": pair_feats,
        })

    Path("results").mkdir(exist_ok=True)
    Path("results/translit_candidates.json").write_bytes(
        json.dumps(groups, ensure_ascii=False).encode())

    n = len(groups)
    pairs_only = [g for g in groups if g["n_reps"] == 2]
    print(f"\ncandidate groups (2..{MAX_REPS} reps): {n}  (+{degenerate} degenerate >{MAX_REPS} skipped)")
    from collections import Counter
    sz = Counter(g["n_reps"] for g in groups)
    print("  group size dist:", dict(sorted(sz.items())))
    print(f"  fully connected (all reps one edge-component): {sum(g['connected'] for g in groups)} ({sum(g['connected'] for g in groups)/n:.1%})")
    print(f"  any direct edge:                               {sum(g['any_edge'] for g in groups)} ({sum(g['any_edge'] for g in groups)/n:.1%})")
    print(f"  max_shared >= 5:                               {sum(g['max_shared']>=5 for g in groups)} ({sum(g['max_shared']>=5 for g in groups)/n:.1%})")
    # pairs view
    pe = sum(g["any_edge"] for g in pairs_only)
    print(f"\n  pure pairs: {len(pairs_only)} | with edge: {pe} ({pe/max(len(pairs_only),1):.1%})")

    import random
    rng = random.Random(0)
    print("\n=== 18 random candidate groups (sanity-check the key) ===")
    for g in rng.sample(groups, min(18, n)):
        flag = "EDGE" if g["any_edge"] else "    "
        spp = " | ".join(f"{r['name']!r}(in={r['in']})" for r in g["reps"])
        print(f"  [{flag}] shared<= {g['max_shared']:<4} jac={g['max_jaccard']:.2f}  {spp}")


if __name__ == "__main__":
    main()
