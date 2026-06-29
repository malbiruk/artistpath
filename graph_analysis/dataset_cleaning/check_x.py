"""Would enabling 'x' as a collab connector be safe? Find names that split on a
standalone 'x' token into >=2 ALL-known-artist segments, compute the centrality
ratio (collab_in / max_member_in), and dump every candidate for labeling so the
threshold can be swept like the main collab rule was."""
import re
from pathlib import Path

import orjson

from analyze import load_names
from binio import GraphStore, uuid_to_bytes
from keys import _SPLIT_CHARS

X_WORDS = {"x"}  # clean_str maps the '×' multiplication sign to 'x' too
_SPLIT_RE = re.compile(f"([{re.escape(_SPLIT_CHARS)}])")
_PUNCT = ".,!?'\"-()[]&+*/|"


def segment_x(norm: str) -> tuple[list[str], bool]:
    segs: list[str] = []
    cur: list[str] = []
    used = False
    for tok in norm.split():
        for p in _SPLIT_RE.split(tok):
            if not p:
                continue
            if p in _SPLIT_CHARS:
                if cur:
                    segs.append(" ".join(cur))
                    cur = []
                continue
            if p.strip(_PUNCT) in X_WORDS:
                if cur:
                    segs.append(" ".join(cur))
                    cur = []
                used = True
            else:
                cur.append(p)
    if cur:
        segs.append(" ".join(cur))
    return [s for s in segs if s], used


def main() -> None:
    data_dir = Path("../../data").resolve()
    store = GraphStore(data_dir)
    data = load_names(data_dir / "metadata.ndjson")
    phon, names, known = data["phon_groups"], data["names"], set(data["phon_groups"])

    def indeg(nn: str) -> int:
        return max(store.in_degree(uuid_to_bytes(a)) for a in phon[nn])

    n_split = n_allknown = 0
    cands: list[dict] = []

    for nn in known:
        if " x " not in f" {nn} ":
            continue
        segs, used = segment_x(nn)
        if not used or len(segs) < 2:
            continue
        n_split += 1
        ks = [s for s in segs if s != nn and s in known]
        if len(ks) < 2 or len(ks) != len(segs):  # require ALL segments be known artists
            continue
        n_allknown += 1
        ci = indeg(nn)
        mc = max(indeg(s) for s in ks)
        ratio = ci / mc if mc else 1.0
        cands.append({
            "name": names[phon[nn][0]],
            "norm": nn,
            "collab_in": ci,
            "segments": {s: indeg(s) for s in ks},
            "max_member_in": mc,
            "ratio": round(ratio, 4),
        })

    cands.sort(key=lambda r: r["ratio"])
    n_del = sum(1 for c in cands if c["ratio"] < 0.2)

    print(f"\nnames with a standalone ' x ' token:            {n_split:,}")
    print(f"  ...splitting into >=2 ALL-known segments:     {n_allknown:,}")
    print(f"     would DELETE at ratio<0.2 (production):    {n_del:,}")
    print(f"     would KEEP (central -> real artist):       {n_allknown - n_del:,}")

    Path("results").mkdir(exist_ok=True)
    Path("results/x_candidates.json").write_bytes(
        orjson.dumps(cands, option=orjson.OPT_INDENT_2)
    )
    print(f"\n  {len(cands):,} candidates -> results/x_candidates.json")


if __name__ == "__main__":
    main()
