"""Step B: sample candidate PAIRS from results/translit_candidates.json,
stratified into graph-connected vs not, enrich BOTH names with Last.fm getInfo
(canonical name + mbid + listeners + tags + bio), and write the label input.
Labelers then judge same-artist vs different; score_translit cross-tabs the
verdict against the graph signal and the Last.fm mbid/name signal."""
import json
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fetch_lastfm import getinfo

SEED = 0
N_CONNECTED = 45
N_OTHER = 80


def main():
    groups = json.loads(Path("results/translit_candidates.json").read_text())
    pairs = [g for g in groups if g["n_reps"] == 2]
    for p in pairs:
        p["connected"] = p["any_edge"] or p["max_shared"] >= 5

    connected = [p for p in pairs if p["connected"]]
    other = [p for p in pairs if not p["connected"]]
    rng = random.Random(SEED)
    sample = (rng.sample(connected, min(N_CONNECTED, len(connected)))
              + rng.sample(other, min(N_OTHER, len(other))))
    rng.shuffle(sample)
    print(f"pairs: {len(pairs)} (connected {len(connected)}, other {len(other)}) "
          f"| sampling {len(sample)}")

    def enrich(p):
        a, b = p["reps"][0], p["reps"][1]
        ia, ib = getinfo(a["name"]), getinfo(b["name"])
        return {
            "a": a["name"], "b": b["name"],
            "a_clean": a["clean"], "b_clean": b["clean"],
            "in_a": a["in"], "in_b": b["in"],
            "edge": p["any_edge"], "shared": p["max_shared"], "jaccard": p["max_jaccard"],
            "connected": p["connected"],
            "a_info": ia, "b_info": ib,
        }

    with ThreadPoolExecutor(max_workers=4) as ex:
        out = list(ex.map(enrich, sample))

    Path("results/translit_label_input.json").write_bytes(
        json.dumps(out, ensure_ascii=False, indent=2).encode())

    both_found = sum(1 for o in out if o["a_info"].get("found") and o["b_info"].get("found"))
    mbid_match = sum(
        1 for o in out
        if o["a_info"].get("mbid") and o["a_info"].get("mbid") == o["b_info"].get("mbid")
    )
    print(f"wrote {len(out)} -> results/translit_label_input.json")
    print(f"  both found on Last.fm: {both_found} | same mbid: {mbid_match}")


if __name__ == "__main__":
    main()
