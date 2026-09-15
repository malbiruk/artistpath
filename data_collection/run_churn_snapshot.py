"""Snapshot stored-vs-fresh similar lists once, then slice them offline.

Every new question about churn (match threshold, top-K rank, in-degree tier)
otherwise costs another full pass over the API. This fetches the same sampled
artists once, writes both lists with weights intact, and does all the cutting
locally. Re-analyse with --analyze-only; no network.

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
SNAP = DATA_DIR / "validation" / "churn_snapshot.json"

CONCURRENCY = 5
SIMILAR_LIMIT = 250
THRESHOLDS = [0.0, 0.05, 0.1, 0.2, 0.5]
TOPKS = [10, 20, 50, 100]


def load_names() -> dict[str, str]:
    names: dict[str, str] = {}
    with METADATA.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                e = json.loads(line)
                names[e["id"]] = e["name"]
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
    return names


def reload_sample() -> list[dict]:
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
            out.append({"band": row["band"], "id": rec["id"],
                        "stored": [[c[0], float(c[1])] for c in rec["connections"]]})
    return out


async def fetch_similar(session, artist_id, name):
    if is_real_mbid(artist_id):
        got = await api_client.get_similar_artists(session, artist_id, SIMILAR_LIMIT)
        if got:
            return got
    if not name:
        return []
    return await api_client.get_similar_artists_by_name(session, name, SIMILAR_LIMIT)


def fresh_pairs(similar):
    import uuid

    out = []
    for s in similar:
        try:
            m = float(s.get("match", 0) or 0)
        except (TypeError, ValueError):
            m = 0.0
        if s.get("mbid"):
            out.append([s["mbid"], m])
        elif s.get("url"):
            out.append([str(uuid.uuid5(uuid.NAMESPACE_URL, s["url"])), m])
    return out


async def snapshot(names, sample):
    sem = asyncio.Semaphore(CONCURRENCY)
    rows = []

    async def one(rec):
        async with sem:
            t0 = time.monotonic()
            try:
                similar = await fetch_similar(session, rec["id"], names.get(rec["id"]))
            except Exception as e:
                rows.append({"band": rec["band"], "id": rec["id"], "error": type(e).__name__})
                return
            el = time.monotonic() - t0
        rows.append({"band": rec["band"], "id": rec["id"], "stored": rec["stored"],
                     "fresh": fresh_pairs(similar), "seconds": round(el, 3)})

    async with aiohttp.ClientSession() as session:
        await asyncio.gather(*(one(r) for r in sample))
    return rows


def ranked(pairs):
    return [p[0] for p in sorted(pairs, key=lambda p: -p[1])]


def analyze(rows, names):
    """Jaccard distance, skipping artists the cut leaves empty; top-K only over
    artists that actually hold K edges on both sides."""
    ok = [r for r in rows if "error" not in r and r.get("stored")]
    bands = sorted({r["band"] for r in ok})

    for thr in THRESHOLDS:
        print(f"\n--- match > {thr} (jaccard) ---")
        print("band  used  stored  fresh  churn%  new_unk  kept%")
        for b in bands:
            g = [r for r in ok if r["band"] == b]
            used = 0
            tot = [0.0] * 4
            for r in g:
                st = {i for i, w in r["stored"] if w > thr}
                fr = {i for i, w in r["fresh"] if w > thr}
                if not (st | fr):
                    continue
                used += 1
                tot[0] += len(st)
                tot[1] += len(fr)
                tot[2] += 1 - len(st & fr) / len(st | fr)
                tot[3] += sum(1 for a in fr - st if a not in names)
            if not used:
                continue
            kept = sum(
                len([1 for i, w in r["stored"] if w > thr]) / max(len(r["stored"]), 1)
                for r in g
            ) / len(g)
            print(f"{b:4d} {used:5d} {tot[0]/used:7.1f} {tot[1]/used:6.1f}"
                  f" {100*tot[2]/used:6.1f} {tot[3]/used:8.3f} {100*kept:6.1f}")

    for k in TOPKS:
        print(f"\n--- top {k} by rank (artists holding >= {k} on both sides) ---")
        print("band  used  overlap%  changed  new_unk")
        for b in bands:
            g = [r for r in ok if r["band"] == b]
            used = 0
            ov = nu = 0.0
            for r in g:
                sr, fr_ = ranked(r["stored"]), ranked(r["fresh"])
                if len(sr) < k or len(fr_) < k:
                    continue
                used += 1
                st, fr = set(sr[:k]), set(fr_[:k])
                ov += len(st & fr) / k
                nu += sum(1 for a in fr - st if a not in names)
            if not used:
                print(f"{b:4d} {0:5d}        --")
                continue
            print(f"{b:4d} {used:5d} {100*ov/used:8.1f} {k*(1-ov/used):8.2f} {nu/used:8.3f}")


async def main():
    names = None
    if "--analyze-only" not in sys.argv:
        if key := os.getenv("LASTFM_API_KEY"):
            api_client.API_KEY = key
        print("Loading names...")
        names = load_names()
        sample = reload_sample()
        print(f"Snapshotting {len(sample)} artists...")
        rows = await snapshot(names, sample)
        SNAP.write_text(json.dumps(rows))
        print(f"Wrote {SNAP}")
    else:
        rows = json.loads(SNAP.read_text())
        print("Loading names...")
        names = load_names()

    errs = [r for r in rows if "error" in r]
    print(f"{len(rows)} rows, {len(errs)} errored")
    analyze(rows, names)


if __name__ == "__main__":
    asyncio.run(main())
