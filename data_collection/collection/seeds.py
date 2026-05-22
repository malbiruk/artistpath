"""Seed artist management for expanding collection to new graph components."""

import json
from pathlib import Path

import aiohttp

from .api_client import get_artist_info_by_name
from .storage import append_to_metadata

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
        state = {"processed_mbids": list(processed_mbids), "queue": queue}
        with state_path.open("w") as f:
            json.dump(state, f, indent=2)
        print(f"\n🎉 Added {added_count} new seeds to queue")
        print(f"📊 Queue now has {len(queue)} artists waiting")
    else:
        print("\n😐 No new seeds added")

    return added_count
