"""Memory-efficient streaming processor for artist graph collection."""

import asyncio
import json
import signal
import time
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
from .storage import (
    append_to_graph,
    append_to_metadata,
    load_names,
    save_state,
    scan_oldest_ids,
)

# State is ~250 MB and rewritten whole; saving every few batches would write
# terabytes a day. A crash costs at most this much crawling (re-crawled
# records are superseded by postprocessing's last-record-wins rule).
SAVE_INTERVAL_SECONDS = 600

# How many of the oldest graph records to queue for re-crawling once the BFS
# frontier runs dry. Just a read-ahead size: the sweep laps the file forever.
REFRESH_CHUNK = 200_000

# A persistent API failure re-queues every artist it touches, and the sweep
# never empties its queue to fall out of: a revoked key returns 403 forever, so
# the crawl would spin on retries while still saving state, keeping the
# healthcheck green. Fail the unit instead and let systemd back off.
MAX_CONSECUTIVE_FAILURES = 100


class StreamingCollector:
    def __init__(self, output_dir: str = "../data") -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.processed_mbids: set[str] = set()
        self.names: dict[str, str] = {}  # every artist with a metadata entry
        self.queue: deque = deque()
        self.stop_requested = False

        # Oldest-first refresh sweep; refresh_offset is a byte position in
        # graph.ndjson (see scan_oldest_ids).
        self.refresh_queue: deque = deque()
        self.refresh_offset = 0
        # Graph records appended, which is what the rebuild trigger gates on:
        # a sweep refreshes edges without discovering many new artists.
        self.crawled_total = 0
        self.consecutive_failures = 0

    def load_state(self) -> bool:
        state_path = self.output_dir / "collection_state.json"

        if not state_path.exists():
            return False

        with state_path.open() as f:
            state = json.load(f)
            self.processed_mbids = set(state.get("processed_mbids", []))
            self.queue = deque(state.get("queue", []))
            self.refresh_queue = deque(state.get("refresh_queue", []))
            self.refresh_offset = state.get("refresh_offset", 0)
            # Seed from the processed count when state predates crawled_total,
            # so the first delta against last_refresh_count.txt stays meaningful.
            self.crawled_total = state.get("crawled_total") or len(self.processed_mbids)

        self.names = load_names(str(self.output_dir))

        # metadata.ndjson is appended as artists are discovered, so after a
        # crash it is ahead of the saved queue: anything discovered since the
        # last save is neither processed nor queued. Rebuild that frontier.
        queued = set(self.queue)
        self.queue.extend(
            artist_id
            for artist_id in self.names
            if artist_id not in self.processed_mbids and artist_id not in queued
        )

        print(f"Resuming with {len(self.processed_mbids)} processed artists")
        print(f"Queue has {len(self.queue)} pending artists")
        print(f"Refresh queue has {len(self.refresh_queue)} at offset {self.refresh_offset}")
        print(f"Tracking {len(self.names)} metadata entries")
        return True

    def save_state(self) -> None:
        save_state(
            self.processed_mbids,
            self.queue,
            str(self.output_dir),
            refresh_queue=self.refresh_queue,
            refresh_offset=self.refresh_offset,
            crawled_total=self.crawled_total,
        )

    def request_stop(self) -> None:
        # Idempotent: systemd signals the whole cgroup and uv forwards its copy,
        # so the process gets several SIGTERMs per stop.
        if not self.stop_requested:
            print("🛑 Stop requested - finishing current batch and saving state...")
        self.stop_requested = True

    def add_metadata_if_new(self, node_id: str, name: str, url: str) -> bool:
        if node_id not in self.names:
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

    def refill_refresh_queue(self) -> bool:
        """Queue the next chunk of oldest graph records for re-crawling."""
        ids, self.refresh_offset = scan_oldest_ids(
            str(self.output_dir),
            self.refresh_offset,
            REFRESH_CHUNK,
        )
        if not ids and self.refresh_offset:
            # Nothing readable between the cursor and EOF - a crash-torn tail,
            # say. Start the next lap instead of reporting the crawl finished.
            ids, self.refresh_offset = scan_oldest_ids(str(self.output_dir), 0, REFRESH_CHUNK)
        self.refresh_queue.extend(ids)
        if ids:
            print(f"♻️  Queued {len(ids)} oldest records, offset now {self.refresh_offset}")
        return bool(ids)

    async def process_single_artist(
        self,
        session: aiohttp.ClientSession,
        artist_id: str,
        similar_per_artist: int | None,
        *,
        refresh: bool = False,
    ) -> int:
        # A refresh deliberately re-crawls an already-processed artist so its
        # new record supersedes the stale one; the frontier still crawls once.
        if not refresh and artist_id in self.processed_mbids:
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
            if refresh:
                # Already processed, so it must not go back on the frontier.
                self.refresh_queue.append(artist_id)
            else:
                self.processed_mbids.discard(artist_id)
                self.queue.append(artist_id)
            self.consecutive_failures += 1
            return 0

        self.consecutive_failures = 0

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

        # An empty result appends nothing, so a refresh that comes back blank
        # leaves the existing record standing rather than blanking it.
        if connections:
            append_to_graph(artist_id, connections, str(self.output_dir))
            self.crawled_total += 1

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
            last_save = time.monotonic()

            while not self.stop_requested and (
                max_artists is None or total_processed < max_artists
            ):
                # Only a graph with nothing left to read ends the crawl: the
                # sweep refills itself from graph.ndjson whenever it empties.
                if (
                    not self.queue
                    and not self.refresh_queue
                    and not self.refill_refresh_queue()
                ):
                    break

                batch_size_actual = min(batch_size, len(self.queue) + len(self.refresh_queue))

                if max_artists is not None:
                    batch_size_actual = min(batch_size_actual, max_artists - total_processed)

                # Drawing a batch from only one queue would let the single
                # artist a sweep turns up shrink the next batch to one, halving
                # the crawl rate.
                batch_artists: list[tuple[str, bool]] = []
                while len(batch_artists) < batch_size_actual and self.queue:
                    batch_artists.append((self.queue.popleft(), False))
                while len(batch_artists) < batch_size_actual and self.refresh_queue:
                    batch_artists.append((self.refresh_queue.popleft(), True))

                if not batch_artists:
                    break

                tasks = [
                    self.process_single_artist(
                        session,
                        mbid,
                        similar_per_artist,
                        refresh=refresh,
                    )
                    for mbid, refresh in batch_artists
                ]

                new_artist_counts = await asyncio.gather(*tasks)

                if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    self.save_state()
                    msg = f"{self.consecutive_failures} consecutive API failures - aborting"
                    raise RuntimeError(msg)

                total_new_artists = sum(new_artist_counts)
                total_processed += len(batch_artists)
                batch_count += 1

                max_display = "unlimited" if max_artists is None else str(max_artists)
                print(
                    f"Batch {batch_count}: Processed {len(batch_artists)} artists "
                    f"({total_processed}/{max_display} total)",
                )
                print(f"  New artists found: {total_new_artists}")
                print(f"  Queue size: {len(self.queue)} (+{len(self.refresh_queue)} refresh)")
                print(
                    f"  Memory usage: {len(self.processed_mbids)} processed IDs, "
                    f"{len(self.names)} metadata entries",
                )

                if time.monotonic() - last_save >= SAVE_INTERVAL_SECONDS:
                    self.save_state()
                    last_save = time.monotonic()
                    print(f"  Saved state at batch {batch_count}")

                await asyncio.sleep(0.1)

                # A sweep averages ~0.1 new artists per crawl, so a batch with
                # none is normal there and only worth flagging for discovery.
                discovering = any(not refresh for _, refresh in batch_artists)
                if total_new_artists == 0 and discovering:
                    print("⚠️  No new artists found - might have reached component limit")

        self.save_state()

        if self.stop_requested:
            print("\n🛑 Collection stopped, state saved")
        else:
            print("\n🎉 Collection complete!")
        print(f"📊 Processed {len(self.processed_mbids)} artists")
        print(f"📝 Collected {len(self.names)} metadata entries")
        print(f"⏭️  Queue remaining: {len(self.queue)} (+{len(self.refresh_queue)} refresh)")
        print_api_error_summary()

        return {
            "processed_artists": len(self.processed_mbids),
            "metadata_entries": len(self.names),
            "queue_remaining": len(self.queue) + len(self.refresh_queue),
            "completed": not self.queue and not self.refresh_queue,
        }
