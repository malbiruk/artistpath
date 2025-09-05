"""Memory-efficient streaming processor for artist graph collection."""

import asyncio
import json
from collections import deque
from pathlib import Path

import aiohttp

from api_client import (
    get_artist_info_by_name,
    get_similar_artists,
    get_similar_artists_by_name,
    is_real_mbid,
    print_api_error_summary,
)
from data_storage import append_to_graph, append_to_metadata, save_state


class StreamingCollector:
    """Memory-efficient collector that streams data to disk."""

    def __init__(self, output_dir: str = "../data") -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Only keep essential data in RAM
        self.processed_mbids: set[str] = set()
        self.seen_metadata_ids: set[str] = set()  # Track metadata to avoid duplicates
        self.queue: deque = deque()

    def load_state(self) -> bool:
        """Load existing state from files. Returns True if resuming."""
        state_path = self.output_dir / "collection_state.json"
        metadata_ids_path = self.output_dir / "seen_metadata.txt"

        if not state_path.exists():
            return False

        with Path(state_path).open() as f:
            state = json.load(f)
            self.processed_mbids = set(state.get("processed_mbids", []))
            self.queue = deque(state.get("queue", []))

        # Load seen metadata IDs
        if metadata_ids_path.exists():
            with metadata_ids_path.open() as f:
                self.seen_metadata_ids = {line.strip() for line in f if line.strip()}

        print(f"Resuming with {len(self.processed_mbids)} processed artists")
        print(f"Queue has {len(self.queue)} pending artists")
        print(f"Tracking {len(self.seen_metadata_ids)} metadata entries")
        return True

    def save_state(self) -> None:
        """Save current state to files."""
        save_state(self.processed_mbids, self.queue, str(self.output_dir))

        # Save seen metadata IDs
        metadata_ids_path = self.output_dir / "seen_metadata.txt"
        with Path(metadata_ids_path).open("w") as f:
            for metadata_id in self.seen_metadata_ids:
                f.write(f"{metadata_id}\n")

    def add_metadata_if_new(self, node_id: str, name: str, url: str) -> bool:
        """Add metadata if not seen before. Returns True if new."""
        if node_id not in self.seen_metadata_ids:
            self.seen_metadata_ids.add(node_id)
            append_to_metadata(node_id, name, url, str(self.output_dir))
            return True
        return False

    async def initialize_starting_artist(
        self,
        session: aiohttp.ClientSession,
        starting_artist: str,
    ) -> bool:
        """Initialize with starting artist."""
        print(f"Starting with artist: {starting_artist}")
        info = await get_artist_info_by_name(session, starting_artist)

        if not info:
            print(f"Could not find artist info for {starting_artist}")
            return False

        # Use MBID if available, otherwise generate UUID5 from Last.fm URL
        if info.get("mbid"):
            artist_id = info["mbid"]
            print(f"  Using MBID: {artist_id}")
        elif info.get("url"):
            import uuid

            # Generate deterministic UUID from Last.fm URL for artists without MBID
            artist_id = str(uuid.uuid5(uuid.NAMESPACE_URL, info["url"]))
            print(f"  Generated UUID5 from URL: {artist_id}")
        else:
            print(f"Could not get MBID or URL for {starting_artist}")
            return False

        name = info.get("name", starting_artist)
        url = info.get("url", "")

        self.add_metadata_if_new(artist_id, name, url)
        self.queue.append(artist_id)
        return True

    def get_artist_name_from_metadata(self, artist_id: str) -> str | None:
        """Get artist name from metadata files for UUID5 artists."""
        metadata_path = self.output_dir / "metadata.ndjson"
        if not metadata_path.exists():
            return None

        # For efficiency, we could cache this, but for now just search
        try:
            with metadata_path.open() as f:
                for line in f:
                    if not line.strip():
                        continue
                    entry = json.loads(line)
                    if entry.get("id") == artist_id:
                        return entry.get("name")
        except Exception:  # noqa: S110
            pass
        return None

    async def process_single_artist(  # noqa: C901, PLR0912
        self,
        session: aiohttp.ClientSession,
        artist_id: str,
        similar_per_artist: int | None,
    ) -> int:
        """Process a single artist and return number of new artists found."""
        if artist_id in self.processed_mbids:
            return 0

        self.processed_mbids.add(artist_id)

        # Get similar artists using hybrid approach
        similar_artists = []

        if is_real_mbid(artist_id):
            # Try MBID first for real MBIDs
            similar_artists = await get_similar_artists(session, artist_id, similar_per_artist)
            if not similar_artists:
                # MBID failed, try to get name and fall back
                artist_name = self.get_artist_name_from_metadata(artist_id)
                if artist_name:
                    similar_artists = await get_similar_artists_by_name(
                        session,
                        artist_name,
                        similar_per_artist,
                    )
        else:
            # UUID5 artist, get name and search by name
            artist_name = self.get_artist_name_from_metadata(artist_id)
            if artist_name:
                similar_artists = await get_similar_artists_by_name(
                    session,
                    artist_name,
                    similar_per_artist,
                )
            else:
                print(f"  ❌ Could not find name for UUID5 artist: {artist_id}")
                return 0

        # Process similar artists
        connections = []
        new_artists = 0

        for similar in similar_artists:
            # Use MBID if available, otherwise generate UUID5 from Last.fm URL
            if similar.get("mbid"):
                similar_id = similar["mbid"]
            elif similar.get("url"):
                import uuid

                similar_id = str(uuid.uuid5(uuid.NAMESPACE_URL, similar["url"]))
            else:
                continue  # Skip artists without MBID or URL

            match_score = float(similar.get("match", 0))
            connections.append((similar_id, match_score))

            # Add to metadata if new
            if self.add_metadata_if_new(
                similar_id,
                similar.get("name", ""),
                similar.get("url", ""),
            ):
                new_artists += 1
                # Add to queue if not processed
                if similar_id not in self.processed_mbids:
                    self.queue.append(similar_id)

        # Stream artist connections to disk
        if connections:
            append_to_graph(artist_id, connections, str(self.output_dir))

        return new_artists

    async def collect_graph(
        self,
        starting_artist: str | None = None,
        max_artists: int | None = None,
        similar_per_artist: int | None = 80,
        batch_size: int = 10,
        *,
        resume: bool = True,
    ) -> dict:
        """Collect artist graph with streaming approach."""

        # Load existing state or initialize
        resumed = self.load_state() if resume else False

        async with aiohttp.ClientSession() as session:
            # Initialize starting artist if needed
            if (
                not resumed
                and not self.queue
                and starting_artist
                and not await self.initialize_starting_artist(session, starting_artist)
            ):
                return {"error": "Could not initialize starting artist"}

            total_processed = len(self.processed_mbids)
            batch_count = 0

            while self.queue and (max_artists is None or total_processed < max_artists):
                # Process batch
                batch_size_actual = min(batch_size, len(self.queue))

                if max_artists is not None:
                    batch_size_actual = min(batch_size_actual, max_artists - total_processed)

                batch_artists = [
                    self.queue.popleft() for _ in range(batch_size_actual) if self.queue
                ]

                if not batch_artists:
                    break

                # Process artists concurrently
                tasks = []
                for mbid in batch_artists:
                    task = self.process_single_artist(
                        session,
                        mbid,
                        similar_per_artist,
                    )
                    tasks.append(task)

                new_artist_counts = await asyncio.gather(*tasks)
                total_new_artists = sum(new_artist_counts)
                total_processed += len(batch_artists)
                batch_count += 1

                # Progress reporting
                max_display = "unlimited" if max_artists is None else str(max_artists)
                print(
                    f"Batch {batch_count}: Processed {len(batch_artists)} artists "
                    f"({total_processed}/{max_display} total)",
                )
                print(f"  New artists found: {total_new_artists}")
                print(f"  Queue size: {len(self.queue)}")
                print(
                    f"  Memory usage: {len(self.processed_mbids)} processed IDs, "
                    f"{len(self.seen_metadata_ids)} metadata entries",
                )

                # Periodic state save
                if batch_count % 10 == 0:
                    self.save_state()
                    print(f"  Saved state at batch {batch_count}")

                # Small delay to avoid overwhelming API
                await asyncio.sleep(0.1)

                if total_new_artists == 0:
                    print("⚠️  No new artists found - might have reached component limit")

        # Final save
        self.save_state()

        # Summary
        print("\n🎉 Collection complete!")
        print(f"📊 Processed {len(self.processed_mbids)} artists")
        print(f"📝 Collected {len(self.seen_metadata_ids)} metadata entries")
        print(f"⏭️  Queue remaining: {len(self.queue)}")
        print_api_error_summary()

        return {
            "processed_artists": len(self.processed_mbids),
            "metadata_entries": len(self.seen_metadata_ids),
            "queue_remaining": len(self.queue),
            "completed": len(self.queue) == 0,
        }
