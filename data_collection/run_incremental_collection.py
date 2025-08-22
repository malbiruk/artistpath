"""Incremental collection to fill gaps in artist graph."""

import asyncio
import json
from pathlib import Path

from collector import StreamingCollector


async def load_existing_artists(data_dir: Path) -> set:
    """Load artist IDs from metadata.ndjson."""
    existing = set()
    metadata_path = data_dir / "metadata.ndjson"

    if metadata_path.exists():
        print(f"Loading existing artists from {metadata_path}...")
        with open(metadata_path) as f:
            for i, line in enumerate(f):
                if i % 100000 == 0:
                    print(f"  Loaded {i:,} artists...", end="\r")
                artist = json.loads(line)
                existing.add(artist["id"])
        print(f"  Loaded {len(existing):,} existing artists")
    else:
        print("No existing metadata found, starting fresh")

    return existing


async def run_seed_collection(
    seed_artist: str,
    collector: StreamingCollector,
    existing_artists: set,
    max_new: int | None = None,
) -> int:
    """Run collection from a single seed artist."""
    print(f"\n🎯 Starting collection from: {seed_artist}")

    # Monkey-patch the collector to check existing artists
    # This prevents re-queuing artists we already have
    original_collect = collector.collect_graph

    async def filtered_collect(**kwargs):
        # Store reference to existing artists in collector
        collector._existing_artists = existing_artists
        return await original_collect(**kwargs)

    collector.collect_graph = filtered_collect

    config = {
        "starting_artist": seed_artist,
        "max_artists": max_new,  # None = unlimited until hitting existing
        "similar_per_artist": 250,
        "batch_size": 10,
        "resume": True,  # Append to existing data
    }

    try:
        result = await collector.collect_graph(**config)
        new_artists = result.get("new_artists", 0)
        print(f"✅ Added {new_artists:,} new artists from {seed_artist}")
        return new_artists
    except Exception as e:
        print(f"❌ Error with {seed_artist}: {e}")
        return 0


async def main() -> None:
    """Run incremental collection from multiple seed artists."""

    data_dir = Path("../data")

    # Load existing artists to avoid re-processing
    existing_artists = await load_existing_artists(data_dir)

    # Seeds for different scenes/clusters
    seed_groups = {
        "Russian Scene": [
            "пошлая молли",
            "дайте танк (!)",
            "пасош",
            "Пасош",
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
            "Caetano Veloso",  # Brazilian
            "Fairuz",  # Arabic
            "A.R. Rahman",  # Indian
            "Sigur Rós",  # Icelandic
            "Buena Vista Social Club",  # Cuban
            "Fela Kuti",  # Nigerian
            "Tinariwen",  # Malian
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

    collector = StreamingCollector(output_dir=str(data_dir))
    total_new = 0

    for group_name, seeds in seed_groups.items():
        print(f"\n{'=' * 60}")
        print(f"Processing {group_name}")
        print(f"{'=' * 60}")

        for artist in seeds:
            new_count = await run_seed_collection(
                artist,
                collector,
                existing_artists,
                max_new=None,  # Let it expand naturally
            )
            total_new += new_count

            # Update existing artists set with newly collected
            # This prevents the next seed from re-exploring the same area
            existing_artists = await load_existing_artists(data_dir)

            # Small delay between seeds to be nice to the API
            if new_count > 0:
                await asyncio.sleep(5)

    print(f"\n{'=' * 60}")
    print(f"🎉 Total new artists added: {total_new:,}")
    print(f"📊 Total artists now: {len(existing_artists):,}")
    print("\n💾 Remember to run run_postprocessing.py after this!")
    print(f"   cd {data_dir.parent}/data_collection")
    print("   uv run python run_postprocessing.py")


if __name__ == "__main__":
    print("🚀 Starting incremental artist collection...")
    print("📊 This will append to your existing dataset")
    print("⏱️  Each seed will expand until hitting already-collected artists")
    asyncio.run(main())
