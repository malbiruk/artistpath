"""Seed artist management for expanding collection to new graph components."""

import json
from collections import deque
from pathlib import Path

import aiohttp

from .api_client import get_artist_info_by_name
from .storage import append_to_metadata, save_state

SEED_GROUPS = {
    "Russian Scene": [
        "пошлая молли",
        "дайте танк (!)",
        "пасош",
        "Земфира",
        "Би-2",
        "Ленинград",
        "Мумий Тролль",
        "Noize MC",
        "Oxxxymiron",
        "Face",
        "Скриптонит",
        "Баста",
        "Кровосток",
    ],
    "Underground/Alternative": [
        "Death Grips",
        "100 gecs",
        "Machine Girl",
        "Drain Gang",
        "Black Country, New Road",
        "Black Midi",
        "Squid",
        "Dry Cleaning",
    ],
    "Regional Scenes": [
        "Caetano Veloso",
        "Fairuz",
        "A.R. Rahman",
        "Sigur Rós",
        "Buena Vista Social Club",
        "Fela Kuti",
        "Tinariwen",
    ],
    "Electronic/Experimental": [
        "Arca",
        "FKA twigs",
        "SOPHIE",
        "Oneohtrix Point Never",
        "Tim Hecker",
        "Fennesz",
    ],
    "Metal Subgenres": [
        "Sunn O)))",
        "Electric Wizard",
        "Meshuggah",
        "Gojira",
        "Alcest",
        "Deafheaven",
    ],
}


async def add_seeds_to_queue(seeds: list[str], data_dir: str = "../data") -> int:
    """Add seed artists to the collection queue if not already processed."""
    data_path = Path(data_dir)
    state_path = data_path / "collection_state.json"

    if state_path.exists():
        with state_path.open() as f:
            state = json.load(f)
        processed_mbids = set(state.get("processed_mbids", []))
        queue = state.get("queue", [])
    else:
        state = {}
        processed_mbids = set()
        queue = []

    print(f"Current state: {len(processed_mbids)} processed, {len(queue)} in queue")

    added_count = 0
    async with aiohttp.ClientSession() as session:
        for seed in seeds:
            print(f"🎯 Checking: {seed}")

            info = await get_artist_info_by_name(session, seed)
            if not info:
                print(f"  ❌ Could not find artist info for {seed}")
                continue

            if info.get("mbid"):
                artist_id = info["mbid"]
                print(f"  🎵 Using MBID: {artist_id}")
            elif info.get("url"):
                import uuid

                artist_id = str(uuid.uuid5(uuid.NAMESPACE_URL, info["url"]))
                print(f"  🔗 Generated UUID5 from URL: {artist_id}")
            else:
                print(f"  ❌ No MBID or URL for {seed}")
                continue

            if artist_id in processed_mbids:
                print(f"  ⏭️  Already processed: {info.get('name', seed)}")
                continue

            if artist_id in queue:
                print(f"  📝 Already in queue: {info.get('name', seed)}")
                continue

            queue.append(artist_id)
            append_to_metadata(artist_id, info.get("name", seed), info.get("url", ""), data_dir)
            added_count += 1
            print(f"  ✅ Added to queue: {info.get('name', seed)}")

    if added_count > 0:
        # save_state keeps the sweep's fields and writes atomically; rebuilding
        # the dict here zeroes crawled_total, which drives check_and_refresh.sh's
        # delta negative and silently stops rebuilds until the count catches up.
        save_state(
            processed_mbids,
            deque(queue),
            data_dir,
            refresh_queue=deque(state.get("refresh_queue", [])),
            refresh_offset=state.get("refresh_offset", 0),
            crawled_total=state.get("crawled_total", 0),
        )
        print(f"\n🎉 Added {added_count} new seeds to queue")
        print(f"📊 Queue now has {len(queue)} artists waiting")
    else:
        print("\n😐 No new seeds added")

    return added_count
