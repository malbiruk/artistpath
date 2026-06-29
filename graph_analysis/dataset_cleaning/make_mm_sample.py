"""Label sample for the m<->m co-occurrence gate. Headline stratum = random
new-deletions (mm>=0.5); plus two stress strata for the real-band FP class the
gate risks: 'the ...' segments (frontman+backing band) and <=2-char segments
(the AC/DC pattern). Enriched with Last.fm getInfo."""
import json
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fetch_lastfm import getinfo

SEED = 0


def main():
    surv = json.loads(Path("results/mm_survivors.json").read_text())
    pool = [s for s in surv if s["mm"] >= 0.5]
    rng = random.Random(SEED)

    a = rng.sample(pool, 150)
    a_norms = {s["norm"] for s in a}
    the = [s for s in pool if s["has_the"] and s["norm"] not in a_norms]
    short = [s for s in pool if s["min_seg_len"] <= 2 and s["norm"] not in a_norms]
    b = rng.sample(the, min(40, len(the)))
    b_norms = {s["norm"] for s in b}
    c = rng.sample([s for s in short if s["norm"] not in b_norms], min(40, len(short)))

    chosen = [("random", s) for s in a] + [("the_seg", s) for s in b] + [("short_seg", s) for s in c]
    print(f"pool mm>=0.5: {len(pool):,}  | sampled random={len(a)} the_seg={len(b)} short_seg={len(c)}")

    def work(args):
        stratum, s = args
        info = getinfo(s["name"])
        return {
            "name": s["name"], "norm": s["norm"], "comps": s["comps"],
            "mm": s["mm"], "ratio": s["ratio"], "n_seg": s["n_seg"],
            "has_the": s["has_the"], "min_seg_len": s["min_seg_len"], "stratum": stratum,
            "found": info.get("found"), "listeners": info.get("listeners"),
            "tags": info.get("tags"), "bio": info.get("bio"),
        }

    with ThreadPoolExecutor(max_workers=4) as ex:
        out = list(ex.map(work, chosen))
    # de-dup by norm (a name could qualify for two strata; keep first)
    seen, dedup = set(), []
    for o in out:
        if o["norm"] in seen:
            continue
        seen.add(o["norm"]); dedup.append(o)

    Path("results/mm_label_input.json").write_bytes(
        json.dumps(dedup, ensure_ascii=False, indent=2).encode()
    )
    found = sum(1 for o in dedup if o.get("found"))
    print(f"wrote {len(dedup)} rows ({found} found on Last.fm) -> results/mm_label_input.json")


if __name__ == "__main__":
    main()
