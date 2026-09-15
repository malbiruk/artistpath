# Postprocessing under a duplicating graph file

The continuous sweep (`sweep-spec.md`) makes `graph.ndjson` accumulate one extra
copy of the live set per lap. Postprocessing was written when duplicates were
effectively absent, and three of its passes assume that. One of them is a
correctness bug that lands on the first rebuild after the sweep starts.

## The three growth sites

| site | consumes duplicates how | fails how | when |
|------|------------------------|-----------|------|
| `cleaning.py:214`, `cleaning.py:284` | no supersession at all | wrong blocklist, silently | immediately |
| `graph.py:96` phase 1 | `frozenset` per task | OOM mid-rebuild | ~lap 1 |
| `graph.py:248` phase 2 | same set, single-threaded | slow | ~lap 1 |

### Why cleaning is the urgent one

`compute_in_degrees` (`cleaning.py:209-225`) counts every connection on every
line. A superseded record still votes, so in-degrees inflate toward 2× per lap —
and not uniformly, because the sweep runs oldest-first, so early in a lap only
the oldest region is double-counted. `_identify_duplicates` picks which spelling
of a decoration variant to keep by comparing in-degree, so a region-correlated
skew flips exactly the comparisons it decides.

`_stream_adjacency` (`cleaning.py:274-301`, called twice) has the same problem
and a worse flavour: an edge a fresh crawl *removed* still appears in the
adjacency that feeds the translit edge gate and the collab co-occurrence gate.
Decisions get made on edges that no longer exist.

Both change **which artists are excluded from the served graph**, with no
symptom. The OOM at least fails loudly.

## Design: one shared survivor index

`_superseded_offsets` (`graph.py:61-84`) already builds `last_offset:
dict[bytes, int]` and discards it, returning only the superseded set.
`last_offset.values()` is the set of surviving offsets — the thing every pass
actually wants.

Build it once per rebuild, persist it as `.npy`, and have every pass iterate it.

**Why survivors and not superseded:** superseded offsets grow as 6.1M × laps,
unbounded. Survivors are one per artist — 6.1M, constant in laps (it tracks the
live set, which grows only by genuine discovery). That is the whole point: this
does not raise the OOM ceiling, it removes the trajectory.

- Parent holds a sorted `int64` array (~49 MB) instead of a growing Python set.
- Each chunk task carries its own slice (~500 KB) instead of ~50 MB × 96.
- `cleaning.py` runs in a separate process via `run_isolated`, so it takes the
  **path** and mmaps it. Never pickle this.
- Bytes read stops being N × 42 GB. Sorted offsets make it a forward-only sparse
  scan, not random I/O — skipped regions are large forward strides, so lost
  readahead is bytes we didn't want. Crossover is immediate at lap ≥ 1.

### Chunking

Split the survivor array by **cumulative survivor bytes**, not record count.
`data/validation/scan.log` shows edges-per-byte is near constant (bin 0: 32,348
records × 249.5 conns ≈ 8.07M edges; bin 99: 265,111 × 30.3 ≈ 8.03M), so
survivor bytes track cost while equal record counts would skew ~8×. As a lap
progresses the front of the file goes all-superseded and the tail all-live, so
equal *byte spans* would starve the front workers.

`_find_chunk_boundaries` (`graph.py:49-58`) becomes dead — remove it rather than
keeping two chunking mechanisms.

Record lengths are needed for the cumulative split. Pack them into the dict
value as `pos << 21 | len` (assert `len < 2**21`) and unpack into two numpy
arrays at the end; a `tuple` value would add ~400 MB of object overhead to a
6.1M-entry dict.

## The hazard this introduces

Today a line failing the `b'{"id": "'` prefix check at `graph.py:72-75` merely
escapes dedup — workers still emit it. **Fail-open.** Routing everything through
a survivor list makes such a line absent from `last_offset` and therefore absent
from `graph.bin` and `rev-graph.bin` entirely. **Fail-closed**, silently.

Measured: 0 of 6,149,990 live lines mismatch the prefix, so output is identical
today. But correctness would then rest permanently on the exact spacing
`json.dumps` emits in `storage.py`. Switching that writer to `orjson.dumps`
(`{"id":`, no space) would drop every record, and a partial drift would drop
records quietly under the 10% shrink gate in `check_and_refresh.sh`.

Required, not optional:

1. The scan counts non-blank prefix-mismatched lines and **hard-fails** above a
   tiny epsilon. The known glued line starts with a valid prefix, so it passes.
2. Workers return counts satisfying `emitted + json_rejects + uuid_rejects +
   blocklist_rejects == survivors_assigned`, asserted in the parent.
3. The prefix is defined **once**. `storage.py:69-84` (`GRAPH_ID_PREFIX`,
   `_extract_graph_id`) already duplicates `graph.py:72-75` and the two disagree
   — storage validates uuid shape, graph takes anything up to the next quote.
   Share one definition so the writer and its readers cannot drift apart.

## Behaviour preservation

Every rejection path stays in the worker. "No membership test" must not become
"no validation" — JSON, `_uuid_bytes` and blocklist checks all remain.

- **Torn later duplicate:** the guard at `graph.py:78-81` `continue`s before the
  `last_offset` update, so the survivor stays the earlier valid offset.
  Unchanged.
- **Torn or glued first occurrence:** enters `last_offset` unvalidated, becomes a
  survivor, the worker's `orjson.loads` fails and skips it. Identical to today.
- **uuid-invalid / blocklisted:** properties of the id, identical across copies.
- **Ordering:** ascending survivor offsets are file order, so chunk
  concatenation, `forward_ids` translation, phase 2's `n_sources` ordinals and
  `reverse_data` insertion order are all unchanged.

## Acceptance

Today's file has effectively no duplicates, so **survivors ≈ all lines and every
output must be byte-identical**. That is the gate:

1. Build all three bins with the current code.
2. Build all three bins with the new code.
3. `cmp` each pair. Any difference fails the change.

This proves the refactor is behaviour-preserving. The intended behavioural
divergence only appears once duplicates exist, which is exactly right — the
blocklist differences we are fixing cannot show up on a file that has no
superseded records to mis-count.

Run the blocklist comparison too and expect an empty delta today.

## Also

- `MemoryMax` on `ops/artistpath-refresh.service` regardless of this work. The
  rebuild runs beside the live backend and the collector; a clean unit failure
  beats the box-wide OOM reaper.
- Drop `_count_lines` (`graph.py:44-46`). It shells out to `wc -l` for a
  progress total and is another full read; `len(survivors)` is exact and free.
- `graph.py:177` transiently double-materialises the set via
  `frozenset(_superseded_offsets(...))`. Goes away with this change.

## Deliberately not doing

- **Keying `last_offset` on 16-byte uuids** (~3× smaller keys). It dominates
  parent memory after this fix at ~0.8-1.2 GB, but it is lap-constant, so it is
  not the growth problem. Needs a raw-bytes fallback for junk ids; not worth the
  risk here.
- **An incremental index** persisted between rebuilds, scanning only appended
  bytes. It is the only way rebuild time stops growing with laps, but compaction
  already bounds that. The collector must never maintain it — two writers of
  truth over irreplaceable data.
- **Fixing the uncaught `KeyError`** at `graph.py:134` when a valid-JSON line has
  no `"connections"`. Pre-existing, kills the whole rebuild, shared by both
  designs. Flagging, not touching.
- **`metadata.ndjson`** does not grow per lap — `collector.py` gates appends on
  the in-memory `names` set — so `metadata.bin` needs nothing.
