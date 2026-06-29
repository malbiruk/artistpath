"""Score the 'x'-connector validation: per-ratio-bin precision + a population-
weighted estimate over the full delete set, and list the false positives."""
import json
from collections import Counter
from pathlib import Path

BINS = [(0.0, 0.01), (0.01, 0.05), (0.05, 0.10), (0.10, 0.20)]


def bname(lo, hi):
    return f"[{lo:.2f},{hi:.2f})"


def prec(c):
    f, a = c["f"], c["a"]
    return f / (f + a) if (f + a) else 1.0


def main() -> None:
    rows = {r_i: r for r_i, r in enumerate(json.loads(Path("results/x_label_input.json").read_text()))}
    labels: dict[int, str] = {}
    for i in range(3):
        for o in json.loads(Path(f"results/x_labels_p{i}.json").read_text()):
            labels[o["i"]] = o["label"]

    # full delete-set population per bin (for weighting)
    cands = json.loads(Path("results/x_candidates.json").read_text())
    pop = Counter()
    for c in cands:
        if c["ratio"] < 0.2:
            for lo, hi in BINS:
                if lo <= c["ratio"] < hi:
                    pop[bname(lo, hi)] += 1
    total_pop = sum(pop.values())

    per = {bname(lo, hi): Counter() for lo, hi in BINS}
    fps = []
    for i, r in rows.items():
        lab = labels.get(i, "?")
        per[r["r_bin"]][lab] += 1
        if lab == "a":
            fps.append((r["ratio"], r["name"], r.get("tags"), r["segments"]))

    print(f"{'ratio bin':14} {'pop':>8} {'sampled f/a/?':>16} {'precision':>10}")
    wsum = 0.0
    for lo, hi in BINS:
        b = bname(lo, hi)
        c = per[b]
        p = prec(c)
        wsum += p * pop[b]
        print(f"{b:14} {pop[b]:>8,} {f'{c[chr(102)]}/{c[chr(97)]}/{c[chr(63)]}':>16} {p:>9.1%}")

    overall = Counter()
    for c in per.values():
        overall.update(c)
    print(f"\nsample precision (all bins pooled): {prec(overall):.1%}  "
          f"(f={overall['f']} a={overall['a']} ?={overall['?']})")
    print(f"population-weighted precision over {total_pop:,} deletions: {wsum / total_pop:.1%}")

    print(f"\nfalse positives (label 'a' = real act wrongly deleted), {len(fps)} of {sum(overall.values())}:")
    for ratio, name, tags, segs in sorted(fps):
        print(f"  r={ratio:<7} {name!r}  tags={tags}  segs={list(segs)}")


if __name__ == "__main__":
    main()
