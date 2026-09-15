"""Re-measure churn counting only edges above a match threshold.

Most of a Last.fm similar list sits near zero match, and those tail entries
reorder constantly -- lists crawled two days ago already showed ~8% churn,
which is jitter, not news. This re-runs the churn probe on the SAME artists
(read back by the byte offsets recorded in discovery_probe.json) and reports
churn both over all edges and over edges with match > THRESHOLD.

Read-only. Uses LASTFM_API_KEY so it does not contend with the collector.
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import aiohttp

from collection import api_client
from collection.api_client import is_real_mbid

DATA_DIR = Path("../data")
GRAPH = DATA_DIR / "graph.ndjson"
METADATA = DATA_DIR / "metadata.ndjson"
PREV = DATA_DIR / "validation" / "discovery_probe.json"
OUT = DATA_DIR / "validation" / "churn_threshold.json"

THRESHOLD = 0.1
CONCURRENCY = 5
SIMILAR_LIMIT = 250


def load_names() -> dict[str, str]:
    names: dict[str, str] = {}
    with METADATA.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                names[entry["id"]] = entry["name"]
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
    return names


def reload_sample() -> list[dict]:
    """Re-read the previous run's records by offset, keeping match weights."""
    prev = json.loads(PREV.read_text())["churn"]
    out = []
    with GRAPH.open("rb") as f:
        for row in prev:
            if "offset" not in row:
                continue
            f.seek(row["offset"])
            line = f.readline()
            if not line.startswith(b'{"id": "'):
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec["id"] != row["id"]:
                continue
            out.append(
                {
                    "band": row["band"],
                    "id": rec["id"],
                    "stored": {c[0]: float(c[1]) for c in rec["connections"]},
                }
            )
    return out


async def fetch_similar(session, artist_id: str, name: str | None):
    if is_real_mbid(artist_id):
        got = await api_client.get_similar_artists(session, artist_id, SIMILAR_LIMIT)
        if got:
            return got
    if not name:
        return []
    return await api_client.get_similar_artists_by_name(session, name, SIMILAR_LIMIT)


def similar_map(similar: list[dict]) -> dict[str, tuple[str, float]]:
    import uuid

    out: dict[str, tuple[str, float]] = {}
    for s in similar:
        try:
            match = float(s.get("match", 0) or 0)
        except (TypeError, ValueError):
            match = 0.0
        if s.get("mbid"):
            out[s["mbid"]] = (s.get("name", ""), match)
        elif s.get("url"):
            out[str(uuid.uuid5(uuid.NAMESPACE_URL, s["url"]))] = (s.get("name", ""), match)
    return out


async def probe(session, names: dict[str, str], sample: list[dict], thr: float) -> list[dict]:
    sem = asyncio.Semaphore(CONCURRENCY)
    results: list[dict] = []

    async def one(rec: dict) -> None:
        async with sem:
            t0 = time.monotonic()
            try:
                similar = await fetch_similar(session, rec["id"], names.get(rec["id"]))
            except Exception as e:
                results.append({"band": rec["band"], "id": rec["id"], "error": type(e).__name__})
                return
            elapsed = time.monotonic() - t0

        fresh = similar_map(similar)
        stored = rec["stored"]
        s_all, f_all = set(stored), set(fresh)
        s_hi = {k for k, w in stored.items() if w > thr}
        f_hi = {k for k, (_, w) in fresh.items() if w > thr}

        results.append(
            {
                "band": rec["band"],
                "id": rec["id"],
                "stored_n": len(s_all),
                "fresh_n": len(f_all),
                "added": len(f_all - s_all),
                "removed": len(s_all - f_all),
                "added_unknown": sum(1 for a in f_all - s_all if a not in names),
                "stored_hi": len(s_hi),
                "fresh_hi": len(f_hi),
                "added_hi": len(f_hi - s_hi),
                "removed_hi": len(s_hi - f_hi),
                "added_unknown_hi": sum(1 for a in f_hi - s_hi if a not in names),
                "matches": sorted((w for _, w in fresh.values()), reverse=True)[:5],
                "seconds": round(elapsed, 3),
            }
        )

    await asyncio.gather(*(one(r) for r in sample))
    return results


async def main() -> None:
    thr = float(sys.argv[1]) if len(sys.argv) > 1 else THRESHOLD
    if key := os.getenv("LASTFM_API_KEY"):
        api_client.API_KEY = key

    print("Loading names...")
    names = load_names()
    print(f"  {len(names):,} known")
    sample = reload_sample()
    print(f"Reusing {len(sample)} artists from the previous run (threshold {thr})")

    async with aiohttp.ClientSession() as session:
        rows = await probe(session, names, sample, thr)

    OUT.write_text(json.dumps({"threshold": thr, "rows": rows}, indent=2))

    ok = [r for r in rows if "error" not in r]
    print("\nALL EDGES")
    print("band   n  stored  fresh   added  removed  churn%  new_unk")
    for b in sorted({r["band"] for r in ok}):
        g = [r for r in ok if r["band"] == b]
        n = len(g)
        ch = sum((r["added"] + r["removed"]) / (2 * max(r["stored_n"], 1)) for r in g) / n
        print(
            f"{b:4d} {n:4d} {sum(r['stored_n'] for r in g)/n:7.1f}"
            f" {sum(r['fresh_n'] for r in g)/n:6.1f} {sum(r['added'] for r in g)/n:7.2f}"
            f" {sum(r['removed'] for r in g)/n:8.2f} {100*ch:6.1f}"
            f" {sum(r['added_unknown'] for r in g)/n:8.3f}"
        )

    print(f"\nMATCH > {thr}")
    print("band   n  stored  fresh   added  removed  churn%  new_unk  kept%")
    for b in sorted({r["band"] for r in ok}):
        g = [r for r in ok if r["band"] == b]
        n = len(g)
        ch = sum((r["added_hi"] + r["removed_hi"]) / (2 * max(r["stored_hi"], 1)) for r in g) / n
        kept = sum(r["stored_hi"] / max(r["stored_n"], 1) for r in g) / n
        print(
            f"{b:4d} {n:4d} {sum(r['stored_hi'] for r in g)/n:7.1f}"
            f" {sum(r['fresh_hi'] for r in g)/n:6.1f} {sum(r['added_hi'] for r in g)/n:7.2f}"
            f" {sum(r['removed_hi'] for r in g)/n:8.2f} {100*ch:6.1f}"
            f" {sum(r['added_unknown_hi'] for r in g)/n:8.3f} {100*kept:6.1f}"
        )

    tops = [m for r in ok for m in r["matches"][:1]]
    if tops:
        tops.sort()
        print(f"\ntop-match per artist: min {tops[0]:.3f} median {tops[len(tops)//2]:.3f} max {tops[-1]:.3f}")
    errs = [r for r in rows if "error" in r]
    if errs:
        print(f"{len(errs)} errored")


if __name__ == "__main__":
    asyncio.run(main())
