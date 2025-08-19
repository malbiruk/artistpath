"""Graph processing and artist batch handling."""

import asyncio
from typing import Dict, List, Optional, Set

import aiohttp
from api_client import get_artist_tags, get_similar_artists
from data_storage import append_to_graph, append_to_metadata


def add_artist_to_metadata(
    artist_mbid: str, artist_data: Dict, artist_metadata: Dict, output_dir: str
) -> bool:
    """Add artist to metadata if not already present. Returns True if new."""
    if artist_mbid not in artist_metadata:
        name = artist_data.get("name", "")
        url = artist_data.get("url", "")
        artist_metadata[artist_mbid] = {"name": name, "url": url}
        append_to_metadata(artist_mbid, name, url, output_dir)
        return True
    return False


def add_tag_to_metadata(
    tag_name: str, tag_data: Dict, artist_metadata: Dict, output_dir: str
) -> str:
    """Add tag to metadata and return tag_id."""
    tag_id = f"tag:{tag_name}"
    if tag_id not in artist_metadata:
        name = f"Tag: {tag_name}"
        url = tag_data.get("url", "")
        artist_metadata[tag_id] = {"name": name, "url": url}
        append_to_metadata(tag_id, name, url, output_dir)
    return tag_id


def process_similar_artists(
    similar_artists: List[Dict], artist_metadata: Dict, output_dir: str
) -> tuple[List[tuple], List[str]]:
    """Process similar artists and return connections and new artist IDs."""
    connections = []
    new_artists = []

    for similar in similar_artists:
        if not similar.get("mbid"):
            continue

        similar_mbid = similar["mbid"]
        match_score = float(similar.get("match", 0))
        connections.append((similar_mbid, match_score))

        if add_artist_to_metadata(similar_mbid, similar, artist_metadata, output_dir):
            new_artists.append(similar_mbid)

    return connections, new_artists


def process_artist_tags(
    artist_tags: List[Dict],
    artist_mbid: str,
    artist_metadata: Dict,
    graph: Dict,
    output_dir: str,
) -> List[tuple]:
    """Process artist tags and return tag connections."""
    tag_connections = []

    for tag in artist_tags:
        tag_name = tag.get("name")
        if not tag_name:
            continue

        tag_id = add_tag_to_metadata(tag_name, tag, artist_metadata, output_dir)
        tag_connections.append((tag_id, 0.0))

        # Add reverse connection from tag to artist
        if tag_id not in graph:
            graph[tag_id] = []
        if not any(conn[0] == artist_mbid for conn in graph[tag_id]):
            graph[tag_id].append((artist_mbid, 0.0))
            append_to_graph(tag_id, graph[tag_id], output_dir)

    return tag_connections


async def process_artist_batch(
    session: aiohttp.ClientSession,
    artists_to_process: List[str],
    processed_mbids: Set[str],
    artist_metadata: Dict,
    graph: Dict,
    include_tags: bool = True,
    similar_per_artist: Optional[int] = 250,
    tags_per_artist: Optional[int] = 50,
    output_dir: str = "../data",
) -> List[str]:
    """Process a batch of artists concurrently."""
    new_artists = []

    # Filter already processed artists
    actually_processed = []
    similar_tasks = []
    tag_tasks = []

    for mbid in artists_to_process:
        if mbid not in processed_mbids:
            similar_tasks.append(get_similar_artists(session, mbid, similar_per_artist))
            if include_tags:
                tag_tasks.append(get_artist_tags(session, mbid, tags_per_artist))
            actually_processed.append(mbid)
            processed_mbids.add(mbid)

    # Wait for all API calls to complete
    similar_results = await asyncio.gather(*similar_tasks)
    if include_tags:
        tag_results = await asyncio.gather(*tag_tasks)
    else:
        tag_results = [[] for _ in similar_results]

    # Process results for each artist
    for mbid, similar_artists, artist_tags in zip(
        actually_processed, similar_results, tag_results
    ):
        # Process similar artists
        similar_connections, similar_new_artists = process_similar_artists(
            similar_artists, artist_metadata, output_dir
        )
        new_artists.extend(similar_new_artists)

        # Process tags if enabled
        tag_connections = []
        if include_tags:
            tag_connections = process_artist_tags(
                artist_tags, mbid, artist_metadata, graph, output_dir
            )

        # Combine all connections and save
        all_connections = similar_connections + tag_connections
        if all_connections:
            graph[mbid] = all_connections
            append_to_graph(mbid, all_connections, output_dir)

    return new_artists
