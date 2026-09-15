# Continuous oldest-first refresh

The collector ran until the BFS frontier emptied, then exited. This makes it
never exit: when there is nothing new to discover, it re-crawls the oldest
records in `graph.ndjson` instead, and anything new those turn up goes back
into the ordinary BFS frontier.

## Why oldest-first

Measured on 1250 sampled records across five equal-byte slices of
`graph.ndjson` (`data/validation/discovery_probe.json`):

| slice | stored | added | removed | new artists | churn |
|-------|--------|-------|---------|-------------|-------|
| 0 (oldest) | 234.8 | 49.3 | 50.2 | 0.168 | 31.8% |
| 1 | 216.2 | 37.5 | 42.2 | 0.108 | 32.2% |
| 2 | 202.8 | 31.5 | 32.4 | 0.092 | 27% |
| 3 | 176.7 | 15.3 | 16.0 | 0.092 | 17% |
| 4 (newest) | 118.8 | 6.1 | 5.8 | 0.052 | 9% |

Churn is **age-driven, not density-driven**: slices 0 and 1 churn identically
(31.8 / 32.2%) despite different edge density, and the gradient is monotonic in
age. It is also scale-invariant — the same ordering holds at match thresholds
0.0 → 0.5 and at top-K 10 → 100. A 3-day-old record still churns ~8.7%, which
is the irreducible floor (Last.fm's own recomputation).

So byte offset in an append-only file is a sufficient staleness proxy, and
sweeping from offset 0 forward targets the most-changed records first.

Discovery is a side effect, not the goal: ~0.0975 new artists per re-crawl,
and the coverage gap against chart/tag/geo listings is only ~1.4%. There is no
large undiscovered component left; the value here is edge freshness.

## Mechanism

One byte cursor, `refresh_offset`, stored in `collection_state.json`.

1. BFS frontier non-empty → crawl it (discovery has priority).
2. Frontier empty, refresh queue empty → read forward from `refresh_offset`,
   collect the next `REFRESH_CHUNK` distinct ids, advance the cursor past the
   bytes consumed.
3. Crawl those ids with the processed-check bypassed. New records append at the
   tail and supersede the old ones at postprocessing time (last-record-wins,
   unchanged). Newly discovered artists land in the BFS frontier as always.
4. Cursor at or past EOF → reset to 0 and start the next lap.

### The cursor is self-balancing

Each refresh crawl consumes one record's bytes at the cursor and appends one
record at the tail, so `filesize - refresh_offset` stays at roughly the live-set
size. The cursor trails the tail by exactly one lap of history, forever. It
never catches up and never falls behind.

Resetting on `offset >= filesize` covers both real cases: caught up (front of
the file is genuinely the oldest) and post-compaction (file shrank below the
cursor).

## Invariants

- **Nothing is ever deleted or rewritten.** `graph.ndjson` stays strictly
  append-only, exactly as today.
- **The cursor advances on bytes read, not on records written.** A re-crawl
  that returns nothing appends nothing, so a blank result leaves the existing
  record standing — no tombstones, and a 250-edge record is never superseded by
  an empty one.
- **A thin result is not covered by that, and does supersede.** 2.88% of
  re-crawls come back with under half the stored edges. Those *are* appended,
  and postprocessing drops the richer original from the served bins with no size
  comparison; the 10% whole-file shrink gate in `check_and_refresh.sh` is far
  too coarse to catch it. The old bytes survive in the file, and the probe shows
  added ≈ removed, so this is per-record variance that self-heals on the next
  lap rather than erosion — but it is tolerated, not prevented.
- **A corrupt or glued line is skipped on every lap, not just one.** Nothing is
  destructive, so a mis-parsed line can never destroy a record, but the buried
  id stays invisible until a compaction rewrites the line. The live file
  contains at least one — a truncated record with a complete 250-edge record
  concatenated onto it.
- **A persistent API failure fails the unit.** With no queue-empty exit left, a
  revoked key (403 forever) would re-queue every artist indefinitely while
  still saving state every 600s, so a wedged crawl would keep the healthcheck
  green. 100 consecutive failures aborts the run and lets systemd back off.
- **Restart-safe.** Cursor and refresh queue are saved together with the
  processed set; a crash re-crawls at most one save interval of work, which is
  idempotent.

## Rebuild trigger

`check_and_refresh.sh` gates on `len(processed_mbids)`, which measures
*discovery*. Under a refresh sweep that grows ~0.1 per crawl, so the served
bins would rebuild roughly every fifth day while ~30% of the swept edges
changed.

Replaced with `crawled_total` — graph records appended — which counts refresh
work. Initialised from `len(processed_mbids)` on first load so it stays
continuous with the existing `last_refresh_count.txt`.

## Not built: compaction

Each lap re-appends the live set, so `graph.ndjson` grows by roughly its own
live size per lap (~42 GB). Two consequences, both gradual:

- **Disk.** 107 GB free today. `check_and_refresh.sh` already fails loudly at
  `MIN_FREE_GB=40`, so there is ~67 GB of headroom and an existing alarm. At a
  sustained 200k crawls/day that is ~50 days.
- **Postprocessing time.** Linear in file bytes, so 27 min becomes ~54 min at
  2× the file size.
- **Postprocessing memory — the binding constraint, and it lands first.**
  `_superseded_offsets` returns almost nothing today because there are almost
  no duplicates. One lap makes it ~6.3M offsets, and `postprocessing/graph.py`
  pickles that set into each of 96 chunk tasks with 24 workers holding live
  copies — several GB by lap 1, growing linearly. Unlike `MIN_FREE_GB` this
  fails as an OOM inside the rebuild rather than a clean refusal, and
  `artistpath-refresh.service` sets no `MemoryMax`.

Compaction is therefore a periodic offline chore, not part of this loop: stop
the collector, full keep-last rewrite emitting survivors in ascending
last-offset order, verify, rename, reset `refresh_offset` to 0. Emitting in
last-offset order is what makes offset 0 mean "oldest" again afterwards.

It must JSON-validate every line and confirm the parsed `id` matches the
prefix-extracted one, and halt rather than skip on a mismatch — that is the
glued-line hazard, and it is only a hazard for a destructive pass.

**The runbook must stop `artistpath-refresh.timer`, not just the collector.** A
rebuild that starts mid-compaction reads a survivor index built against the old
file, so every offset points into the swapped one. `_process_forward_chunk`
raises on the first offset that does not start a record, but do not rely on
that alone — mask the timer for the duration.

## Healthcheck semantics change

The collector check pings only when `collection_state.json` was touched in the
last 30 minutes, so "red" used to mean the crawl finished. The crawl no longer
finishes. Red now means the collector died or wedged — the ordinary meaning.
