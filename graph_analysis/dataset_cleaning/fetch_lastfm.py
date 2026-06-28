"""Enrich the label sample with Last.fm artist.getInfo (bio + tags + listeners)
so an agent can judge 'real act vs credit' the same way a human reading the page
would. Reads results/label_sample.csv, writes results/label_input.json."""
import csv
import json
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = "http://ws.audioscrobbler.com/2.0/"


def load_key() -> str:
    for p in (Path("../../.env"), Path("../.env"), Path(".env")):
        if p.exists():
            for line in p.read_text().splitlines():
                if line.startswith("LASTFM_COLLECTOR_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("LASTFM_COLLECTOR_API_KEY not found in .env")


KEY = load_key()


def strip_html(s: str) -> str:
    s = re.sub(r"<a\b[^>]*>.*?</a>", "", s, flags=re.S)  # drop "Read more on Last.fm" links
    s = re.sub(r"<[^>]+>", "", s)
    return " ".join(s.split())


def getinfo(name: str) -> dict:
    params = {
        "method": "artist.getinfo", "artist": name, "api_key": KEY,
        "format": "json", "autocorrect": "0",
    }
    url = BASE + "?" + urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=12) as r:
                data = json.load(r)
            if "error" in data:
                return {"found": False, "error": data.get("error")}
            a = data.get("artist", {})
            stats = a.get("stats", {})
            tags = a.get("tags", {}).get("tag", [])
            if isinstance(tags, dict):
                tags = [tags]
            return {
                "found": True,
                "lfm_name": a.get("name"),
                "listeners": int(stats.get("listeners", 0) or 0),
                "playcount": int(stats.get("playcount", 0) or 0),
                "tags": [t.get("name") for t in tags][:8],
                "bio": strip_html(a.get("bio", {}).get("summary", "") or "")[:600],
            }
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    return {"found": False, "error": "fetch_failed"}


def work(row: dict) -> dict:
    info = getinfo(row["name"])
    time.sleep(0.1)
    return {
        "norm": row["norm"], "name": row["name"], "r": row["r"], "r_bin": row["r_bin"],
        "components": row["components"], **info,
    }


def main() -> None:
    rows = list(csv.DictReader((Path("results") / "label_sample.csv").open()))
    with ThreadPoolExecutor(max_workers=4) as ex:
        out = list(ex.map(work, rows))
    Path("results/label_input.json").write_bytes(
        json.dumps(out, ensure_ascii=False, indent=2).encode()
    )
    found = sum(1 for o in out if o.get("found"))
    print(f"fetched {found}/{len(out)} found; wrote results/label_input.json")


if __name__ == "__main__":
    main()
