"""Build the label sample for the Cyrillic-x fold: the NEW collab deletions it
unlocks (decompose into >=2 known members once a standalone Cyrillic/Greek 'x'
look-alike token is folded to Latin 'x', and then dropped by an EXISTING gate).
Enriched with Last.fm getInfo for identity labeling. Headline = the centrality
drops (the bulk); also carries the handful that survive to the m<->m gate."""
import json
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from analyze import load_names
from binio import GraphStore, uuid_to_bytes
from fetch_lastfm import getinfo
from keys import clean_str
from probe_refine import decompose, fold_connectors

SEED = 0


def main():
    data_dir = Path("../../data")
    store = GraphStore(data_dir.resolve())
    data = load_names(data_dir / "metadata.ndjson")
    names, phon = data["names"], data["phon_groups"]
    known_plain = set(phon)

    folded_phon = {}
    for aid, nm in names.items():
        folded_phon.setdefault(clean_str(fold_connectors(nm)), []).append(aid)
    known_folded = set(folded_phon)

    icache = {}

    def max_in(nn):
        v = icache.get(nn)
        if v is None:
            v = max((store.in_degree(uuid_to_bytes(i)) for i in folded_phon.get(nn, [])), default=0)
            icache[nn] = v
        return v

    cands = []
    for nm in names.values():
        plain = clean_str(nm)
        folded = clean_str(fold_connectors(nm))
        if folded == plain or decompose(plain, known_plain) is not None:
            continue
        d = decompose(folded, known_folded)
        if d is None:
            continue
        comps, has_feat = d
        mc = max(max_in(s) for s in comps)
        ci = max_in(folded)
        if has_feat:
            gate = "feat"
        elif mc and ci < 0.2 * mc:
            gate = "centrality"
        else:
            gate = "needs_mm"
        cands.append({"name": nm, "norm": folded, "comps": comps, "gate": gate,
                      "ratio": round(ci / mc, 3) if mc else None})

    # de-dup by folded norm (keep first original spelling)
    seen, uniq = set(), []
    for c in cands:
        if c["norm"] in seen:
            continue
        seen.add(c["norm"]); uniq.append(c)

    drops = [c for c in uniq if c["gate"] in ("feat", "centrality")]
    rng = random.Random(SEED)
    sample = rng.sample(drops, min(40, len(drops)))
    # include every needs_mm survivor too (rare, higher-risk)
    sample += [c for c in uniq if c["gate"] == "needs_mm"]

    print(f"unique new deletions: {len(drops)} (gate-dropped) + "
          f"{sum(1 for c in uniq if c['gate']=='needs_mm')} needs_mm | sampling {len(sample)}")

    def work(c):
        info = getinfo(c["name"])
        return {**c, "found": info.get("found"), "listeners": info.get("listeners"),
                "tags": info.get("tags"), "bio": info.get("bio")}

    with ThreadPoolExecutor(max_workers=4) as ex:
        out = list(ex.map(work, sample))

    Path("results/fold_label_input.json").write_bytes(
        json.dumps(out, ensure_ascii=False, indent=2).encode())
    found = sum(1 for o in out if o.get("found"))
    print(f"wrote {len(out)} rows ({found} found on Last.fm) -> results/fold_label_input.json")


if __name__ == "__main__":
    main()
