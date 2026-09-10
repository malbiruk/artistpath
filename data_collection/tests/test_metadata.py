"""Tests for the metadata binary writer."""

import json
import struct
import uuid

from postprocessing.metadata import process_metadata


def _metadata_ids(path):
    data = path.read_bytes()
    _, meta_off, _, _ = struct.unpack_from("<4I", data, 0)
    (count,) = struct.unpack_from("<I", data, meta_off)
    pos, ids = meta_off + 4, []
    for _ in range(count):
        ids.append(str(uuid.UUID(bytes=data[pos : pos + 16])))
        pos += 16
        for _ in range(2):  # name, then url
            (length,) = struct.unpack_from("<H", data, pos)
            pos += 2 + length
    return ids


def test_artists_without_any_edge_are_dropped(tmp_path):
    source, target, orphan = (str(uuid.uuid4()) for _ in range(3))
    with (tmp_path / "metadata.ndjson").open("w") as f:
        for artist_id, name in [(source, "Source"), (target, "Target"), (orphan, "Orphan")]:
            f.write(json.dumps({"id": artist_id, "name": name, "url": "u"}) + "\n")

    stats = process_metadata(
        tmp_path / "metadata.ndjson", tmp_path, {source: 0}, {target: 0}, blocklist=set()
    )

    assert stats["metadata_entries"] == 2
    assert set(_metadata_ids(tmp_path / "metadata.bin")) == {source, target}
