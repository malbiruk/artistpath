"""Main entry point for streaming artist graph collection."""

import asyncio

from collector import StreamingCollector
from data_storage import export_to_json


async def main():
    """Main function for memory-efficient graph collection."""

    # Configuration
    config = {
        "starting_artist": "Taylor Swift",
        "max_artists": None,
        "include_tags": False,
        "similar_per_artist": 250,
        "tags_per_artist": 50,
        "batch_size": 10,
        "resume": True,
    }

    # Create streaming collector
    collector = StreamingCollector(output_dir="../data")

    print("🚀 Starting memory-efficient artist graph collection...")
    print("📁 Output directory: ../data")
    print(
        f"🎯 Target: {'Unlimited' if config['max_artists'] is None else config['max_artists']} artists"
    )
    print(f"📦 Batch size: {config['batch_size']}")
    print(f"🏷️  Include tags: {config['include_tags']}")
    print(f"🔄 Resume: {config['resume']}")

    # Collect data
    result = await collector.collect_graph(**config)

    if "error" not in result:
        print("\n✅ Collection finished successfully!")

        # Export to regular JSON if needed (warning: this loads data back into RAM)
        if result["processed_artists"] < 100000:  # Only export if reasonably small
            export_to_json("../data")
            print("📤 Exported to regular JSON files")
        else:
            print("⚠️  Dataset too large for JSON export - use NDJSON files directly")

        # Show file sizes
        show_file_sizes()
    else:
        print(f"❌ Collection failed: {result['error']}")


def show_file_sizes():
    """Show sizes of generated files."""
    from pathlib import Path

    data_dir = Path("../data")
    files_to_check = [
        "graph.ndjson",
        "metadata.ndjson",
        "collection_state.json",
        "seen_metadata.txt",
    ]

    print("\n📂 Generated files:")
    total_size = 0

    for filename in files_to_check:
        filepath = data_dir / filename
        if filepath.exists():
            size_mb = filepath.stat().st_size / 1024 / 1024
            total_size += size_mb
            print(f"   {filename}: {size_mb:.1f} MB")
        else:
            print(f"   {filename}: Not found")

    print(f"   Total: {total_size:.1f} MB")


if __name__ == "__main__":
    asyncio.run(main())
