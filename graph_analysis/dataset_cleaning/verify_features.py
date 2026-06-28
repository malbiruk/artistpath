"""Spot-check the Rule-2 decision on specific names: niche collabs should be
DELETEd, legit duos KEPT — without any popularity gate."""
import sys
from pathlib import Path

from analyze import load_names
from binio import GraphStore, uuid_to_bytes
from keys import clean_str, segment_name

CENTRALITY_FRAC = 0.5

NAMES = sys.argv[1:] or [
    # niche collabs (should DELETE)
    "flowers in your eyes feat. corn wave",
    "PHARAOH x ACID DROP KING",
    "поливокс, Corn Wave",
    "last past. & Corn Wave",
    "Devika Shawty, i61, Boulevard Depo & Acid Drop King",
    # legit duos / bands with weak connectors (should KEEP)
    "Simon & Garfunkel",
    "Hall & Oates",
    "Earth, Wind & Fire",
    "Macklemore & Ryan Lewis",
    # one-off pop collab (judgment call)
    "Calvin Harris & Dua Lipa",
]


def main() -> None:
    data_dir = Path("../../data").resolve()
    store = GraphStore(data_dir)
    data = load_names(data_dir / "metadata.ndjson")
    phon = data["phon_groups"]
    known = set(phon)

    def indeg(nn: str) -> int | None:
        if nn not in phon:
            return None
        return max(store.in_degree(uuid_to_bytes(a)) for a in phon[nn])

    for raw in NAMES:
        nn = clean_str(raw)
        segs, strong, weak = segment_name(nn)
        known_segs = [s for s in segs if s != nn and s in known]
        comp_ind = {s: indeg(s) for s in known_segs}
        ci = indeg(nn)

        if nn not in known:
            decision = "NODE NOT IN DATA"
        elif len(segs) < 2:
            decision = "KEEP (not a collab: <2 segments)"
        elif len(known_segs) < 2:
            decision = f"KEEP (only {len(known_segs)} known segment(s))"
        else:
            maxc = max(v for v in comp_ind.values() if v)
            secondary = ci is not None and ci < CENTRALITY_FRAC * maxc
            if strong or secondary:
                tags = "+".join([t for t, on in (("strong", strong), ("secondary", secondary)) if on])
                decision = f"DELETE ({tags})"
            else:
                decision = "KEEP (weak connector + central -> real duo/band)"

        print(f"\n{raw!r}")
        print(f"  norm={nn!r}  collab_in={ci}  strong={strong} weak={weak}")
        print(f"  segments={segs}")
        print(f"  known components={comp_ind}")
        print(f"  => {decision}")


if __name__ == "__main__":
    main()
