"""Convert NDJSON data files to optimized binary format."""

import os
import time
from pathlib import Path

from postprocessing import (
    identify_blocklisted_uuids,
    identify_cleaning_uuids,
    process_graph,
    process_metadata,
)

MB = 1024**2
GB = 1024**3


def main() -> None:
    graph_file = Path("../data/graph.ndjson")
    metadata_file = Path("../data/metadata.ndjson")
    data_dir = Path("../data")

    print("🔄 Starting post-processing...")
    print(f"📏 Graph input: {graph_file.stat().st_size / GB:.1f} GB")
    print(f"📏 Metadata input: {metadata_file.stat().st_size / MB:.1f} MB")

    t0 = time.perf_counter()

    print("\n🚫 Step 0: Identifying blocklisted sentinel UUIDs")
    blocklist = identify_blocklisted_uuids(metadata_file)
    print(f"✅ Sentinels: {len(blocklist):,} UUID(s)")

    # Graph-aware cleaning (duplicates + collab/feature credits) removes ~25% of
    # nodes. On by default; kill-switch is ARTISTPATH_CLEANING=0.
    if os.getenv("ARTISTPATH_CLEANING", "1") != "0":
        print("\n🧹 Step 0b: Identifying duplicate + collab/feature UUIDs")
        dup_uuids, translit_uuids, collab_uuids = identify_cleaning_uuids(
            graph_file, metadata_file, skip=blocklist
        )
        print(
            f"✅ Duplicates: {len(dup_uuids):,}  |  Translit dups: {len(translit_uuids):,}"
            f"  |  Collabs/features: {len(collab_uuids):,}"
        )
        blocklist |= dup_uuids | translit_uuids | collab_uuids
        print(f"✅ Blocklist total: {len(blocklist):,} UUID(s) will be excluded")
    else:
        print("\n⏭️  Step 0b: graph-aware cleaning DISABLED (ARTISTPATH_CLEANING=0)")

    print("\n📊 Step 1: Converting graph to binary format")
    graph_stats = process_graph(graph_file, data_dir, blocklist=blocklist)
    print(f"✅ Forward graph: {graph_stats['graph_bin_size'] / MB:.1f} MB")
    print(f"✅ Reverse graph: {graph_stats['rev_graph_bin_size'] / MB:.1f} MB")

    print("\n📊 Step 2: Creating unified metadata binary")
    metadata_stats = process_metadata(
        metadata_file,
        data_dir,
        graph_stats["forward_index"],
        graph_stats["reverse_index"],
        blocklist=blocklist,
    )
    print(f"✅ Metadata binary: {metadata_stats['binary_size'] / MB:.1f} MB")

    elapsed = time.perf_counter() - t0

    # Summary
    total_binary = (
        graph_stats["graph_bin_size"]
        + graph_stats["rev_graph_bin_size"]
        + metadata_stats["binary_size"]
    )
    original = graph_file.stat().st_size + metadata_file.stat().st_size
    savings = (original - total_binary) / original * 100

    print(f"\n✅ Post-processing complete in {elapsed:.0f}s")
    print(f"🎵 Artists: {graph_stats['artists']:,}")
    print(f"🔗 Forward connections: {graph_stats['forward_connections']:,}")
    print(f"🔄 Reverse connections: {graph_stats['reverse_connections']:,}")
    print(f"📦 Total binary: {total_binary / MB:.1f} MB (saved {savings:.0f}%)")


if __name__ == "__main__":
    main()
