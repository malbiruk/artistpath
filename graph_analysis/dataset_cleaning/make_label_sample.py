"""Generate a stratified labeling sample to set the centrality threshold.

Samples decomposable+all-known collab candidates evenly across r-bins in the
ambiguous gray band [0.05, 1.0], plus anchors below/above. You label each row
'f' (feature/credit -> delete) or 'a' (real act/band -> keep). We then compute,
per r-bin, the fraction of real acts, and pick the threshold where acts appear.
"""
import csv
import random
from collections import defaultdict
from pathlib import Path

import orjson

from analyze import load_names, rep_id
from binio import GraphStore, uuid_to_bytes
from keys import segment_name

GRAY_BINS = [
    (0.05, 0.10), (0.10, 0.15), (0.15, 0.20), (0.20, 0.25), (0.25, 0.33),
    (0.33, 0.40), (0.40, 0.50), (0.50, 0.67), (0.67, 0.80), (0.80, 1.00),
]
PER_BIN = 30
ANCHOR = 15
SEED = 0


def bin_of(r: float) -> str:
    if r < 0.05:
        return "LOW(<0.05)"
    if r >= 1.0:
        return "HIGH(>=1.0)"
    for lo, hi in GRAY_BINS:
        if lo <= r < hi:
            return f"[{lo:.2f},{hi:.2f})"
    return "?"


def main() -> None:
    data_dir = Path("../../data").resolve()
    out = Path("results")
    out.mkdir(exist_ok=True)
    store = GraphStore(data_dir)
    data = load_names(data_dir / "metadata.ndjson")
    phon, names, known = data["phon_groups"], data["names"], set(data["phon_groups"])

    indeg_cache: dict[str, int] = {}
    rep_cache: dict[str, str] = {}

    def indeg(nn: str) -> int:
        v = indeg_cache.get(nn)
        if v is None:
            v = max(store.in_degree(uuid_to_bytes(a)) for a in phon[nn])
            indeg_cache[nn] = v
        return v

    def rep(nn: str) -> str:
        v = rep_cache.get(nn)
        if v is None:
            v = rep_id(store, phon[nn])
            rep_cache[nn] = v
        return v

    buckets: dict[str, list] = defaultdict(list)
    for nn in known:
        if " " not in nn:
            continue
        segs, strong, _ = segment_name(nn)
        if len(segs) < 2:
            continue
        ks = [s for s in segs if s != nn and s in known]
        if len(ks) < 2 or len(ks) != len(segs):
            continue
        mc = max(indeg(s) for s in ks)
        if mc == 0:
            continue
        r = indeg(nn) / mc
        buckets[bin_of(r)].append((nn, r, ks, strong))

    rng = random.Random(SEED)
    chosen: list = []
    for b, items in buckets.items():
        k = ANCHOR if b.startswith(("LOW", "HIGH")) else PER_BIN
        chosen += [(b, *it) for it in (items if len(items) <= k else rng.sample(items, k))]

    # fetch Last.fm urls for the chosen collab nodes (one pass over metadata)
    want = {rep(nn) for (_b, nn, _r, _ks, _s) in chosen}
    url: dict[str, str] = {}
    with (data_dir / "metadata.ndjson").open("rb") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                e = orjson.loads(line)
            except orjson.JSONDecodeError:
                continue
            if e["id"] in want:
                url[e["id"]] = e.get("url", "")
                if len(url) == len(want):
                    break

    chosen.sort(key=lambda c: c[2])  # by r ascending, easiest-to-hardest

    path = out / "label_sample.csv"
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(
            ["label", "name", "url", "r", "collab_in", "components", "n_seg", "r_bin", "norm"]
        )
        for b, nn, r, ks, strong in chosen:
            rid = rep(nn)
            comps = "; ".join(f"{s} (in={indeg(s)})" for s in ks)
            w.writerow(
                [
                    "",                       # <- you fill: f=feature/credit, a=act/band, ?=unsure
                    names.get(rid, nn),
                    url.get(rid, ""),
                    f"{r:.3f}",
                    indeg(nn),
                    comps,
                    len(ks),
                    b,
                    nn,
                ]
            )

    n_gray = sum(1 for c in chosen if not c[0].startswith(("LOW", "HIGH")))
    print(f"\nwrote {path}  ({len(chosen)} rows: {n_gray} gray-band + anchors)")
    print("label column: 'f' = feature/credit (delete), 'a' = real act/band (keep), '?' = unsure")
    print("rows sorted by r ascending (low r = obvious credits, high r = real acts emerge)")


if __name__ == "__main__":
    main()
