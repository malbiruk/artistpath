"""For each dedup pair, fetch Last.fm getInfo for BOTH the variant and its
canonical (mbid + bio + tags + listeners) so an agent can judge same-vs-different
artist. Reads results/dedup_sample.csv, writes results/dedup_label_input.json."""
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
    raise SystemExit("LASTFM_COLLECTOR_API_KEY not found")


KEY = load_key()


def strip_html(s: str) -> str:
    s = re.sub(r"<a\b[^>]*>.*?</a>", "", s, flags=re.S)
    s = re.sub(r"<[^>]+>", "", s)
    return " ".join(s.split())


def getinfo(name: str) -> dict:
    params = {"method": "artist.getinfo", "artist": name, "api_key": KEY,
              "format": "json", "autocorrect": "0"}
    url = BASE + "?" + urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=12) as r:
                data = json.load(r)
            if "error" in data:
                return {"found": False}
            a = data.get("artist", {})
            tags = a.get("tags", {}).get("tag", [])
            if isinstance(tags, dict):
                tags = [tags]
            return {
                "found": True,
                "mbid": a.get("mbid", ""),
                "listeners": int(a.get("stats", {}).get("listeners", 0) or 0),
                "tags": [t.get("name") for t in tags][:6],
                "bio": strip_html(a.get("bio", {}).get("summary", "") or "")[:400],
            }
        except Exception:
            time.sleep(1.0 * (attempt + 1))
    return {"found": False}


def work(row: dict) -> dict:
    v = getinfo(row["variant"])
    c = getinfo(row["canonical"])
    time.sleep(0.05)
    return {
        "kind": row["kind"],
        "variant": row["variant"], "canonical": row["canonical"],
        "variant_in": row["variant_in"], "canonical_in": row["canonical_in"],
        "variant_lfm": v, "canonical_lfm": c,
    }


def main() -> None:
    rows = list(csv.DictReader((Path("results") / "dedup_sample.csv").open()))
    with ThreadPoolExecutor(max_workers=4) as ex:
        out = list(ex.map(work, rows))
    Path("results/dedup_label_input.json").write_bytes(
        json.dumps(out, ensure_ascii=False, indent=2).encode()
    )
    both = sum(1 for o in out if o["variant_lfm"]["found"] and o["canonical_lfm"]["found"])
    print(f"fetched {len(out)} pairs ({both} with both sides found); wrote dedup_label_input.json")


if __name__ == "__main__":
    main()
