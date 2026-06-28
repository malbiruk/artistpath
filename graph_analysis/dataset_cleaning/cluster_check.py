#!/usr/bin/env python3
"""Does widening past 1-hop recover the non-adjacent dupes?

1-hop adjacency confirms only ~20% of same-name collision groups, yet the
non-adjacent ones are mostly still obvious dupes (BOM/accent/translit variants).
This measures, for 2-member phonetic-collision groups, whether members sit in the
"same cluster": shared out-neighbors (a 2-hop proxy) and neighbor-overlap Jaccard.
Compared against a random-pair baseline. Read-only.
"""

import random
from pathlib import Path

import numpy as np
import orjson
from rich.console import Console
from rich.table import Table

from analyze import load_names
from binio import GraphStore, uuid_to_bytes

console = Console()


def jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def main() -> None:
    data_dir = Path("../../data").resolve()
    out_dir = Path("results").resolve()
    store = GraphStore(data_dir)
    data = load_names(data_dir / "metadata.ndjson")
    names, phon_groups = data["names"], data["phon_groups"]

    rng = random.Random(0)

    adj_jac: list[float] = []
    non_jac: list[float] = []
    non_share = 0          # non-adjacent pairs sharing >=1 out-neighbor
    non_total = 0
    non_ghost = 0          # non-adjacent pairs where >=1 member has 0 out-edges
    non_both_edges = 0     # non-adjacent pairs where both have out-edges
    recovered_samples: list[dict] = []     # non-adj, high overlap -> still a dupe
    homonym_samples: list[dict] = []       # non-adj, low overlap, both real -> different artist?

    for key, ids in phon_groups.items():
        if len(ids) != 2:
            continue
        a, b = uuid_to_bytes(ids[0]), uuid_to_bytes(ids[1])
        na, nb = store.out_neighbors(a), store.out_neighbors(b)
        j = jaccard(na, nb)
        if store.adjacent(a, b):
            adj_jac.append(j)
            continue
        non_total += 1
        non_jac.append(j)
        if not na or not nb:
            non_ghost += 1
            continue
        non_both_edges += 1
        if na & nb:
            non_share += 1
        ida, idb = store.in_degree(a), store.in_degree(b)
        rec = {
            "key": key,
            "a": {"name": names.get(ids[0]), "in": ida, "out": len(na)},
            "b": {"name": names.get(ids[1]), "in": idb, "out": len(nb)},
            "jaccard": round(j, 3),
            "shared_neighbors": len(na & nb),
        }
        if j >= 0.10 and len(recovered_samples) < 150:
            recovered_samples.append(rec)
        elif j == 0.0 and min(ida, idb) >= 20 and len(homonym_samples) < 150:
            homonym_samples.append(rec)

    # random-pair baseline jaccard (source nodes with out-edges)
    src = [k for k in store.fwd_index if store.out_degree(k) > 0]
    base_jac = []
    for _ in range(5000):
        x, y = rng.choice(src), rng.choice(src)
        base_jac.append(jaccard(store.out_neighbors(x), store.out_neighbors(y)))

    adj_arr = np.array(adj_jac) if adj_jac else np.array([0.0])
    non_arr = np.array(non_jac) if non_jac else np.array([0.0])
    nb_arr = np.array([j for j in non_jac if j > 0]) if non_jac else np.array([0.0])
    base_arr = np.array(base_jac)

    t = Table(title="neighbor-overlap (Jaccard of out-neighbors), 2-member collision groups")
    t.add_column("pair set")
    t.add_column("n", justify="right")
    t.add_column("median J", justify="right")
    t.add_column("mean J", justify="right")
    t.add_column(">=0.05", justify="right")
    t.add_column(">=0.20", justify="right")
    for label, arr in [
        ("1-hop ADJACENT", adj_arr),
        ("NON-adjacent (all)", non_arr),
        ("random baseline", base_arr),
    ]:
        t.add_row(
            label,
            f"{len(arr):,}",
            f"{np.median(arr):.3f}",
            f"{arr.mean():.3f}",
            f"{(arr >= 0.05).mean():.1%}",
            f"{(arr >= 0.20).mean():.1%}",
        )
    console.print(t)

    console.print(
        f"\nNON-adjacent 2-member groups: [cyan]{non_total:,}[/]\n"
        f"  >=1 member is a ghost (0 out-edges) -> degree/junk handles it: "
        f"[green]{non_ghost:,}[/] ({non_ghost / non_total:.1%})\n"
        f"  both have out-edges: [cyan]{non_both_edges:,}[/]; of those, "
        f"share >=1 out-neighbor (2-hop same cluster): "
        f"[green]{non_share:,}[/] ({non_share / non_both_edges:.1%})"
    )
    console.print(
        f"  random-pair baseline shares-neighbor rate ~ "
        f"[dim]{(base_arr > 0).mean():.2%}[/]"
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "cluster_recovered.json").write_bytes(
        orjson.dumps(recovered_samples, option=orjson.OPT_INDENT_2)
    )
    (out_dir / "cluster_homonym_candidates.json").write_bytes(
        orjson.dumps(homonym_samples, option=orjson.OPT_INDENT_2)
    )
    console.print(
        "[dim]samples -> cluster_recovered.json (non-adj but same cluster), "
        "cluster_homonym_candidates.json (non-adj, no overlap, both real)[/]"
    )


if __name__ == "__main__":
    main()
