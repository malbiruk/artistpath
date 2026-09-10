"""Measure the 'Strykalo' bucket: same clean_str, DIFFERENT skeletons (cross-script
variants the homoglyph skeleton can't fold, e.g. Valentin Strykalo / Валентин
Стрыкало both clean to 'valentin strykalo' but keep distinct skeletons). The
existing skeleton dedup misses these (different skeleton) and translit dedup misses
them (only one clean_str, no cross-clean block). For each such group we check
whether the per-skeleton representatives are edge-connected — the same gate that
worked for the translit case. No API calls."""
import json
from itertools import combinations
from pathlib import Path

from analyze import load_names
from binio import GraphStore, uuid_to_bytes
from keys import skeleton

DATA = Path("../../data")


def components(ids, edges):
    parent = {r: r for r in ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        parent[find(a)] = find(b)
    comp: dict = {}
    for r in ids:
        comp.setdefault(find(r), []).append(r)
    return list(comp.values())


def main():
    store = GraphStore(DATA.resolve())
    data = load_names(DATA / "metadata.ndjson")
    names, phon = data["names"], data["phon_groups"]

    multi_clean = 0          # clean_str groups with >=2 nodes
    bucket = []              # groups with >=2 distinct live skeletons
    for clean, ids in phon.items():
        if len(ids) < 2:
            continue
        multi_clean += 1
        # representative (highest in-degree node) per distinct skeleton
        skel_rep: dict[str, tuple[str, int]] = {}
        for aid in ids:
            sk = skeleton(names[aid])
            d = store.in_degree(uuid_to_bytes(aid))
            if sk not in skel_rep or d > skel_rep[sk][1]:
                skel_rep[sk] = (aid, d)
        live = {sk: v for sk, v in skel_rep.items() if v[1] > 0}
        if len(live) < 2:
            continue
        bucket.append((clean, live))

    # edge connectivity among each group's skeleton-reps
    edge_groups = 0
    drops = 0
    examples = []
    for clean, live in bucket:
        reps = [(sk, i, d) for sk, (i, d) in live.items()]
        ids = [i for _, i, _ in reps]
        nbrs = {i: store.out_neighbors(uuid_to_bytes(i)) for i in ids}
        edges = set()
        for (ska, ia, da), (skb, ib, db) in combinations(reps, 2):
            ba, bb = uuid_to_bytes(ia), uuid_to_bytes(ib)
            if bb in nbrs[ia] or ba in nbrs[ib]:
                edges.add(frozenset((ia, ib)))
        if not edges:
            continue
        edge_groups += 1
        indeg = {i: d for _, i, d in reps}
        for comp in components(ids, edges):
            if len(comp) >= 2:
                drops += len(comp) - 1
        examples.append((clean, sorted(reps, key=lambda r: -r[2])))

    print(f"\nmulti-node clean_str groups: {multi_clean:,}")
    print(f"  with >=2 distinct live skeletons (Strykalo bucket): {len(bucket):,}")
    print(f"  of those, edge-connected (would merge): {edge_groups:,} "
          f"({edge_groups / max(len(bucket), 1):.1%})")
    print(f"  nodes that would be dropped: {drops:,}")

    Path("results").mkdir(exist_ok=True)
    Path("results/sameclean_candidates.json").write_bytes(
        json.dumps(
            [{"clean": c, "reps": [{"name": names[i], "in": d} for _, i, d in r]}
             for c, r in examples],
            ensure_ascii=False,
        ).encode()
    )

    import random
    rng = random.Random(0)
    print("\n=== 20 random edge-connected groups (eyeball precision) ===")
    for clean, reps in rng.sample(examples, min(20, len(examples))):
        spp = " | ".join(f"{names[i]!r}(in={d})" for _, i, d in reps)
        print(f"  {clean!r:24} {spp}")


if __name__ == "__main__":
    main()
