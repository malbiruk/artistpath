"""Capture the dedup rule's actual (variant -> canonical) deletions and write a
stratified labeling sample. Imports the SHIPPED skeleton/_is_latin from
data_collection/postprocessing/cleaning.py so we validate the real logic.

in-degree comes from rev-graph.bin via the fast mmap store (no 28GB stream)."""
import csv
import importlib.util
import random
import sys
from collections import defaultdict
from pathlib import Path

import orjson

from binio import GraphStore, uuid_to_bytes

DC = "/var/home/klimasos/Services/artistpath/data_collection"
sys.path.insert(0, DC)
from normalization import clean_str  # noqa: E402

# load the shipped cleaning module directly (avoid the package __init__ -> joblib)
_spec = importlib.util.spec_from_file_location("prod_cleaning", f"{DC}/postprocessing/cleaning.py")
_prod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_prod)
skeleton, is_latin = _prod.skeleton, _prod._is_latin

PER_KIND = 150


def main() -> None:
    data_dir = Path("../../data").resolve()
    store = GraphStore(data_dir)

    name_of: dict[str, str] = {}
    phon_groups: dict[str, list[str]] = defaultdict(list)
    skel_groups: dict[str, list[str]] = defaultdict(list)
    with (data_dir / "metadata.ndjson").open("rb") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                e = orjson.loads(line)
                aid, name = e["id"], e["name"]
            except (orjson.JSONDecodeError, KeyError):
                continue
            if not isinstance(name, str):
                continue
            name_of[aid] = name
            phon_groups[clean_str(name)].append(aid)
            skel_groups[skeleton(name)].append(aid)
    print(f"loaded {len(name_of):,} names")

    def indeg(i: str) -> int:
        return store.in_degree(uuid_to_bytes(i))

    # reproduce _identify_duplicates, recording (variant, canonical) per pass
    skel_pairs: dict[str, tuple] = {}   # variant_id -> (canonical_id, ktype)
    for key, ids in skel_groups.items():
        if not key or len(ids) < 2:
            continue
        canon = max(ids, key=indeg)
        cname = name_of[canon]
        for i in ids:
            if name_of[i] != cname:
                skel_pairs[i] = (canon, "skel")

    phon_pairs: dict[str, tuple] = {}
    for key, ids in phon_groups.items():
        if not key or len(ids) < 2:
            continue
        canon = max(ids, key=indeg)
        cname = name_of[canon]
        if not is_latin(cname):
            continue
        for i in ids:
            if i != canon and name_of[i] != cname and not is_latin(name_of[i]):
                phon_pairs[i] = (canon, "phon")

    all_variants = set(skel_pairs) | set(phon_pairs)
    print(f"dedup deletions: {len(all_variants):,}  (skel {len(skel_pairs):,}, phon {len(phon_pairs):,}, "
          f"overlap {len(set(skel_pairs) & set(phon_pairs)):,})")

    rng = random.Random(0)
    skel_only = [v for v in skel_pairs if v not in phon_pairs]
    phon_all = list(phon_pairs)
    sample = []
    for kind, pool, src in (("skel", skel_only, skel_pairs), ("phon", phon_all, phon_pairs)):
        pick = pool if len(pool) <= PER_KIND else rng.sample(pool, PER_KIND)
        for v in pick:
            canon = src[v][0]
            sample.append((kind, name_of[v], v, name_of[canon], canon, indeg(v), indeg(canon)))

    out = Path("results")
    out.mkdir(exist_ok=True)
    with (out / "dedup_sample.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["label", "kind", "variant", "variant_id", "canonical", "canonical_id",
                    "variant_in", "canonical_in"])
        for kind, vn, vid, cn, cid, vin, cin in sample:
            w.writerow(["", kind, vn, vid, cn, cid, vin, cin])
    print(f"wrote results/dedup_sample.csv ({len(sample)} rows: "
          f"{sum(1 for s in sample if s[0]=='skel')} skel + {sum(1 for s in sample if s[0]=='phon')} phon)")
    # record population sizes for later precision weighting
    (out / "dedup_pop.json").write_bytes(orjson.dumps(
        {"skel_only": len(skel_only), "phon": len(phon_all), "total": len(all_variants)}))


if __name__ == "__main__":
    main()
