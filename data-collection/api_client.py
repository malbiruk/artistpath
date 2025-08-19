"""Last.fm API client with retry logic."""

import asyncio
import os
from typing import Dict, List, Optional

import aiohttp
from dotenv import load_dotenv
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

load_dotenv()

API_KEY = os.getenv("API_KEY")
BASE_URL = "http://ws.audioscrobbler.com/2.0/"

API_ERRORS = {
    "rate_limit": 0,
    "forbidden": 0,
    "other": 0,
    "exceptions": 0,
    "retries": 0,
}


class RateLimitError(Exception):
    """Custom exception for rate limiting."""
    pass


class APIError(Exception):
    """Custom exception for API errors."""
    pass


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=1, max=30),
    retry=retry_if_exception_type(
        (RateLimitError, APIError, aiohttp.ClientError, asyncio.TimeoutError)
    ),
    reraise=True,
)
async def fetch_json(session: aiohttp.ClientSession, params: dict) -> Optional[dict]:
    """Fetch JSON data from Last.fm API with retry logic."""
    params["api_key"] = API_KEY
    params["format"] = "json"

    try:
        async with session.get(
            BASE_URL, params=params, timeout=aiohttp.ClientTimeout(total=10)
        ) as response:
            if response.status == 200:
                data = await response.json()
                if not data:
                    print("⚠️ Empty response data - retrying...")
                    API_ERRORS["other"] += 1
                    API_ERRORS["retries"] += 1
                    raise APIError("Empty response data")
                if "error" in data:
                    print(f"⚠️ API Error: {data.get('message', 'Unknown error')} - retrying...")
                    API_ERRORS["other"] += 1
                    API_ERRORS["retries"] += 1
                    raise APIError(f"API returned error: {data.get('message')}")
                return data
            elif response.status == 429:
                print("⚠️  RATE LIMITED! Retrying with exponential backoff...")
                API_ERRORS["rate_limit"] += 1
                API_ERRORS["retries"] += 1
                raise RateLimitError("Rate limited")
            elif response.status == 403:
                print("❌ FORBIDDEN! Check your API key")
                API_ERRORS["forbidden"] += 1
                return None  # Don't retry forbidden errors
            else:
                print(f"❌ API ERROR: {response.status} - retrying...")
                API_ERRORS["other"] += 1
                API_ERRORS["retries"] += 1
                raise APIError(f"HTTP {response.status}")
    except (RateLimitError, APIError):
        raise  # Re-raise these for retry logic
    except Exception as e:
        print(f"❌ REQUEST ERROR: {e} - retrying...")
        API_ERRORS["exceptions"] += 1
        API_ERRORS["retries"] += 1
        raise


async def get_artist_info_by_name(
    session: aiohttp.ClientSession, artist_name: str
) -> Optional[Dict]:
    """Get artist info including mbid from artist name."""
    params = {"method": "artist.getinfo", "artist": artist_name}
    data = await fetch_json(session, params)
    if data and "artist" in data:
        return data["artist"]
    return None


async def get_similar_artists(
    session: aiohttp.ClientSession, mbid: str, limit: Optional[int] = 250
) -> List[Dict]:
    """Get similar artists for a given artist by mbid."""
    params = {"method": "artist.getsimilar", "mbid": mbid}
    if limit is not None:
        params["limit"] = limit

    data = await fetch_json(session, params)
    if data and "similarartists" in data:
        artists = data["similarartists"].get("artist", [])
        if isinstance(artists, list):
            return artists
    return []


async def get_artist_tags(
    session: aiohttp.ClientSession, mbid: str, limit: Optional[int] = 50
) -> List[Dict]:
    """Get top tags for an artist by mbid."""
    params = {"method": "artist.gettoptags", "mbid": mbid}
    if limit is not None:
        params["limit"] = limit

    data = await fetch_json(session, params)
    if data and "toptags" in data:
        tags = data["toptags"].get("tag", [])
        if isinstance(tags, list):
            return tags
        elif isinstance(tags, dict):
            return [tags]
    return []


def print_api_error_summary():
    """Print summary of API errors."""
    print("\n=== API Error Summary ===")
    print(f"Rate limit errors: {API_ERRORS['rate_limit']}")
    print(f"Other API errors: {API_ERRORS['other']}")
    print(f"Connection errors: {API_ERRORS['exceptions']}")
    print(f"Total retry attempts: {API_ERRORS['retries']}")