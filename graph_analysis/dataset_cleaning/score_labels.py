"""Merge labels with r-bins + full-population counts, estimate per-bin act-rate,
and sweep the centrality threshold to find the precision-vs-volume operating point."""
import csv
import json
from collections import defaultdict
from pathlib import Path

from analyze import load_names
from binio import GraphStore, uuid_to_bytes
from keys import segment_name

GRAY_BINS = [
    (0.05, 0.10), (0.10, 0.15), (0.15, 0.20), (0.20, 0.25), (0.25, 0.33),
    (0.33, 0.40), (0.40, 0.50), (0.50, 0.67), (0.67, 0.80), (0.80, 1.00),
]
ORDER = ["LOW(<0.05)"] + [f"[{lo:.2f},{hi:.2f})" for lo, hi in GRAY_BINS] + ["HIGH(>=1.0)"]


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
    labels: dict[str, str] = {}
    for i in range(3):
        for o in json.load(open(f"results/labels_part{i}.json")):
            labels[o["norm"]] = o["label"]

    sample_bin: dict[str, str] = {}
    for row in csv.DictReader(open("results/label_sample.csv")):
        sample_bin[row["norm"]] = row["r_bin"]

    per = defaultdict(lambda: {"a": 0, "f": 0, "?": 0})
    for norm, lab in labels.items():
        per[sample_bin[norm]][lab if lab in ("a", "f", "?") else "?"] += 1

    # full population per bin
    store = GraphStore(Path("../../data").resolve())
    data = load_names(Path("../../data/metadata.ndjson").resolve())
    phon, known = data["phon_groups"], set(data["phon_groups"])
    cache: dict[str, int] = {}

    def indeg(nn: str) -> int:
        v = cache.get(nn)
        if v is None:
            v = max(store.in_degree(uuid_to_bytes(a)) for a in phon[nn])
            cache[nn] = v
        return v

    pop = defaultdict(int)
    for nn in known:
        if " " not in nn:
            continue
        segs, _, _ = segment_name(nn)
        if len(segs) < 2:
            continue
        ks = [s for s in segs if s != nn and s in known]
        if len(ks) < 2 or len(ks) != len(segs):
            continue
        mc = max(indeg(s) for s in ks)
        if mc:
            pop[bin_of(indeg(nn) / mc)] += 1

    print(f"\n{'r-bin':14} {'pop':>10} {'sampled(a/f/?)':>15} {'act-rate':>9}")
    act_rate: dict[str, float] = {}
    for b in ORDER:
        a, f, q = per[b]["a"], per[b]["f"], per[b]["?"]
        ar = a / (a + f) if (a + f) else 0.0
        act_rate[b] = ar
        print(f"{b:14} {pop[b]:>10,} {f'{a}/{f}/{q}':>15} {ar:>8.0%}")

    # threshold sweep: delete everything with r < t. estimate acts wrongly deleted.
    edges = [0.05, 0.10, 0.15, 0.20, 0.25, 0.33, 0.40, 0.50, 0.67, 0.80, 1.00]
    print(f"\n{'threshold r<':12} {'deletes':>11} {'est. real acts deleted':>24} {'est. precision':>15}")
    for t in edges:
        del_pop = 0
        acts = 0.0
        for b in ORDER:
            if b == "LOW(<0.05)":
                lo_hi = (0.0, 0.05)
            elif b == "HIGH(>=1.0)":
                lo_hi = (1.0, 9e9)
            else:
                lo_hi = next((lo, hi) for lo, hi in GRAY_BINS if f"[{lo:.2f},{hi:.2f})" == b)
            if lo_hi[1] <= t:  # bin fully below threshold -> deleted
                del_pop += pop[b]
                acts += pop[b] * act_rate[b]
        prec = 1 - acts / del_pop if del_pop else 0.0
        print(f"r < {t:<8} {del_pop:>11,} {acts:>24,.0f} {prec:>14.1%}")


if __name__ == "__main__":
    main()
