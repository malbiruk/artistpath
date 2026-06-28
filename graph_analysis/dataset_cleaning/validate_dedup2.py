"""Validate a centrality gate for the skeleton dedup. Splits deletions into
'pure-junk' differences (invisible/whitespace/case -> always safe) and
'meaningful' differences (punctuation/accent/homoglyph -> where homonyms hide),
and stratifies the meaningful ones across ratio = variant_in/canonical_in so we
can sweep a threshold. Writes results/dedup_sample2.csv."""
import csv
import importlib.util
import random
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

import orjson

from binio import GraphStore, uuid_to_bytes

DC = "/var/home/klimasos/Services/artistpath/data_collection"
sys.path.insert(0, DC)
from normalization import clean_str  # noqa: E402,F401  (kept for parity / available)

_spec = importlib.util.spec_from_file_location("prod_cleaning", f"{DC}/postprocessing/cleaning.py")
_prod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_prod)
skeleton = _prod.skeleton

RATIO_BINS = [(0, 0.05), (0.05, 0.1), (0.1, 0.2), (0.2, 0.3), (0.3, 0.5), (0.5, 0.8), (0.8, 1.01)]
PER_BIN = 40
PURE_ANCHOR = 30


def pure_junk(a: str, b: str) -> bool:
    """True if a and b differ only by invisible (format/control) chars, case, or
    whitespace — never a way to make a distinct artist."""
    def norm(s: str) -> str:
        s = "".join(c for c in s if unicodedata.category(c) not in ("Cf", "Cc"))
        return " ".join(s.lower().split())
    return norm(a) == norm(b)


def bin_of(r: float) -> str:
    for lo, hi in RATIO_BINS:
        if lo <= r < hi:
            return f"[{lo:.2f},{hi:.2f})"
    return "?"


def main() -> None:
    data_dir = Path("../../data").resolve()
    store = GraphStore(data_dir)

    name_of: dict[str, str] = {}
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
            if isinstance(name, str):
                name_of[aid] = name
                skel_groups[skeleton(name)].append(aid)
    print(f"loaded {len(name_of):,} names")

    def indeg(i: str) -> int:
        return store.in_degree(uuid_to_bytes(i))

    pure_pool: list[tuple] = []
    buckets: dict[str, list[tuple]] = defaultdict(list)
    n_pure = n_meaning = 0
    for key, ids in skel_groups.items():
        if not key or len(ids) < 2:
            continue
        canon = max(ids, key=indeg)
        cin = indeg(canon)
        cname = name_of[canon]
        if cin == 0:
            continue
        for i in ids:
            if name_of[i] == cname:
                continue
            vin = indeg(i)
            ratio = vin / cin
            rec = (name_of[i], i, cname, canon, vin, cin, ratio)
            if pure_junk(name_of[i], cname):
                n_pure += 1
                pure_pool.append(rec)
            else:
                n_meaning += 1
                buckets[bin_of(ratio)].append(rec)

    print(f"skeleton deletions: pure-junk={n_pure:,}  meaningful-diff={n_meaning:,}")
    print("meaningful-diff by ratio bucket:")
    for lo, hi in RATIO_BINS:
        b = f"[{lo:.2f},{hi:.2f})"
        print(f"  {b:14} {len(buckets[b]):>8,}")

    rng = random.Random(0)
    sample = []
    for lo, hi in RATIO_BINS:
        b = f"[{lo:.2f},{hi:.2f})"
        pool = buckets[b]
        for rec in (pool if len(pool) <= PER_BIN else rng.sample(pool, PER_BIN)):
            sample.append(("meaning:" + b, *rec))
    for rec in (pure_pool if len(pure_pool) <= PURE_ANCHOR else rng.sample(pure_pool, PURE_ANCHOR)):
        sample.append(("pure", *rec))

    out = Path("results")
    out.mkdir(exist_ok=True)
    with (out / "dedup_sample2.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["label", "kind", "variant", "variant_id", "canonical", "canonical_id",
                    "variant_in", "canonical_in", "ratio"])
        for cat, vn, vid, cn, cid, vin, cin, ratio in sample:
            w.writerow(["", cat, vn, vid, cn, cid, vin, cin, f"{ratio:.3f}"])
    (out / "dedup_pop2.json").write_bytes(orjson.dumps({
        "pure": n_pure, "meaningful": n_meaning,
        "by_bucket": {f"[{lo:.2f},{hi:.2f})": len(buckets[f'[{lo:.2f},{hi:.2f})']) for lo, hi in RATIO_BINS},
    }))
    print(f"wrote results/dedup_sample2.csv ({len(sample)} rows)")


if __name__ == "__main__":
    main()
