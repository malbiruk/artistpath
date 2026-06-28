"""Would enabling 'and'/'with' as connectors be safe? Find names that split on
'and'/'with' into >=2 ALL-known-artist segments, classify keep(central) vs
delete(secondary), and dump samples to eyeball for band-name false positives."""
import re
from pathlib import Path

import orjson

from analyze import load_names
from binio import GraphStore, uuid_to_bytes
from keys import _SPLIT_CHARS

CENTRALITY_FRAC = 0.5
AND_WORDS = {"and", "with", "n"}
_SPLIT_RE = re.compile(f"([{re.escape(_SPLIT_CHARS)}])")
_PUNCT = ".,!?'\"-()[]&+*/|"


def segment_and(norm: str) -> tuple[list[str], bool]:
    segs: list[str] = []
    cur: list[str] = []
    used_and = False
    for tok in norm.split():
        for p in _SPLIT_RE.split(tok):
            if not p:
                continue
            if p in _SPLIT_CHARS:
                if cur:
                    segs.append(" ".join(cur))
                    cur = []
                continue
            if p.strip(_PUNCT) in AND_WORDS:
                if cur:
                    segs.append(" ".join(cur))
                    cur = []
                used_and = True
            else:
                cur.append(p)
    if cur:
        segs.append(" ".join(cur))
    return [s for s in segs if s], used_and


def main() -> None:
    data_dir = Path("../../data").resolve()
    store = GraphStore(data_dir)
    data = load_names(data_dir / "metadata.ndjson")
    phon, names, known = data["phon_groups"], data["names"], set(data["phon_groups"])

    def indeg(nn: str) -> int:
        return max(store.in_degree(uuid_to_bytes(a)) for a in phon[nn])

    n_split = n_allknown = n_delete = n_keep = 0
    del_samples: list[dict] = []
    keep_samples: list[dict] = []

    for nn in known:
        padded = f" {nn} "
        if " and " not in padded and " with " not in padded and " n " not in padded:
            continue
        segs, used_and = segment_and(nn)
        if not used_and or len(segs) < 2:
            continue
        n_split += 1
        ks = [s for s in segs if s != nn and s in known]
        if len(ks) < 2 or len(ks) != len(segs):  # require ALL segments be known artists
            continue
        n_allknown += 1
        ci = indeg(nn)
        mc = max(indeg(s) for s in ks)
        secondary = ci < CENTRALITY_FRAC * mc
        row = {
            "name": names[phon[nn][0]],
            "collab_in": ci,
            "segments": {s: indeg(s) for s in ks},
            "secondary": secondary,
        }
        if secondary:
            n_delete += 1
            if len(del_samples) < 150:
                del_samples.append(row)
        else:
            n_keep += 1
            if len(keep_samples) < 80:
                keep_samples.append(row)

    print(f"\nnames splitting on and/with/n that contain the token: {n_split:,}")
    print(f"  ...into >=2 ALL-known-artist segments:  {n_allknown:,}")
    print(f"     would DELETE (secondary):            {n_delete:,}")
    print(f"     would KEEP (central -> real band):   {n_keep:,}")

    Path("results").mkdir(exist_ok=True)
    Path("results/and_delete.json").write_bytes(orjson.dumps(del_samples, option=orjson.OPT_INDENT_2))
    Path("results/and_keep.json").write_bytes(orjson.dumps(keep_samples, option=orjson.OPT_INDENT_2))
    print("  samples -> and_delete.json (EYEBALL for real-band FPs), and_keep.json")


if __name__ == "__main__":
    main()
