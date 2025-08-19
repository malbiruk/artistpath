"""Memory-efficient streaming processor for artist graph collection."""

import asyncio
from collections import deque
from pathlib import Path
from typing import Optional, Set

import aiohttp
from api_client import (
    get_artist_info_by_name,
    get_artist_tags,
    get_similar_artists,
    print_api_error_summary,
)
from data_storage import append_to_graph, append_to_metadata, save_state


class StreamingCollector:
    """Memory-efficient collector that streams data to disk."""

    def __init__(self, output_dir: str = "../data"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Only keep essential data in RAM
        self.processed_mbids: Set[str] = set()
        self.seen_metadata_ids: Set[str] = set()  # Track metadata to avoid duplicates
        self.queue: deque = deque()

    def load_state(self) -> bool:
        """Load existing state from files. Returns True if resuming."""
        state_path = self.output_dir / "collection_state.json"
        metadata_ids_path = self.output_dir / "seen_metadata.txt"

        if not state_path.exists():
            return False

        # Load processing state
        import json

        with open(state_path, "r") as f:
            state = json.load(f)
            self.processed_mbids = set(state.get("processed_mbids", []))
            self.queue = deque(state.get("queue", []))

        # Load seen metadata IDs
        if metadata_ids_path.exists():
            with open(metadata_ids_path, "r") as f:
                self.seen_metadata_ids = set(line.strip() for line in f if line.strip())

        print(f"Resuming with {len(self.processed_mbids)} processed artists")
        print(f"Queue has {len(self.queue)} pending artists")
        print(f"Tracking {len(self.seen_metadata_ids)} metadata entries")
        return True

    def save_state(self):
        """Save current state to files."""
        save_state(self.processed_mbids, self.queue, str(self.output_dir))

        # Save seen metadata IDs
        metadata_ids_path = self.output_dir / "seen_metadata.txt"
        with open(metadata_ids_path, "w") as f:
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
        self, session: aiohttp.ClientSession, starting_artist: str
    ) -> bool:
        """Initialize with starting artist."""
        print(f"Starting with artist: {starting_artist}")
        info = await get_artist_info_by_name(session, starting_artist)

        if not info or not info.get("mbid"):
            print(f"Could not get mbid for {starting_artist}")
            return False

        initial_mbid = info["mbid"]
        name = info.get("name", starting_artist)
        url = info.get("url", "")

        self.add_metadata_if_new(initial_mbid, name, url)
        self.queue.append(initial_mbid)
        return True

    async def process_single_artist(
        self,
        session: aiohttp.ClientSession,
        mbid: str,
        include_tags: bool,
        similar_per_artist: Optional[int],
        tags_per_artist: Optional[int],
    ) -> int:
        """Process a single artist and return number of new artists found."""
        if mbid in self.processed_mbids:
            return 0

        self.processed_mbids.add(mbid)

        # Fetch data concurrently
        tasks = [get_similar_artists(session, mbid, similar_per_artist)]
        if include_tags:
            tasks.append(get_artist_tags(session, mbid, tags_per_artist))

        results = await asyncio.gather(*tasks)
        similar_artists = results[0]
        artist_tags = results[1] if include_tags else []

        # Process similar artists
        connections = []
        new_artists = 0

        for similar in similar_artists:
            if not similar.get("mbid"):
                continue

            similar_mbid = similar["mbid"]
            match_score = float(similar.get("match", 0))
            connections.append((similar_mbid, match_score))

            # Add to metadata if new
            if self.add_metadata_if_new(
                similar_mbid, similar.get("name", ""), similar.get("url", "")
            ):
                new_artists += 1
                # Add to queue if not processed
                if similar_mbid not in self.processed_mbids:
                    self.queue.append(similar_mbid)

        # Process tags if enabled
        if include_tags:
            for tag in artist_tags:
                tag_name = tag.get("name")
                if not tag_name:
                    continue

                tag_id = f"tag:{tag_name}"
                connections.append((tag_id, 0.0))

                # Add tag to metadata
                self.add_metadata_if_new(tag_id, f"Tag: {tag_name}", tag.get("url", ""))

                # Stream reverse connection (tag -> artist)
                tag_connections = [(mbid, 0.0)]
                append_to_graph(tag_id, tag_connections, str(self.output_dir))

        # Stream artist connections to disk
        if connections:
            append_to_graph(mbid, connections, str(self.output_dir))

        return new_artists

    async def collect_graph(
        self,
        starting_artist: Optional[str] = None,
        max_artists: Optional[int] = None,
        include_tags: bool = False,
        similar_per_artist: Optional[int] = 80,
        tags_per_artist: Optional[int] = 50,
        batch_size: int = 10,
        resume: bool = True,
    ) -> dict:
        """Collect artist graph with streaming approach."""

        # Load existing state or initialize
        if resume:
            resumed = self.load_state()
        else:
            resumed = False

        async with aiohttp.ClientSession() as session:
            # Initialize starting artist if needed
            if not resumed and not self.queue and starting_artist:
                if not await self.initialize_starting_artist(session, starting_artist):
                    return {"error": "Could not initialize starting artist"}

            total_processed = len(self.processed_mbids)
            batch_count = 0

            while self.queue and (max_artists is None or total_processed < max_artists):
                # Process batch
                batch_artists = []
                batch_size_actual = min(batch_size, len(self.queue))

                if max_artists is not None:
                    batch_size_actual = min(
                        batch_size_actual, max_artists - total_processed
                    )

                for _ in range(batch_size_actual):
                    if self.queue:
                        batch_artists.append(self.queue.popleft())

                if not batch_artists:
                    break

                # Process artists concurrently
                tasks = []
                for mbid in batch_artists:
                    task = self.process_single_artist(
                        session, mbid, include_tags, similar_per_artist, tags_per_artist
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
                    f"({total_processed}/{max_display} total)"
                )
                print(f"  New artists found: {total_new_artists}")
                print(f"  Queue size: {len(self.queue)}")
                print(
                    f"  Memory usage: {len(self.processed_mbids)} processed IDs, "
                    f"{len(self.seen_metadata_ids)} metadata entries"
                )

                # Periodic state save
                if batch_count % 10 == 0:
                    self.save_state()
                    print(f"  Saved state at batch {batch_count}")

                # Small delay to avoid overwhelming API
                await asyncio.sleep(0.1)

                if total_new_artists == 0:
                    print(
                        "⚠️  No new artists found - might have reached component limit"
                    )

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
