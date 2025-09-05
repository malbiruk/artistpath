"""Main entry point for artist metadata collection from external APIs."""

import asyncio
import json
import time
from collections import deque
from datetime import UTC
from pathlib import Path

import aiohttp
from dotenv import load_dotenv
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from api_client import API_KEY, RESPONSE_CODES

load_dotenv("../.env")
load_dotenv()

REFRESH_IN_DAYS = 30
ITUNES_BASE_URL = "https://itunes.apple.com/search"
LASTFM_BASE_URL = "http://ws.audioscrobbler.com/2.0/"


class MetadataCollector:
    """Collects enriched metadata for artists from Last.fm and iTunes."""

    def __init__(self, output_dir: str = "../data") -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.api_key = API_KEY
        self.stats = {
            "total": 0,
            "successful": 0,
            "failed": 0,
            "api_errors": 0,
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
        reraise=False,
    )
    async def fetch_lastfm_artist_info(
        self,
        session: aiohttp.ClientSession,
        artist_name: str,
    ) -> dict | None:
        """Fetch artist info from Last.fm."""
        params = {
            "method": "artist.getinfo",
            "artist": artist_name,
            "api_key": self.api_key,
            "format": "json",
        }

        try:
            async with session.get(
                LASTFM_BASE_URL,
                params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status == RESPONSE_CODES["ok"]:
                    data = await response.json()
                    if "artist" in data:
                        return data["artist"]
        except Exception as e:
            print(f"⚠️  Error fetching Last.fm info for {artist_name}: {e}")
            self.stats["api_errors"] += 1
        return None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
        reraise=False,
    )
    async def fetch_lastfm_top_tracks(
        self,
        session: aiohttp.ClientSession,
        artist_name: str,
        limit: int = 5,
    ) -> list | None:
        """Fetch top tracks from Last.fm."""
        params = {
            "method": "artist.gettoptracks",
            "artist": artist_name,
            "api_key": self.api_key,
            "format": "json",
            "limit": limit,
        }

        try:
            async with session.get(
                LASTFM_BASE_URL,
                params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status == RESPONSE_CODES["ok"]:
                    data = await response.json()
                    if "toptracks" in data and "track" in data["toptracks"]:
                        return data["toptracks"]["track"]
        except Exception as e:
            print(f"⚠️  Error fetching Last.fm tracks for {artist_name}: {e}")
            self.stats["api_errors"] += 1
        return None

    async def fetch_itunes_preview(
        self,
        session: aiohttp.ClientSession,
        artist_name: str,
        track_name: str,
    ) -> str | None:
        """Fetch iTunes preview URL for a track."""
        # Clean up the search terms for better iTunes matching
        clean_artist = artist_name.replace("&", "and").replace("  ", " ").strip()
        clean_track = track_name.replace("&", "and").replace("  ", " ").strip()
        # Don't replace spaces with +, let aiohttp handle URL encoding
        search_term = f"{clean_artist} {clean_track}"

        params = {
            "term": search_term,
            "media": "music",
            "entity": "song",
            "limit": 1,
        }

        try:
            async with session.get(
                ITUNES_BASE_URL,
                params=params,
                timeout=aiohttp.ClientTimeout(total=10),
                headers={"User-Agent": "artistpath-metadata-collector/1.0"},
            ) as response:
                if response.status == RESPONSE_CODES["ok"]:
                    # iTunes sometimes returns text/javascript content-type but valid JSON
                    # Try parsing as JSON regardless of content-type
                    try:
                        data = await response.json(content_type=None)  # Ignore content-type check
                        results = data.get("results", [])
                        if results:
                            return results[0].get("previewUrl")
                    except json.JSONDecodeError:
                        # If it's truly not JSON, warn and return None
                        content_type = response.headers.get("content-type", "")
                        print(
                            f"⚠️  iTunes returned non-JSON {content_type} for {artist_name} - {track_name}",
                        )
                        return None
        except Exception as e:
            print(f"⚠️  iTunes error for {artist_name} - {track_name}: {e}")
        return None

    def process_lastfm_data(self, artist_info: dict) -> dict:
        """Process Last.fm artist data into our format."""
        # Extract image URL
        images = artist_info.get("image", [])
        image_url = None
        for img in images:
            if img.get("size") in ["large", "medium"] and img.get("#text"):
                image_url = img["#text"]
                if image_url:  # Take first valid image
                    break

        # Extract stats
        stats = artist_info.get("stats", {})

        # Extract tags
        tags = []
        if "tags" in artist_info and "tag" in artist_info["tags"]:
            tags = [tag["name"] for tag in artist_info["tags"]["tag"]]

        # Extract bio
        bio = artist_info.get("bio", {})
        bio_summary = bio.get("summary", "").replace("Read more on Last.fm", "").strip()
        bio_full = bio.get("content", "").replace("Read more on Last.fm", "").strip()

        return {
            "url": artist_info.get("url"),
            "image_url": image_url,
            "listeners": stats.get("listeners"),
            "playcount": stats.get("playcount"),
            "tags": tags,
            "bio_summary": bio_summary if bio_summary else None,
            "bio_full": bio_full if bio_full else None,
        }

    async def process_artist(
        self,
        session: aiohttp.ClientSession,
        artist_id: str,
        artist_name: str,
        artist_url: str,
    ) -> dict | None:
        """Process a single artist - fetch all metadata."""
        # Fetch Last.fm data
        lastfm_info = await self.fetch_lastfm_artist_info(session, artist_name)
        lastfm_tracks = await self.fetch_lastfm_top_tracks(session, artist_name)

        result = {
            "id": artist_id,
            "name": artist_name,
            "url": artist_url,
            "last_fetched": int(time.time()),
        }

        # Process Last.fm artist info
        if lastfm_info:
            result["lastfm"] = self.process_lastfm_data(lastfm_info)

        # Process tracks with iTunes previews
        if lastfm_tracks:
            tracks_with_previews = []
            for i, track in enumerate(lastfm_tracks[:5]):  # Limit to top 5
                # Add small delay between iTunes requests to avoid rate limiting
                if i > 0:
                    await asyncio.sleep(0.1)

                preview_url = await self.fetch_itunes_preview(session, artist_name, track["name"])
                tracks_with_previews.append(
                    {
                        "name": track["name"],
                        "url": track["url"],
                        "playcount": track["playcount"],
                        "listeners": track["listeners"],
                        "preview_url": preview_url,
                    },
                )
            result["tracks"] = tracks_with_previews

        return result

    async def collect_metadata(  # noqa: C901, PLR0912
        self,
        batch_size: int = 10,
        rate_limit_delay: float = 0.2,
    ) -> dict:
        """Collect metadata for all artists."""
        metadata_file = self.output_dir / "metadata.ndjson"
        output_file = self.output_dir / "artist_metadata.ndjson"
        temp_file = self.output_dir / "artist_metadata.ndjson.tmp"

        if not metadata_file.exists():
            return {"error": "metadata.ndjson not found"}

        # Count total artists
        with metadata_file.open() as f:
            total_artists = sum(1 for line in f if line.strip())

        self.stats["total"] = total_artists
        print(f"📊 Found {total_artists:,} artists to process")
        print(f"🔑 API Key: {self.api_key[:8]}..." if self.api_key else "⚠️  No API key!")
        print(f"📦 Batch size: {batch_size}")
        print(f"⏱  Rate limit delay: {rate_limit_delay}s between batches")
        print(f"💾 Output: {output_file}")

        async with aiohttp.ClientSession() as session:
            with metadata_file.open() as infile, temp_file.open("w") as outfile:
                batch = deque(maxlen=batch_size)
                processed = 0

                for line_ in infile:
                    line = line_.strip()
                    if not line:
                        continue

                    try:
                        artist = json.loads(line)
                        batch.append((artist["id"], artist["name"], artist["url"]))

                        if len(batch) >= batch_size:
                            # Process batch
                            tasks = [
                                self.process_artist(session, aid, name, url)
                                for aid, name, url in batch
                            ]
                            results = await asyncio.gather(*tasks)

                            for result in results:
                                if result:
                                    outfile.write(json.dumps(result) + "\n")
                                    self.stats["successful"] += 1
                                else:
                                    self.stats["failed"] += 1

                            processed += len(batch)
                            if processed % 100 == 0:
                                print(f"  Processed {processed:,}/{total_artists:,} artists...")

                            batch.clear()

                            # Rate limiting
                            await asyncio.sleep(rate_limit_delay)

                    except json.JSONDecodeError as e:
                        print(f"⚠️  Skipping malformed line: {e}")
                        self.stats["failed"] += 1
                        continue

                # Process remaining batch
                if batch:
                    tasks = [
                        self.process_artist(session, aid, name, url) for aid, name, url in batch
                    ]
                    results = await asyncio.gather(*tasks)

                    for result in results:
                        if result:
                            outfile.write(json.dumps(result) + "\n")
                            self.stats["successful"] += 1
                        else:
                            self.stats["failed"] += 1

        # Atomic rename
        temp_file.replace(output_file)

        return {
            "total": self.stats["total"],
            "successful": self.stats["successful"],
            "failed": self.stats["failed"],
            "api_errors": self.stats["api_errors"],
            "output_file": str(output_file),
            "file_size_mb": output_file.stat().st_size / (1024**2),
        }


async def main() -> None:
    """Main function for metadata collection."""
    # Configuration
    config = {
        "batch_size": 10,
        "rate_limit_delay": 0.2,  # 200ms between batches
    }

    # Create collector
    collector = MetadataCollector(output_dir="../data")

    print("🚀 Starting artist metadata collection...")
    print("=" * 60)

    # Collect metadata
    result = await collector.collect_metadata(**config)

    if "error" not in result:
        print("\n✅ Metadata collection finished successfully!")
        print(f"✓ Processed: {result['successful']:,}/{result['total']:,} artists")
        if result["failed"] > 0:
            print(f"⚠️  Failed: {result['failed']:,} artists")
        if result["api_errors"] > 0:
            print(f"⚠️  API errors: {result['api_errors']:,}")
        print(f"💾 Output: {result['output_file']} ({result['file_size_mb']:.1f} MB)")
    else:
        print(f"❌ Collection failed: {result['error']}")


def show_file_info() -> None:
    """Show information about the metadata file."""
    from datetime import datetime

    metadata_file = Path("../data/artist_metadata.ndjson")

    if not metadata_file.exists():
        print("⚠️  No artist_metadata.ndjson found")
        return

    # Count entries and check freshness
    entries = 0
    oldest_timestamp = float("inf")
    newest_timestamp = 0

    with metadata_file.open() as f:
        for line in f:
            if line.strip():
                try:
                    data = json.loads(line)
                    entries += 1
                    timestamp = data.get("last_fetched", 0)
                    oldest_timestamp = min(oldest_timestamp, timestamp)
                    newest_timestamp = max(newest_timestamp, timestamp)
                except Exception as e:
                    print(f"Error retrieving data timestamp: {e}")

    print("\n📊 Metadata file info:")
    print(f"  Entries: {entries:,}")
    print(f"  Size: {metadata_file.stat().st_size / (1024**2):.1f} MB")

    if oldest_timestamp < float("inf"):
        oldest_date = datetime.fromtimestamp(oldest_timestamp, tz=UTC).strftime("%Y-%m-%d %H:%M")
        newest_date = datetime.fromtimestamp(newest_timestamp, tz=UTC).strftime("%Y-%m-%d %H:%M")
        days_old = (time.time() - oldest_timestamp) / (24 * 3600)

        print(f"  Oldest entry: {oldest_date} ({days_old:.0f} days old)")
        print(f"  Newest entry: {newest_date}")

        if days_old > REFRESH_IN_DAYS:
            print("  ⚠️  Some data is over 30 days old - consider re-running collection")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        # Just check the existing file without collecting
        show_file_info()
    else:
        # Show info BEFORE collection to see how stale the data is
        print("📊 Current metadata status:")
        show_file_info()
        
        # Run collection
        asyncio.run(main())
        
        # Show info AFTER collection
        print("\n📊 Updated metadata status:")
        show_file_info()
