"""Tests for StreamingCollector state persistence and collection control flow."""

import asyncio
import json
import uuid

import aiohttp
import pytest
import tenacity

from collection.collector import StreamingCollector


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


def test_load_state_requeues_artists_discovered_after_the_last_save(tmp_path):
    processed, queued, discovered_later = (str(uuid.uuid4()) for _ in range(3))
    (tmp_path / "collection_state.json").write_text(
        json.dumps({"processed_mbids": [processed], "queue": [queued]})
    )
    with (tmp_path / "metadata.ndjson").open("w") as f:
        for artist_id in (processed, queued, discovered_later):
            f.write(json.dumps({"id": artist_id, "name": "x", "url": "u"}) + "\n")

    collector = StreamingCollector(output_dir=str(tmp_path))
    collector.load_state()

    assert list(collector.queue) == [queued, discovered_later]


def test_collect_graph_refreshes_oldest_records_when_frontier_is_empty(tmp_path, monkeypatch):
    artist_id = str(uuid.uuid4())
    (tmp_path / "collection_state.json").write_text(
        json.dumps({"processed_mbids": [], "queue": []})
    )
    with (tmp_path / "graph.ndjson").open("w") as f:
        f.write(json.dumps({"id": artist_id, "connections": [["x", 0.5]]}) + "\n")

    calls = []
    collector = StreamingCollector(output_dir=str(tmp_path))

    async def fake_get_similar_artists(session, mbid, limit):
        calls.append(mbid)
        return []

    monkeypatch.setattr("collection.collector.get_similar_artists", fake_get_similar_artists)

    asyncio.run(collector.collect_graph(starting_artist=None, max_artists=1, resume=True))

    assert calls == [artist_id]


def test_process_single_artist_skips_already_processed_artist_without_refresh(
    tmp_path, monkeypatch
):
    artist_id = str(uuid.uuid4())
    collector = StreamingCollector(output_dir=str(tmp_path))
    collector.processed_mbids.add(artist_id)

    calls = []

    async def fake_get_similar_artists(session, mbid, limit):
        calls.append(mbid)
        return []

    monkeypatch.setattr("collection.collector.get_similar_artists", fake_get_similar_artists)

    async def run():
        async with aiohttp.ClientSession() as session:
            return await collector.process_single_artist(session, artist_id, 80)

    asyncio.run(run())

    assert calls == []


def test_process_single_artist_recrawls_already_processed_artist_when_refreshing(
    tmp_path, monkeypatch
):
    artist_id = str(uuid.uuid4())
    collector = StreamingCollector(output_dir=str(tmp_path))
    collector.processed_mbids.add(artist_id)

    calls = []

    async def fake_get_similar_artists(session, mbid, limit):
        calls.append(mbid)
        return []

    monkeypatch.setattr("collection.collector.get_similar_artists", fake_get_similar_artists)

    async def run():
        async with aiohttp.ClientSession() as session:
            return await collector.process_single_artist(session, artist_id, 80, refresh=True)

    asyncio.run(run())

    assert calls == [artist_id]


def test_process_single_artist_refresh_with_no_results_leaves_existing_record_intact(
    tmp_path, monkeypatch
):
    artist_id = str(uuid.uuid4())
    graph_path = tmp_path / "graph.ndjson"
    original_line = json.dumps({"id": artist_id, "connections": [["other-id", 0.9]]}) + "\n"
    graph_path.write_text(original_line)

    collector = StreamingCollector(output_dir=str(tmp_path))
    collector.processed_mbids.add(artist_id)

    async def fake_get_similar_artists(session, mbid, limit):
        return []

    monkeypatch.setattr("collection.collector.get_similar_artists", fake_get_similar_artists)

    async def run():
        async with aiohttp.ClientSession() as session:
            return await collector.process_single_artist(session, artist_id, 80, refresh=True)

    asyncio.run(run())

    assert graph_path.read_text() == original_line


def test_process_single_artist_refresh_puts_new_discoveries_on_the_bfs_queue(
    tmp_path, monkeypatch
):
    artist_id = str(uuid.uuid4())
    new_id = str(uuid.uuid4())
    collector = StreamingCollector(output_dir=str(tmp_path))
    collector.processed_mbids.add(artist_id)

    async def fake_get_similar_artists(session, mbid, limit):
        return [{"mbid": new_id, "name": "New Artist", "url": "u", "match": 0.8}]

    monkeypatch.setattr("collection.collector.get_similar_artists", fake_get_similar_artists)

    async def run():
        async with aiohttp.ClientSession() as session:
            return await collector.process_single_artist(session, artist_id, 80, refresh=True)

    asyncio.run(run())

    assert new_id in collector.queue
    assert new_id not in collector.refresh_queue


def test_process_single_artist_refresh_requeues_on_retry_error_without_discarding(
    tmp_path, monkeypatch
):
    artist_id = str(uuid.uuid4())
    collector = StreamingCollector(output_dir=str(tmp_path))

    async def raising_get_similar_artists(session, mbid, limit):
        raise tenacity.RetryError(tenacity.Future.construct(1, ValueError("boom"), True))

    monkeypatch.setattr(
        "collection.collector.get_similar_artists", raising_get_similar_artists
    )

    async def run():
        async with aiohttp.ClientSession() as session:
            return await collector.process_single_artist(session, artist_id, 80, refresh=True)

    asyncio.run(run())

    assert artist_id in collector.processed_mbids
    assert list(collector.refresh_queue) == [artist_id]


def test_process_single_artist_increments_crawled_total_when_a_record_is_appended(
    tmp_path, monkeypatch
):
    artist_id = str(uuid.uuid4())
    similar_id = str(uuid.uuid4())
    collector = StreamingCollector(output_dir=str(tmp_path))

    async def fake_get_similar_artists(session, mbid, limit):
        return [{"mbid": similar_id, "name": "Similar", "url": "u", "match": 0.5}]

    monkeypatch.setattr("collection.collector.get_similar_artists", fake_get_similar_artists)

    async def run():
        async with aiohttp.ClientSession() as session:
            return await collector.process_single_artist(session, artist_id, 80)

    asyncio.run(run())

    assert collector.crawled_total == 1


def test_process_single_artist_leaves_crawled_total_unchanged_with_no_connections(
    tmp_path, monkeypatch
):
    artist_id = str(uuid.uuid4())
    collector = StreamingCollector(output_dir=str(tmp_path))

    async def fake_get_similar_artists(session, mbid, limit):
        return []

    monkeypatch.setattr("collection.collector.get_similar_artists", fake_get_similar_artists)

    async def run():
        async with aiohttp.ClientSession() as session:
            return await collector.process_single_artist(session, artist_id, 80)

    asyncio.run(run())

    assert collector.crawled_total == 0


def test_save_and_load_state_round_trips_refresh_fields(tmp_path):
    collector = StreamingCollector(output_dir=str(tmp_path))
    collector.refresh_queue.extend(["r1", "r2"])
    collector.refresh_offset = 123
    collector.crawled_total = 45
    collector.save_state()

    reloaded = StreamingCollector(output_dir=str(tmp_path))
    reloaded.load_state()

    assert list(reloaded.refresh_queue) == ["r1", "r2"]
    assert reloaded.refresh_offset == 123
    assert reloaded.crawled_total == 45


def test_load_state_seeds_crawled_total_from_processed_count_when_missing(tmp_path):
    processed = [str(uuid.uuid4()) for _ in range(3)]
    (tmp_path / "collection_state.json").write_text(
        json.dumps({"processed_mbids": processed, "queue": []})
    )

    collector = StreamingCollector(output_dir=str(tmp_path))
    collector.load_state()

    assert collector.crawled_total == 3


def test_collect_graph_aborts_with_runtime_error_after_max_consecutive_failures(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("collection.collector.MAX_CONSECUTIVE_FAILURES", 2)
    artist_ids = [str(uuid.uuid4()) for _ in range(5)]
    (tmp_path / "collection_state.json").write_text(
        json.dumps({"processed_mbids": [], "queue": artist_ids})
    )

    collector = StreamingCollector(output_dir=str(tmp_path))

    async def always_raising_get_similar_artists(session, mbid, limit):
        raise tenacity.RetryError(tenacity.Future.construct(1, ValueError("boom"), True))

    monkeypatch.setattr(
        "collection.collector.get_similar_artists", always_raising_get_similar_artists
    )

    with pytest.raises(RuntimeError):
        asyncio.run(collector.collect_graph(starting_artist=None, batch_size=1, resume=True))

    # State was saved before the abort, so a restart doesn't lose the re-queued artists.
    saved_state = json.loads((tmp_path / "collection_state.json").read_text())
    assert set(saved_state["queue"]) == set(artist_ids)


def test_intermittent_failures_do_not_trip_the_circuit_breaker(tmp_path, monkeypatch):
    monkeypatch.setattr("collection.collector.MAX_CONSECUTIVE_FAILURES", 2)
    artist_ids = [str(uuid.uuid4()) for _ in range(6)]
    (tmp_path / "collection_state.json").write_text(
        json.dumps({"processed_mbids": [], "queue": artist_ids})
    )

    collector = StreamingCollector(output_dir=str(tmp_path))
    call_count = 0

    async def alternating_get_similar_artists(session, mbid, limit):
        nonlocal call_count
        call_count += 1
        if call_count % 2 == 1:
            raise tenacity.RetryError(tenacity.Future.construct(1, ValueError("boom"), True))
        return []

    monkeypatch.setattr(
        "collection.collector.get_similar_artists", alternating_get_similar_artists
    )

    # Every other call fails (3 failures total, above the threshold) but each is
    # immediately followed by a success, so the streak never reaches the limit.
    asyncio.run(
        collector.collect_graph(
            starting_artist=None, batch_size=1, max_artists=6, resume=True
        )
    )

    assert call_count == 6


def test_collect_graph_fills_a_batch_from_both_queues(tmp_path, monkeypatch):
    frontier_id = str(uuid.uuid4())
    sweep_ids = [str(uuid.uuid4()) for _ in range(9)]
    (tmp_path / "collection_state.json").write_text(
        json.dumps(
            {
                "processed_mbids": sweep_ids,  # sweep artists were already crawled once
                "queue": [frontier_id],
                "refresh_queue": sweep_ids,
                "refresh_offset": 0,
            }
        )
    )

    collector = StreamingCollector(output_dir=str(tmp_path))
    calls = []
    in_flight = 0
    max_in_flight = 0

    async def fake_get_similar_artists(session, mbid, limit):
        nonlocal in_flight, max_in_flight
        calls.append(mbid)
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        collector.request_stop()  # stop after this (the only) batch completes
        await asyncio.sleep(0)  # yield so batchmates overlap instead of running serially
        in_flight -= 1
        return []

    monkeypatch.setattr("collection.collector.get_similar_artists", fake_get_similar_artists)

    asyncio.run(collector.collect_graph(starting_artist=None, batch_size=10, resume=True))

    # One batch of 10: the frontier artist plus sweep artists already processed.
    assert max_in_flight == 10
    assert set(calls) == {frontier_id, *sweep_ids}


def test_refill_refresh_queue_retries_from_start_when_cursor_is_parked_in_a_torn_tail(
    tmp_path,
):
    graph_path = tmp_path / "graph.ndjson"
    complete_id = str(uuid.uuid4())
    complete_line = json.dumps({"id": complete_id, "connections": []}) + "\n"
    torn_tail = json.dumps({"id": str(uuid.uuid4()), "connections": []})  # no newline yet
    graph_path.write_text(complete_line + torn_tail)

    collector = StreamingCollector(output_dir=str(tmp_path))
    collector.refresh_offset = len(complete_line.encode())  # cursor parked in the torn tail

    found_more = collector.refill_refresh_queue()

    assert found_more
    assert list(collector.refresh_queue) == [complete_id]
