"""Low-memory random access to the built graph via mmap.

We never load the 11 GB graph into RAM. metadata.bin carries a forward_index
(uuid -> byte offset in graph.bin) and a reverse_index (uuid -> byte offset in
rev-graph.bin); both record formats start with a u32 count we can read in place.

Record layouts (little-endian):
  graph.bin     [id 16B][u32 out_count][out_count x (id 16B + f32 weight)]
  rev-graph.bin [id 16B][u32 in_count ][in_count  x (id 16B + f32 weight)]

So in-degree(node) = the u32 at rev_offset+16, no edge scan required.
"""

import mmap
import struct
from pathlib import Path


def uuid_to_bytes(s: str) -> bytes:
    return bytes.fromhex(s.replace("-", ""))


class GraphStore:
    def __init__(self, data_dir: Path):
        self.graph_path = data_dir / "graph.bin"
        self.rev_path = data_dir / "rev-graph.bin"
        meta_bin = data_dir / "metadata.bin"

        self.fwd_index, self.rev_index = _load_indices(meta_bin)

        self._gf = self.graph_path.open("rb")
        self._rf = self.rev_path.open("rb")
        self.graph = mmap.mmap(self._gf.fileno(), 0, access=mmap.ACCESS_READ)
        self.rev = mmap.mmap(self._rf.fileno(), 0, access=mmap.ACCESS_READ)

        self._neighbor_cache: dict[bytes, frozenset[bytes]] = {}

    # -- degree ---------------------------------------------------------------

    def in_degree(self, node: bytes) -> int:
        pos = self.rev_index.get(node)
        if pos is None:
            return 0
        return struct.unpack_from("<I", self.rev, pos + 16)[0]

    def out_degree(self, node: bytes) -> int:
        pos = self.fwd_index.get(node)
        if pos is None:
            return 0
        return struct.unpack_from("<I", self.graph, pos + 16)[0]

    # -- adjacency ------------------------------------------------------------

    def out_neighbors(self, node: bytes) -> frozenset[bytes]:
        cached = self._neighbor_cache.get(node)
        if cached is not None:
            return cached
        pos = self.fwd_index.get(node)
        if pos is None:
            result: frozenset[bytes] = frozenset()
        else:
            cnt = struct.unpack_from("<I", self.graph, pos + 16)[0]
            start = pos + 20
            mm = self.graph
            result = frozenset(
                mm[start + i * 20 : start + i * 20 + 16] for i in range(cnt)
            )
        self._neighbor_cache[node] = result
        return result

    def adjacent(self, a: bytes, b: bytes) -> bool:
        """Directed-either-way adjacency: edge a->b or b->a exists."""
        return b in self.out_neighbors(a) or a in self.out_neighbors(b)

    # -- baselines ------------------------------------------------------------

    def sample_mean_out_degree(self, sample: int, seed: int = 0) -> float:
        import random

        rng = random.Random(seed)
        keys = list(self.fwd_index.keys())
        if not keys:
            return 0.0
        pick = keys if len(keys) <= sample else rng.sample(keys, sample)
        total = sum(self.out_degree(k) for k in pick)
        return total / len(pick)

    @property
    def n_nodes(self) -> int:
        # total nodes that appear anywhere as source or target
        return len(set(self.fwd_index) | set(self.rev_index))


def _load_indices(meta_bin: Path) -> tuple[dict[bytes, int], dict[bytes, int]]:
    with meta_bin.open("rb") as f:
        _lookup_off, _meta_off, fwd_off, rev_off = struct.unpack("<4I", f.read(16))
        fwd = _read_index_section(f, fwd_off)
        rev = _read_index_section(f, rev_off)
    return fwd, rev


def _read_index_section(f, offset: int) -> dict[bytes, int]:
    f.seek(offset)
    (count,) = struct.unpack("<I", f.read(4))
    raw = f.read(count * 24)
    out: dict[bytes, int] = {}
    unpack = struct.unpack_from
    for i in range(count):
        base = i * 24
        out[raw[base : base + 16]] = unpack("<Q", raw, base + 16)[0]
    return out
