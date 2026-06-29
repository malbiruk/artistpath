"""Stratified label sample for the 'x' connector, enriched with Last.fm getInfo.

Reads results/x_candidates.json (all ' x '-decomposable all-known candidates),
keeps the production delete set (ratio<0.2), stratifies across ratio bins, fetches
artist.getInfo for each candidate name, and writes results/x_label_input.json for
an agent to label 'f' (collab/credit -> correct delete) or 'a' (real standalone
act -> FALSE POSITIVE)."""
import json
import random
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fetch_lastfm import getinfo

BINS = [(0.0, 0.01), (0.01, 0.05), (0.05, 0.10), (0.10, 0.20)]
PER_BIN = 50
SEED = 0


def bin_of(r: float) -> str:
    for lo, hi in BINS:
        if lo <= r < hi:
            return f"[{lo:.2f},{hi:.2f})"
    return "?"


def main() -> None:
    cands = json.loads(Path("results/x_candidates.json").read_text())
    delete = [c for c in cands if c["ratio"] < 0.2]

    buckets: dict[str, list] = defaultdict(list)
    for c in delete:
        buckets[bin_of(c["ratio"])].append(c)

    print("delete-set population by ratio bin:")
    for lo, hi in BINS:
        b = f"[{lo:.2f},{hi:.2f})"
        print(f"  {b:14} {len(buckets[b]):>7,}")

    rng = random.Random(SEED)
    chosen: list = []
    for lo, hi in BINS:
        b = f"[{lo:.2f},{hi:.2f})"
        items = buckets[b]
        chosen += [(b, c) for c in (items if len(items) <= PER_BIN else rng.sample(items, PER_BIN))]

    def work(args):
        b, c = args
        info = getinfo(c["name"])
        return {
            "name": c["name"],
            "norm": c["norm"],
            "ratio": c["ratio"],
            "collab_in": c["collab_in"],
            "segments": c["segments"],
            "r_bin": b,
            "found": info.get("found"),
            "listeners": info.get("listeners"),
            "tags": info.get("tags"),
            "bio": info.get("bio"),
        }

    with ThreadPoolExecutor(max_workers=4) as ex:
        out = list(ex.map(work, chosen))

    Path("results/x_label_input.json").write_bytes(
        json.dumps(out, ensure_ascii=False, indent=2).encode()
    )
    found = sum(1 for o in out if o.get("found"))
    print(f"\nwrote {len(out)} rows ({found} found on Last.fm) -> results/x_label_input.json")


if __name__ == "__main__":
    main()
