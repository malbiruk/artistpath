"""Score the m<->m co-occurrence gate: headline precision on the random stratum
(at mm>=0.5 and mm>=1.0), FP rate in the frontman ('the ...') and short-segment
(AC/DC) stress strata, the effect of guards, and a dump of every false positive."""
import json
from collections import Counter
from pathlib import Path


def prec(c):
    f, a = c["f"], c["a"]
    return f / (f + a) if (f + a) else 1.0


def main():
    rows = json.loads(Path("results/mm_label_input.json").read_text())
    labels = {}
    for i in range(3):
        for o in json.loads(Path(f"results/mm_labels_p{i}.json").read_text()):
            labels[o["i"]] = o["label"]
    for j, r in enumerate(rows):
        r["label"] = labels.get(j, "?")

    rnd = [r for r in rows if r["stratum"] == "random"]
    the = [r for r in rows if r["stratum"] == "the_seg"]
    short = [r for r in rows if r["stratum"] == "short_seg"]

    def tally(rs):
        c = Counter()
        for r in rs:
            c[r["label"]] += 1
        return c

    print("=== HEADLINE: random stratum (unbiased precision of new mm deletions) ===")
    cr = tally(rnd)
    print(f"  mm>=0.5 : {prec(cr):.1%}  (f={cr['f']} a={cr['a']} ?={cr['?']}, n={len(rnd)})")
    r10 = [r for r in rnd if r["mm"] >= 1.0]
    c10 = tally(r10)
    print(f"  mm>=1.0 : {prec(c10):.1%}  (f={c10['f']} a={c10['a']} ?={c10['?']}, n={len(r10)})")

    print("\n=== STRESS strata (oversampled FP classes) ===")
    print(f"  'the ...' segment : precision {prec(tally(the)):.1%}  (f={tally(the)['f']} a={tally(the)['a']} ?={tally(the)['?']}, n={len(the)})")
    print(f"  <=2-char segment  : precision {prec(tally(short)):.1%}  (f={tally(short)['f']} a={tally(short)['a']} ?={tally(short)['?']}, n={len(short)})")

    print("\n=== GUARD effect on random stratum (skip has_the OR min_seg_len<=2) ===")
    guarded = [r for r in rnd if not r["has_the"] and r["min_seg_len"] > 2]
    removed = [r for r in rnd if r["has_the"] or r["min_seg_len"] <= 2]
    print(f"  after guard: {prec(tally(guarded)):.1%}  (kept {len(guarded)} of {len(rnd)} random; guard removed {len(removed)})")
    rem_fp = sum(1 for r in removed if r["label"] == "a")
    print(f"  guard removed {len(removed)} rows, {rem_fp} of them were FPs ('a')")

    print("\n=== ALL false positives (label 'a') ===")
    for r in rows:
        if r["label"] == "a":
            print(f"  [{r['stratum']:9}] {r['name'][:34]!r:36} mm={r['mm']} ratio={r['ratio']} "
                  f"the={int(r['has_the'])} minlen={r['min_seg_len']} comps={r['comps']} tags={r['tags']}")


if __name__ == "__main__":
    main()
