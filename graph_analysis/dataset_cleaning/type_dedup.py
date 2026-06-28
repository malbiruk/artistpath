"""Does difference-TYPE separate dedup same-vs-diff better than ratio?
Classifies each labeled meaningful pair by how the variant differs from the
canonical (ascii punctuation/case, Latin accent, or non-Latin script fold)."""
import json
import unicodedata
from collections import Counter


def char_class(ch: str) -> str | None:
    if not ch.isalpha():
        return None
    if ord(ch) < 128:
        return "ascii"
    nm = unicodedata.name(ch, "")
    return "latin-accent" if nm.startswith("LATIN") else "nonlatin"


def classify(v: str, c: str) -> str:
    chars = v + c
    if any(char_class(ch) == "nonlatin" for ch in chars):
        return "script-fold"      # homoglyph / fullwidth / Cyrillic / Greek
    if any(char_class(ch) == "latin-accent" for ch in chars):
        return "accent"           # é / ö / ñ
    return "ascii-punct"          # punctuation / case only


def main():
    labels = {}
    for i in range(3):
        for o in json.load(open(f"results/dedup_labels2_part{i}.json")):
            labels[o["i"]] = o["label"]
    recs = json.load(open("results/dedup_label_input2.json"))

    per = Counter()
    perlab = {}
    diffs = []
    for idx, r in enumerate(recs):
        if r["kind"] == "pure":
            t = "pure"
        else:
            t = classify(r["variant"], r["canonical"])
        lab = labels.get(idx, "?")
        perlab.setdefault(t, Counter())[lab] += 1
        per[t] += 1
        if t != "pure" and lab == "diff":
            diffs.append((t, r["variant"], r["canonical"]))

    print(f"{'diff type':14} {'n':>5} {'same/diff/?':>13} {'precision':>10}")
    for t in ("pure", "ascii-punct", "accent", "script-fold"):
        c = perlab.get(t, Counter())
        s, d = c["same"], c["diff"]
        p = s / (s + d) if s + d else 1.0
        print(f"{t:14} {per[t]:>5} {f'{s}/{d}/{c[chr(63)]}':>13} {p:>9.1%}")

    print("\nthe 'diff' (false-positive) examples by type:")
    for t, v, c in diffs:
        print(f"  [{t}] {v!r} vs {c!r}")


if __name__ == "__main__":
    main()
