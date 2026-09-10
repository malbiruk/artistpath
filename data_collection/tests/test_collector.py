"""Tests for StreamingCollector state persistence and collection control flow."""

import asyncio
import json
import uuid

import aiohttp
import tenacity

from collection.collector import StreamingCollector


def test_save_state_round_trips_metadata_ids_and_leaves_no_temp_file(tmp_path):
    collector = StreamingCollector(output_dir=str(tmp_path))
    collector.seen_metadata_ids = {"id-a", "id-b", "id-c"}

    collector.save_state()

    ids = {
        line.strip()
        for line in (tmp_path / "seen_metadata.txt").read_text().splitlines()
        if line.strip()
    }
    assert ids == {"id-a", "id-b", "id-c"}
    assert not (tmp_path / "seen_metadata.txt.tmp").exists()


def test_add_metadata_if_new_makes_name_available_for_lookup(tmp_path):
    collector = StreamingCollector(output_dir=str(tmp_path))

    collector.add_metadata_if_new("id-1", "Cool Band", "http://example.com/cool-band")

    assert collector.get_artist_name_from_metadata("id-1") == "Cool Band"


def test_load_state_populates_names_from_metadata_file(tmp_path):
    (tmp_path / "collection_state.json").write_text(
        json.dumps({"processed_mbids": [], "queue": []})
    )
    (tmp_path / "metadata.ndjson").write_text(
        json.dumps({"id": "id-1", "name": "Cool Band", "url": "http://example.com"}) + "\n"
    )

    collector = StreamingCollector(output_dir=str(tmp_path))
    collector.load_state()

    assert collector.get_artist_name_from_metadata("id-1") == "Cool Band"


def test_collect_graph_stops_after_current_batch_on_stop_request(tmp_path, monkeypatch):
    ids = [str(uuid.uuid5(uuid.NAMESPACE_URL, f"artist-{i}")) for i in range(4)]

    (tmp_path / "collection_state.json").write_text(
        json.dumps({"processed_mbids": [], "queue": ids})
    )
    with (tmp_path / "metadata.ndjson").open("w") as f:
        for i, artist_id in enumerate(ids):
            f.write(json.dumps({"id": artist_id, "name": f"Artist {i}", "url": "u"}) + "\n")

    calls = []
    collector = StreamingCollector(output_dir=str(tmp_path))

    async def fake_get_similar_artists_by_name(session, artist_name, limit):
        calls.append(artist_name)
        collector.request_stop()
        return []

    monkeypatch.setattr(
        "collection.collector.get_similar_artists_by_name",
        fake_get_similar_artists_by_name,
    )

    result = asyncio.run(
        collector.collect_graph(starting_artist=None, batch_size=1, resume=True)
    )

    assert len(calls) == 1
    assert result["queue_remaining"] == len(ids) - 1

    saved_state = json.loads((tmp_path / "collection_state.json").read_text())
    assert saved_state["queue"] == ids[1:]


def test_process_single_artist_requeues_artist_on_retry_error(tmp_path, monkeypatch):
    artist_id = str(uuid.uuid4())
    collector = StreamingCollector(output_dir=str(tmp_path))

    async def raising_get_similar_artists(session, mbid, limit):
        raise tenacity.RetryError(tenacity.Future.construct(1, ValueError("boom"), True))

    monkeypatch.setattr(
        "collection.collector.get_similar_artists",
        raising_get_similar_artists,
    )

    async def run():
        async with aiohttp.ClientSession() as session:
            return await collector.process_single_artist(session, artist_id, 80)

    new_artist_count = asyncio.run(run())

    assert new_artist_count == 0
    assert artist_id not in collector.processed_mbids
    assert list(collector.queue) == [artist_id]
    assert not (tmp_path / "graph.ndjson").exists()
