"""Entry point for streaming artist graph collection."""

import asyncio
from pathlib import Path

from collection import StreamingCollector


async def main() -> None:
    config = {
        "starting_artist": "Taylor Swift",
        "max_artists": None,
        "similar_per_artist": 250,
        "batch_size": 10,
        "resume": True,
    }

    collector = StreamingCollector(output_dir="../data")

    print("🚀 Starting artist graph collection...")
    print(f"🎯 Target: {'Unlimited' if config['max_artists'] is None else config['max_artists']}")
    print(f"📦 Batch size: {config['batch_size']}")

    result = await collector.collect_graph(**config)

    if "error" not in result:
        print("\n✅ Collection finished!")
        show_file_sizes()
    else:
        print(f"❌ Collection failed: {result['error']}")


def show_file_sizes() -> None:
    data_dir = Path("../data")
    files = ["graph.ndjson", "metadata.ndjson", "collection_state.json"]

    print("\n📂 File sizes:")
    total = 0
    for name in files:
        path = data_dir / name
        if path.exists():
            size_mb = path.stat().st_size / 1024 / 1024
            total += size_mb
            print(f"   {name}: {size_mb:.1f} MB")
    print(f"   Total: {total:.1f} MB")


if __name__ == "__main__":
    asyncio.run(main())
