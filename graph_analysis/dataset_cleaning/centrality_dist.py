"""Distribution of the centrality ratio r = collab_in / max(component_in) over
all decomposable+all-known collab candidates. Reveals whether there's a natural
valley (data-driven threshold) or just a slope (pure tradeoff). No labels needed."""
from collections import Counter
from pathlib import Path

import numpy as np

from analyze import load_names
from binio import GraphStore, uuid_to_bytes
from keys import segment_name


def main() -> None:
    data_dir = Path("../../data").resolve()
    store = GraphStore(data_dir)
    data = load_names(data_dir / "metadata.ndjson")
    phon, known = data["phon_groups"], set(data["phon_groups"])

    indeg_cache: dict[str, int] = {}

    def indeg(nn: str) -> int:
        v = indeg_cache.get(nn)
        if v is None:
            v = max(store.in_degree(uuid_to_bytes(a)) for a in phon[nn])
            indeg_cache[nn] = v
        return v

    ratios: list[float] = []
    ratios_feat: list[float] = []
    ratios_sym: list[float] = []
    for nn in known:
        if " " not in nn:
            continue
        segs, has_strong, _ = segment_name(nn)
        if len(segs) < 2:
            continue
        ks = [s for s in segs if s != nn and s in known]
        if len(ks) < 2 or len(ks) != len(segs):
            continue
        mc = max(indeg(s) for s in ks)
        if mc == 0:
            continue
        r = indeg(nn) / mc
        ratios.append(r)
        (ratios_feat if has_strong else ratios_sym).append(r)

    arr = np.array(ratios)
    print(f"\ncandidates (decomposable, all-known): {len(arr):,}")
    print(f"r = collab_in / max(component_in)   median={np.median(arr):.3f}  mean={arr.mean():.3f}")

    edges = [0, 0.01, 0.025, 0.05, 0.1, 0.15, 0.2, 0.25, 0.33, 0.5, 0.67, 0.8, 1.0, 1.5, 2.0, 5.0, np.inf]
    hist, _ = np.histogram(arr, bins=edges)
    print("\nhistogram of r (look for a dip = natural threshold):")
    peak = hist.max()
    for i, c in enumerate(hist):
        lo, hi = edges[i], edges[i + 1]
        bar = "#" * int(60 * c / peak)
        print(f"  [{lo:>5}, {hi:>5}) {c:>9,}  {bar}")

    print("\ndeletes vs threshold (cumulative r < t):")
    for t in (0.05, 0.1, 0.25, 0.5, 0.75, 1.0):
        n = int((arr < t).sum())
        print(f"  r < {t:<4}  ->  {n:>9,} deletes  ({n / len(arr):.1%})")

    print(f"\nby split type:  feat={len(ratios_feat):,} (median r={np.median(ratios_feat):.3f})  "
          f"symbol={len(ratios_sym):,} (median r={np.median(ratios_sym):.3f})")


if __name__ == "__main__":
    main()
