"""Last.fm API client with retry logic."""

import asyncio
import os
import uuid

import aiohttp
from dotenv import load_dotenv
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

load_dotenv("../.env")  # Try root level first
load_dotenv()  # Fallback to current directory

API_KEY = os.getenv("API_KEY")
BASE_URL = "http://ws.audioscrobbler.com/2.0/"

API_ERRORS = {
    "rate_limit": 0,
    "forbidden": 0,
    "other": 0,
    "exceptions": 0,
    "retries": 0,
}

RESPONSE_CODES = {
    "ok": 200,
    "rate_limit": 429,
    "forbidden": 403,
}
NOT_FOUND_ERROR_CODE = 6


class RateLimitError(Exception):
    """Custom exception for rate limiting."""


class APIError(Exception):
    """Custom exception for API errors."""


def handle_empty_response() -> None:
    print("⚠️ Empty response data - retrying...")
    API_ERRORS["other"] += 1
    API_ERRORS["retries"] += 1
    raise APIError("Empty response data")


def handle_error_data(data: dict, params: dict) -> None:
    error_code = data.get("error")
    if error_code == NOT_FOUND_ERROR_CODE:  # Artist not found
        print(
            f"⚠️ Artist not found: {params.get('mbid', params.get('artist', 'unknown'))}",
        )
        API_ERRORS["other"] += 1
        return  # Don't retry for not found errors
    print(f"⚠️ API Error: {data.get('message', 'Unknown error')} - retrying...")
    API_ERRORS["other"] += 1
    API_ERRORS["retries"] += 1
    raise APIError(f"API returned error: {data.get('message')}")


def handle_rate_limit() -> None:
    print("⚠️  RATE LIMITED! Retrying with exponential backoff...")
    API_ERRORS["rate_limit"] += 1
    API_ERRORS["retries"] += 1
    raise RateLimitError("Rate limited")


def handle_forbidden_response() -> None:
    print("❌ FORBIDDEN! Check your API key")
    API_ERRORS["forbidden"] += 1
    # Don't retry forbidden errors


def handle_other_api_error(response_status: int) -> None:
    print(f"❌ API ERROR: {response_status} - retrying...")
    API_ERRORS["other"] += 1
    API_ERRORS["retries"] += 1
    raise APIError(f"HTTP {response_status}")


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=1, max=30),
    retry=retry_if_exception_type(
        (RateLimitError, APIError, aiohttp.ClientError, asyncio.TimeoutError),
    ),
    reraise=False,
)
async def fetch_json(session: aiohttp.ClientSession, params: dict) -> dict | None:
    """Fetch JSON data from Last.fm API with retry logic."""
    params["api_key"] = API_KEY
    params["format"] = "json"

    try:
        async with session.get(
            BASE_URL,
            params=params,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as response:
            if response.status == RESPONSE_CODES["ok"]:
                data = await response.json()

                if not data:
                    handle_empty_response()  # This raises, no return

                if "error" in data:
                    return handle_error_data(data, params)  # This CAN return None

                return data

            if response.status == RESPONSE_CODES["rate_limit"]:
                handle_rate_limit()  # This raises, no return

            if response.status == RESPONSE_CODES["forbidden"]:
                return handle_forbidden_response()  # This returns None (no retry)

            handle_other_api_error(response.status)  # This raises, no return

    except (RateLimitError, APIError):
        raise  # Re-raise these for retry logic

    except Exception as e:
        print(f"❌ REQUEST ERROR: {e} - retrying...")
        API_ERRORS["exceptions"] += 1
        API_ERRORS["retries"] += 1
        raise


async def get_artist_info_by_name(
    session: aiohttp.ClientSession,
    artist_name: str,
) -> dict | None:
    """Get artist info including mbid from artist name."""
    params = {"method": "artist.getinfo", "artist": artist_name}
    data = await fetch_json(session, params)
    if data and "artist" in data:
        return data["artist"]
    return None


async def get_similar_artists(
    session: aiohttp.ClientSession,
    mbid: str,
    limit: int | None = 250,
) -> list[dict]:
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


async def get_similar_artists_by_name(
    session: aiohttp.ClientSession,
    artist_name: str,
    limit: int | None = 250,
) -> list[dict]:
    """Get similar artists for a given artist by name."""
    params = {"method": "artist.getsimilar", "artist": artist_name}
    if limit is not None:
        params["limit"] = limit

    data = await fetch_json(session, params)
    if data and "similarartists" in data:
        artists = data["similarartists"].get("artist", [])
        if isinstance(artists, list):
            return artists
    return []


def is_real_mbid(artist_id: str) -> bool:
    """Check if artist_id is a real MBID (not our generated UUID5)."""
    try:
        parsed = uuid.UUID(artist_id)
    except (ValueError, AttributeError):
        return False
    else:
        uuid_version = 5
        return parsed.version != uuid_version


def print_api_error_summary() -> None:
    """Print summary of API errors."""
    print("\n=== API Error Summary ===")
    print(f"Rate limit errors: {API_ERRORS['rate_limit']}")
    print(f"Other API errors: {API_ERRORS['other']}")
    print(f"Connection errors: {API_ERRORS['exceptions']}")
    print(f"Total retry attempts: {API_ERRORS['retries']}")
