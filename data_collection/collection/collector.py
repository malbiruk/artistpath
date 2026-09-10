"""Memory-efficient streaming processor for artist graph collection."""

import asyncio
import json
import os
import signal
from collections import deque
from pathlib import Path

import aiohttp
from tenacity import RetryError

from .api_client import (
    get_artist_info_by_name,
    get_similar_artists,
    get_similar_artists_by_name,
    is_real_mbid,
    print_api_error_summary,
)
from .storage import append_to_graph, append_to_metadata, load_names, save_state


class StreamingCollector:
    def __init__(self, output_dir: str = "../data") -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.processed_mbids: set[str] = set()
        self.seen_metadata_ids: set[str] = set()
        self.names: dict[str, str] = {}
        self.queue: deque = deque()
        self.stop_requested = False

    def load_state(self) -> bool:
        state_path = self.output_dir / "collection_state.json"
        metadata_ids_path = self.output_dir / "seen_metadata.txt"

        if not state_path.exists():
            return False

        with state_path.open() as f:
            state = json.load(f)
            self.processed_mbids = set(state.get("processed_mbids", []))
            self.queue = deque(state.get("queue", []))

        if metadata_ids_path.exists():
            with metadata_ids_path.open() as f:
                self.seen_metadata_ids = {line.strip() for line in f if line.strip()}

        self.names = load_names(str(self.output_dir))

        print(f"Resuming with {len(self.processed_mbids)} processed artists")
        print(f"Queue has {len(self.queue)} pending artists")
        print(f"Tracking {len(self.seen_metadata_ids)} metadata entries")
        return True

    def save_state(self) -> None:
        save_state(self.processed_mbids, self.queue, str(self.output_dir))

        metadata_ids_path = self.output_dir / "seen_metadata.txt"
        tmp_path = metadata_ids_path.with_suffix(".txt.tmp")
        with tmp_path.open("w") as f:
            for metadata_id in self.seen_metadata_ids:
                f.write(f"{metadata_id}\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, metadata_ids_path)

    def request_stop(self) -> None:
        # Idempotent: systemd signals the whole cgroup and uv forwards its copy,
        # so the process gets several SIGTERMs per stop.
        if not self.stop_requested:
            print("🛑 Stop requested - finishing current batch and saving state...")
        self.stop_requested = True

    def add_metadata_if_new(self, node_id: str, name: str, url: str) -> bool:
        if node_id not in self.seen_metadata_ids:
            self.seen_metadata_ids.add(node_id)
            self.names[node_id] = name
            append_to_metadata(node_id, name, url, str(self.output_dir))
            return True
        return False

    async def initialize_starting_artist(
        self,
        session: aiohttp.ClientSession,
        starting_artist: str,
    ) -> bool:
        print(f"Starting with artist: {starting_artist}")
        info = await get_artist_info_by_name(session, starting_artist)

        if not info:
            print(f"Could not find artist info for {starting_artist}")
            return False

        if info.get("mbid"):
            artist_id = info["mbid"]
            print(f"  Using MBID: {artist_id}")
        elif info.get("url"):
            import uuid

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
        return self.names.get(artist_id)

    async def fetch_similar_artists(
        self,
        session: aiohttp.ClientSession,
        artist_id: str,
        similar_per_artist: int | None,
    ) -> list[dict]:
        if is_real_mbid(artist_id):
            similar_artists = await get_similar_artists(session, artist_id, similar_per_artist)
            if similar_artists:
                return similar_artists

        artist_name = self.get_artist_name_from_metadata(artist_id)
        if not artist_name:
            if not is_real_mbid(artist_id):
                print(f"  ❌ Could not find name for UUID5 artist: {artist_id}")
            return []
        return await get_similar_artists_by_name(session, artist_name, similar_per_artist)

    async def process_single_artist(
        self,
        session: aiohttp.ClientSession,
        artist_id: str,
        similar_per_artist: int | None,
    ) -> int:
        if artist_id in self.processed_mbids:
            return 0

        self.processed_mbids.add(artist_id)

        try:
            similar_artists = await self.fetch_similar_artists(
                session, artist_id, similar_per_artist
            )
        except RetryError:
            # Last.fm unreachable after all retries: try this artist again later
            # instead of crashing the crawl.
            print(f"  ⚠️ API unavailable for {artist_id} - re-queued")
            self.processed_mbids.discard(artist_id)
            self.queue.append(artist_id)
            return 0

        connections = []
        new_artists = 0

        for similar in similar_artists:
            if similar.get("mbid"):
                similar_id = similar["mbid"]
            elif similar.get("url"):
                import uuid

                similar_id = str(uuid.uuid5(uuid.NAMESPACE_URL, similar["url"]))
            else:
                continue

            match_score = float(similar.get("match", 0))
            connections.append((similar_id, match_score))

            if self.add_metadata_if_new(
                similar_id,
                similar.get("name", ""),
                similar.get("url", ""),
            ):
                new_artists += 1
                if similar_id not in self.processed_mbids:
                    self.queue.append(similar_id)

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
        resumed = self.load_state() if resume else False

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self.request_stop)

        async with aiohttp.ClientSession() as session:
            if (
                not resumed
                and not self.queue
                and starting_artist
                and not await self.initialize_starting_artist(session, starting_artist)
            ):
                return {"error": "Could not initialize starting artist"}

            total_processed = len(self.processed_mbids)
            batch_count = 0

            while (
                self.queue
                and not self.stop_requested
                and (max_artists is None or total_processed < max_artists)
            ):
                batch_size_actual = min(batch_size, len(self.queue))

                if max_artists is not None:
                    batch_size_actual = min(batch_size_actual, max_artists - total_processed)

                batch_artists = [
                    self.queue.popleft() for _ in range(batch_size_actual) if self.queue
                ]

                if not batch_artists:
                    break

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

                if batch_count % 10 == 0:
                    self.save_state()
                    print(f"  Saved state at batch {batch_count}")

                await asyncio.sleep(0.1)

                if total_new_artists == 0:
                    print("⚠️  No new artists found - might have reached component limit")

        self.save_state()

        if self.stop_requested:
            print("\n🛑 Collection stopped, state saved")
        else:
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
