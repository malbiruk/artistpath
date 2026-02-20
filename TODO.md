# Performance TODOs

## P0 — Will break at scale

### Search is O(n) linear scan
`web/backend/src/search.rs:34` — `filter_artists_by_query` iterates every key in `name_lookup` HashMap doing `.contains()` on each. At 850k artists this already causes 504 timeouts via the Cloudflare Worker. At 7M it will be completely unusable.

**Fix:** Build a prefix/trigram index at startup, or use a sorted Vec with binary search for prefix queries. Substring matching could use an inverted index of n-grams.

### Pathfinding is slow on HDD (not an algorithm issue)
`core/src/pathfinding/bfs/state.rs:57` — The BFS loop has no visited-node limit, which is correct by design (a cap would miss valid paths). The slowness on the current server is purely due to HDD random reads on mmap'd graph files (~8ms per node visit). On hardware with NVMe SSD + sufficient RAM for page cache, the same queries run in milliseconds.

**Not a code fix** — resolved by moving to proper hardware (SSD + RAM). If a timeout is ever needed for safety (e.g. to avoid runaway queries on degraded hardware), a wall-clock timeout returning "search timed out, try different parameters" would be preferable to a node cap.

## P1 — Worth fixing

### Blocking CPU work on async runtime
`web/backend/src/handlers.rs:44,98` — Pathfinding and exploration run synchronously inside `async fn` handlers on the tokio runtime. A long BFS blocks a worker thread, stalling all other requests queued on that thread (including trivial ones like `/stats`).

**Fix:** Wrap heavy compute in `tokio::task::spawn_blocking(move || { ... }).await`.

### `get_random_artist` is O(n)
`web/backend/src/handlers.rs:156` — `.iter().nth(random_index)` on a HashMap walks the entire internal structure up to index `n`. At 7M artists this scans millions of buckets per call.

**Fix:** Keep a `Vec<Uuid>` of all artist IDs at startup, pick a random index in O(1).

## P2 — Minor

### Edge dedup in neighborhood is O(n²)
`core/src/pathfinding/bfs/neighborhood.rs:179` — `edges.iter().any(|edge| ...)` checks all existing edges for each new edge. With hundreds of edges this is fine, but could use a HashSet if edge counts grow.
