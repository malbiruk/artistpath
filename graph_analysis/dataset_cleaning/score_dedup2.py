"""Threshold sweep for the dedup centrality gate."""
import json
from collections import Counter

BINS = [(0, 0.05), (0.05, 0.1), (0.1, 0.2), (0.2, 0.3), (0.3, 0.5), (0.5, 0.8), (0.8, 1.01)]


def bname(lo, hi):
    return f"[{lo:.2f},{hi:.2f})"


def prec(c):
    s, d = c["same"], c["diff"]
    return s / (s + d) if s + d else 1.0


def main():
    labels = {}
    for i in range(3):
        for o in json.load(open(f"results/dedup_labels2_part{i}.json")):
            labels[o["i"]] = o["label"]
    recs = json.load(open("results/dedup_label_input2.json"))
    pop = json.load(open("results/dedup_pop2.json"))

    per = {bname(lo, hi): Counter() for lo, hi in BINS}
    pure = Counter()
    for idx, r in enumerate(recs):
        lab = labels.get(idx, "?")
        k = r["kind"]
        (pure if k == "pure" else per[k.split(":", 1)[1]])[lab] += 1

    print(f"pure-junk (always delete): same={pure['same']} diff={pure['diff']} ?={pure['?']}  "
          f"precision={prec(pure):.1%}  pop={pop['pure']:,}")

    print(f"\n{'ratio bucket':14} {'pop':>9} {'same/diff/?':>13} {'precision':>10}")
    pb = {}
    for lo, hi in BINS:
        b = bname(lo, hi)
        c = per[b]
        pb[b] = prec(c)
        sdq = f"{c['same']}/{c['diff']}/{c['?']}"
        print(f"{b:14} {pop['by_bucket'][b]:>9,} {sdq:>13} {pb[b]:>9.1%}")

    np_, pp = pop["pure"], prec(pure)
    print(f"\n{'threshold':16} {'deletions':>11} {'precision':>10}  (delete pure-junk + meaningful with ratio<t)")
    for _lo, hi in BINS:
        t = hi
        dele, corr = np_, pp * np_
        for lo2, hi2 in BINS:
            if hi2 <= t + 1e-9:
                b = bname(lo2, hi2)
                n = pop["by_bucket"][b]
                dele += n
                corr += pb[b] * n
        print(f"ratio < {t:<8} {dele:>11,} {corr / dele:>9.1%}")

    alln = np_ + pop["meaningful"]
    allc = pp * np_ + sum(pb[bname(lo, hi)] * pop["by_bucket"][bname(lo, hi)] for lo, hi in BINS)
    print(f"\nno gate (current): {alln:,} deletions, precision ~ {allc / alln:.1%}")


if __name__ == "__main__":
    main()
