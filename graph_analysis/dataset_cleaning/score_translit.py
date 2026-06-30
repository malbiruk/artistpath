"""Score the translit-dup validation. Majority vote of 3 labelers (s=same,
d=different, ?=unsure) is ground truth. Then cross-tab against the GRAPH signal
(connected = direct edge or >=5 shared neighbours) to answer:
  - base rate: of string-candidate pairs, how many are truly the same artist?
  - precision: of graph-connected pairs, how many are truly same?  (false-merge risk)
  - recall:    of truly-same pairs, how many does the graph connect?  (coverage)
"""
import json
from collections import Counter
from pathlib import Path

R = Path("results")


def main():
    rows = json.loads((R / "translit_label_input.json").read_text())
    votes = {i: [] for i in range(len(rows))}
    for p in range(3):
        for o in json.loads((R / f"translit_labels_p{p}.json").read_text()):
            votes[o["i"]].append(o["label"])

    def majority(i):
        c = Counter(votes[i])
        if not c:
            return "?"
        top, n = c.most_common(1)[0]
        # require a real majority (>=2 of 3); ties -> unsure
        return top if n >= 2 else "?"

    for i, r in enumerate(rows):
        r["label"] = majority(i)
        r["conn"] = r["connected"]
        r["_i"] = i

    same = [r for r in rows if r["label"] == "s"]
    diff = [r for r in rows if r["label"] == "d"]
    unsure = [r for r in rows if r["label"] == "?"]
    decided = same + diff
    print(f"n={len(rows)}  labeled same={len(same)} diff={len(diff)} unsure={len(unsure)}")
    print(f"BASE RATE same (of decided): {len(same)/max(len(decided),1):.1%}\n")

    def cell(conn, lab):
        return sum(1 for r in decided if r["conn"] == conn and r["label"] == lab)
    cs, cd = cell(True, "s"), cell(True, "d")
    ns, nd = cell(False, "s"), cell(False, "d")
    print("                 label=same   label=diff")
    print(f"  graph-connected   {cs:>6}      {cd:>6}")
    print(f"  not connected     {ns:>6}      {nd:>6}")
    print()
    if cs + cd:
        print(f"PRECISION  connected -> same:  {cs/(cs+cd):.1%}  ({cs}/{cs+cd})   "
              f"[1-this = false-merge rate of a graph gate]")
    if cs + ns:
        print(f"RECALL     same that are connected: {cs/(cs+ns):.1%}  ({cs}/{cs+ns})   "
              f"[coverage of a graph gate]")
    if nd + ns:
        print(f"of NOT-connected pairs, {nd/(nd+ns):.1%} are different "
              f"(so string-only merge would mis-delete that fraction)")

    print("\n=== graph-connected but labeled DIFFERENT (graph false positives) ===")
    for r in [x for x in decided if x["conn"] and x["label"] == "d"]:
        print(f"  edge={r['edge']} shared={r['shared']:<4} {r['a']!r} | {r['b']!r}  votes={votes[r['_i']]}")
    print("\n=== labeled SAME but NOT connected (graph misses — recall loss) ===")
    misses = [x for x in decided if (not x["conn"]) and x["label"] == "s"]
    print(f"  {len(misses)} of {len(same)} same-pairs. examples:")
    for r in misses[:12]:
        print(f"  in=({r['in_a']},{r['in_b']}) {r['a']!r} | {r['b']!r}")


if __name__ == "__main__":
    main()
