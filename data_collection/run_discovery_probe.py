"""Measure where new artists come from, before committing to a re-crawl policy.

Part A (churn): re-fetch the similar lists of artists we already crawled and
diff against what is stored, so we can price discovery per re-crawl. Artists
are sampled from byte-offset bands of graph.ndjson; the file is append-only and
the crawl was breadth-first, so early bands are the dense hub region and late
bands the sparse tail. Offset therefore conflates crawl age with popularity —
the bands are read as popularity tiers, not as ages.

Part B (coverage): pull Last.fm's chart/tag/geo surfaces and count how many of
those artists we have never seen. Charts have a popularity floor, so this
probes for large unreachable clusters, NOT for new artists.

Read-only: writes a JSON report and never touches collection state. Uses
LASTFM_API_KEY so it does not contend with the collector's key.
"""

import asyncio
import json
import os
import random
import sys
import time
from pathlib import Path

import aiohttp

from collection import api_client
from collection.api_client import is_real_mbid

DATA_DIR = Path("../data")
GRAPH = DATA_DIR / "graph.ndjson"
METADATA = DATA_DIR / "metadata.ndjson"
OUT = DATA_DIR / "validation" / "discovery_probe.json"

BANDS = 5
PER_BAND = 250
CONCURRENCY = 5
SIMILAR_LIMIT = 250

TAGS = [
    "rock", "pop", "electronic", "hip-hop", "jazz", "metal", "folk", "punk",
    "classical", "ambient", "techno", "house", "indie", "experimental", "soul",
    "funk", "reggae", "blues", "country", "disco", "shoegaze", "post-rock",
    "black metal", "death metal", "drum and bass", "dubstep", "trance", "grime",
    "k-pop", "j-pop", "city pop", "afrobeat", "bossa nova", "cumbia", "fado",
    "flamenco", "raï", "qawwali", "gamelan", "highlife", "mpb", "chanson",
    "russian rock", "turkish psych", "vaporwave", "hyperpop", "emo", "ska",
    "gospel", "bluegrass",
]
COUNTRIES = [
    "United States", "United Kingdom", "Germany", "France", "Japan", "Brazil",
    "Russia", "Poland", "Sweden", "Finland", "Norway", "Italy", "Spain",
    "Mexico", "Argentina", "Chile", "Colombia", "Canada", "Australia",
    "Netherlands", "Belgium", "Portugal", "Turkey", "Greece", "Ukraine",
    "Czech Republic", "Hungary", "Romania", "Bulgaria", "Serbia", "India",
    "Indonesia", "Philippines", "Thailand", "Vietnam", "South Korea", "China",
    "Nigeria", "South Africa", "Egypt", "Israel", "Iran", "Morocco", "Peru",
]


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


def sample_records(rng: random.Random) -> list[dict]:
    """Seek to random offsets in each band and take the next whole record."""
    size = GRAPH.stat().st_size
    band = size // BANDS
    out = []
    with GRAPH.open("rb") as f:
        for b in range(BANDS):
            seen: set[int] = set()
            for _ in range(PER_BAND * 3):
                if len([r for r in out if r["band"] == b]) >= PER_BAND:
                    break
                pos = rng.randrange(b * band, min((b + 1) * band, size - 1))
                f.seek(pos)
                f.readline()  # discard the partial line
                start = f.tell()
                if start in seen:
                    continue
                seen.add(start)
                line = f.readline()
                if not line.startswith(b'{"id": "'):
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                out.append(
                    {
                        "band": b,
                        "offset": start,
                        "id": rec["id"],
                        "stored": {c[0] for c in rec["connections"]},
                    }
                )
    return out


async def fetch_similar(session, artist_id: str, name: str | None):
    """Mirror collector.fetch_similar_artists: mbid first, then name."""
    if is_real_mbid(artist_id):
        got = await api_client.get_similar_artists(session, artist_id, SIMILAR_LIMIT)
        if got:
            return got
    if not name:
        return []
    return await api_client.get_similar_artists_by_name(session, name, SIMILAR_LIMIT)


def similar_map(similar: list[dict]) -> dict[str, str]:
    """id -> name, so an "unknown" id can be re-checked by name (mbids drift)."""
    import uuid

    out: dict[str, str] = {}
    for s in similar:
        if s.get("mbid"):
            out[s["mbid"]] = s.get("name", "")
        elif s.get("url"):
            out[str(uuid.uuid5(uuid.NAMESPACE_URL, s["url"]))] = s.get("name", "")
    return out


async def probe_churn(session, names: dict[str, str], records: list[dict]) -> list[dict]:
    sem = asyncio.Semaphore(CONCURRENCY)
    results: list[dict] = []

    async def one(rec: dict) -> None:
        async with sem:
            t0 = time.monotonic()
            try:
                similar = await fetch_similar(session, rec["id"], names.get(rec["id"]))
            except Exception as e:  # RetryError and friends: record, do not abort
                results.append({**{k: rec[k] for k in ("band", "offset", "id")},
                                "error": type(e).__name__})
                return
            elapsed = time.monotonic() - t0
            fresh_map = similar_map(similar)
            fresh = set(fresh_map)
            stored = rec["stored"]
            added = fresh - stored
            results.append(
                {
                    "band": rec["band"],
                    "offset": rec["offset"],
                    "id": rec["id"],
                    "stored_n": len(stored),
                    "fresh_n": len(fresh),
                    "added": len(added),
                    "removed": len(stored - fresh),
                    "added_unknown": sum(1 for a in added if a not in names),
                    "added_unknown_names": [
                        fresh_map[a] for a in added if a not in names
                    ],
                    "seconds": round(elapsed, 3),
                }
            )

    await asyncio.gather(*(one(r) for r in records))
    return results


async def probe_coverage(session, names: dict[str, str]) -> dict:
    sem = asyncio.Semaphore(CONCURRENCY)

    async def top(params: dict, label: str) -> dict | None:
        async with sem:
            try:
                data = await api_client.fetch_json(session, {**params, "limit": 200})
            except Exception as e:
                return {"source": label, "error": type(e).__name__}
        if not data:
            return {"source": label, "error": "empty"}
        block = data.get("topartists") or data.get("artists") or {}
        artists = block.get("artist", [])
        if isinstance(artists, dict):
            artists = [artists]
        import uuid as _uuid

        unknown = []
        for a in artists:
            if a.get("mbid"):
                aid = a["mbid"]
            elif a.get("url"):
                aid = str(_uuid.uuid5(_uuid.NAMESPACE_URL, a["url"]))
            else:
                continue
            if aid not in names:
                unknown.append(a.get("name", ""))
        return {
            "source": label,
            "returned": len(artists),
            "unknown": len(unknown),
            "unknown_names": unknown[:15],
        }

    jobs = [top({"method": "chart.getTopArtists"}, "chart:global")]
    jobs += [top({"method": "tag.getTopArtists", "tag": t}, f"tag:{t}") for t in TAGS]
    jobs += [top({"method": "geo.getTopArtists", "country": c}, f"geo:{c}") for c in COUNTRIES]
    rows = [r for r in await asyncio.gather(*jobs) if r]
    ok = [r for r in rows if "returned" in r]
    return {
        "sources": rows,
        "total_returned": sum(r["returned"] for r in ok),
        "total_unknown": sum(r["unknown"] for r in ok),
    }


async def main() -> None:
    key = os.getenv("LASTFM_API_KEY")
    if key:
        api_client.API_KEY = key  # keep the collector's key uncontended

    rng = random.Random(20260914)
    print("Loading names from metadata.ndjson...")
    names = load_names()
    print(f"  {len(names):,} known artists")

    print(f"Sampling {BANDS} x {PER_BAND} records from graph.ndjson...")
    records = sample_records(rng)
    print(f"  {len(records)} sampled")

    async with aiohttp.ClientSession() as session:
        print("Part A: re-fetching similar lists...")
        churn = await probe_churn(session, names, records)
        if "--churn-only" in sys.argv:
            coverage = {"skipped": True, "sources": [], "total_returned": 0, "total_unknown": 0}
        else:
            print("Part B: chart / tag / geo coverage...")
            coverage = await probe_coverage(session, names)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"churn": churn, "coverage": coverage}, indent=2))
    print(f"\nWrote {OUT}")

    print("\nband  n   stored  fresh  added  removed  new_unknown  sec/req")
    for b in range(BANDS):
        rows = [r for r in churn if r["band"] == b and "error" not in r]
        if not rows:
            continue
        n = len(rows)
        print(
            f"{b:4d} {n:4d} {sum(r['stored_n'] for r in rows)/n:7.1f}"
            f" {sum(r['fresh_n'] for r in rows)/n:6.1f}"
            f" {sum(r['added'] for r in rows)/n:6.2f}"
            f" {sum(r['removed'] for r in rows)/n:8.2f}"
            f" {sum(r['added_unknown'] for r in rows)/n:12.3f}"
            f" {sum(r['seconds'] for r in rows)/n:8.3f}"
        )
    known_names = set(names.values())
    unk_names = [n for r in churn for n in r.get("added_unknown_names", []) if n]
    if unk_names:
        drift = sum(1 for n in unk_names if n in known_names)
        print(
            f"\nadded_unknown ids: {len(unk_names)} | already known BY NAME "
            f"(mbid drift, not new): {drift} ({100*drift/len(unk_names):.0f}%) "
            f"| genuinely new: {len(unk_names)-drift}"
        )

    errs = [r for r in churn if "error" in r]
    if errs:
        print(f"\n{len(errs)} errored")
    if not coverage.get("skipped"):
        print(
            f"\ncoverage: {coverage['total_unknown']:,} unknown of "
            f"{coverage['total_returned']:,} chart/tag/geo artists"
        )


if __name__ == "__main__":
    asyncio.run(main())
