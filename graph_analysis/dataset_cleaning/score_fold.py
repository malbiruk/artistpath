"""Score the Cyrillic-x fold's new deletions. Precision = fraction the labelers
call collab credits ('f') by majority of 3. Breaks out the headline (centrality/
feat drops the fold delivers directly) from the needs_mm survivors, and dumps any
node a majority labeled a real standalone act ('a') -- the false positives."""
import json
from collections import Counter
from pathlib import Path


def main():
    rows = json.loads(Path("results/fold_label_input.json").read_text())
    votes = {i: [] for i in range(len(rows))}
    for p in range(3):
        for o in json.loads(Path(f"results/fold_labels_p{p}.json").read_text()):
            votes[o["i"]].append(o["label"])

    def majority(i):
        c = Counter(votes[i])
        return c.most_common(1)[0][0] if c else "?"

    for r in rows:
        r["label"] = majority(rows.index(r))

    def prec(rs):
        f = sum(1 for r in rs if r["label"] == "f")
        a = sum(1 for r in rs if r["label"] == "a")
        q = sum(1 for r in rs if r["label"] == "?")
        n = len(rs)
        p = f / (f + a) if (f + a) else 1.0
        return p, f, a, q, n

    headline = [r for r in rows if r["gate"] in ("centrality", "feat")]
    needs_mm = [r for r in rows if r["gate"] == "needs_mm"]

    p, f, a, q, n = prec(headline)
    print(f"=== HEADLINE: fold's direct new deletions (centrality/feat gate) ===")
    print(f"  precision {p:.1%}  (f={f} a={a} ?={q}, n={n})")
    p2, f2, a2, q2, n2 = prec(needs_mm)
    print(f"\n=== needs_mm survivors (deleted only if 1-hop m<->m also fires) ===")
    print(f"  identity-collab rate {p2:.1%}  (f={f2} a={a2} ?={q2}, n={n2})")
    p3, f3, a3, q3, n3 = prec(rows)
    print(f"\n=== ALL sampled ===")
    print(f"  precision {p3:.1%}  (f={f3} a={a3} ?={q3}, n={n3})")

    print("\n=== any node a majority called REAL ('a') -- the FPs ===")
    fps = [r for r in rows if r["label"] == "a"]
    if not fps:
        print("  (none)")
    for r in fps:
        print(f"  [{r['gate']:10}] {r['name'][:40]!r:42} comps={r['comps']} "
              f"listeners={r['listeners']} tags={r['tags']} votes={votes[rows.index(r)]}")

    print("\n=== any '?' ===")
    for r in rows:
        if r["label"] == "?":
            print(f"  {r['name'][:46]!r}  votes={votes[rows.index(r)]}")


if __name__ == "__main__":
    main()
