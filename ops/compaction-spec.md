# Compaction

`graph.ndjson` is append-only, so a re-crawled artist leaves its old record in
place. One sweep lap therefore writes a second copy of the live set — measured
at 8.4 GB/day, ~42 GB/lap. Nothing else grows: the survivor index made rebuild
time and memory constant in laps, so disk is the only reason this exists.

Compaction rewrites the file keeping only each artist's last record.

## Why it is not part of postprocessing

A rebuild takes ~27 minutes and the collector appends throughout — deliberately,
since postprocessing only reads. So the survivor index built in Step 0a is
already stale when that run ends, and any record appended during the rebuild is
absent from it.

**Compaction driven by that index would delete those records.** It must build
its own index with the collector stopped, which removes the only efficiency
argument for coupling the two. Keeping postprocessing read-only also means
running it by hand never stops the collector as a side effect.

## Trigger

Runs as the **last** step of `check_and_refresh.sh`, after the report deploys,
when `size(graph.ndjson) > COMPACT_RATIO × live_bytes`.

`live_bytes` is the sum of survivor record lengths — exactly what the file would
shrink to. `run_postprocessing.py` already builds the index every rebuild, so it
persists that sum to `data/live_bytes.txt`. Written next to `graph.ndjson`, not
into `--out-dir`, because it describes the input and the out-dir is a staging
directory that gets deleted.

`COMPACT_RATIO = 1.5`. The binding constraint is that compaction must always
fit: it holds both files at once, so it needs `live_bytes` free. A higher ratio
means a bigger file and less free space at exactly the moment more is needed.
1.5 caps the file at ~63 GB and triggers every ~2.5 days at the current rate,
costing ~2 minutes and a 42 GB write each time.

Running last matters: the bins are already swapped and verified by then, so a
compaction failure exits non-zero into the existing `/fail` ping without
endangering a successful refresh. No separate healthcheck — a conditional step
cannot be modelled by a period-based check, which would alarm every night it
correctly skipped.

## Procedure

1. **Stop the collector** and wait for it to exit. It finishes its batch and
   saves state (`TimeoutStopSec=300`). Nothing may append past this point.
2. **Build a fresh survivor index** against the file as it now stands.
3. **Pre-flight**: require free space > `live_bytes` plus a margin. This is
   exact, not an estimate — the index knows the answer.
4. **Write `graph.ndjson.new`**, walking the index in ascending offset order and
   copying each survivor's line.
5. **Verify** before anything destructive (see below).
6. **Re-assert nothing appended** — collector still stopped, file still its
   original size. Run this *before* the cursor reset as well as immediately
   before the rename: a refusal here means a collector is running, and the
   reset read-modify-writes a 286 MB state file, so a save landing between the
   read and the replace would be clobbered whole — `queue` and `crawled_total`
   included, not just the cursor.
7. **Reset `refresh_offset` to 0** in `collection_state.json` — *before* the
   rename, so an interruption leaves a valid cursor on the intact old file.
8. **`os.replace()`** the new file over `graph.ndjson`, keeping the previous one
   as `graph.ndjson.old` until the collector is back.
9. **Restart the collector**, in a trap so it comes back even on failure.

### Why ascending offset order

A survivor's offset is the position of that artist's *most recent* record, so
sorting survivors by offset sorts artists by when they were last crawled.
Emitting them in that order keeps the compacted file oldest-first, which is what
makes resetting the cursor to 0 correct rather than merely convenient. It also
turns the read into a forward sparse scan instead of random I/O.

## Verification

Three checks on the output, all before the rename:

- `size(graph.ndjson.new) == live_bytes` — exact, from the index.
- Re-indexing the new file yields the same survivor count.
- That re-index sees `non_blank == survivor count`, i.e. **no id survives
  twice**. This is the actual proof that supersession was applied.

Together these are strong, because records are copied verbatim: compaction
cannot corrupt a record, only omit one. A wrong length either truncates a
survivor so the next record glues onto it (line count drops, check 2 fails) or
injects a newline that splits a record (extra non-blank line, check 3 fails).
The second fragment cannot disguise itself, because `{"id": "` never occurs
mid-record — connections are arrays, not objects.

**But all three look only at the output.** They never re-read the original, so
they are structurally blind to the file changing underneath. That is the one
way compaction can lose data unseen, so two input-side guards close it:

- **Size freeze.** Immediately before the rename, re-assert the collector is
  stopped and that `graph.ndjson` is exactly the size it was when the index was
  built. Append-only makes size a complete test, not a heuristic. Without this,
  a collector started by hand during the write silently drops that window's
  records.
- **Count continuity.** Each rebuild records its survivor count next to
  `live_bytes`. Compaction requires its own fresh count to be at least that:
  artists are only ever added, so the count only grows, and a shortfall means
  two independent runs disagree about the file. This is cross-code-path
  validation *before* the rename rather than a shrink gate a day later that
  cannot see a loss under 10%.

### What is not preserved

Lines that fail the `{"id": "` prefix check are dropped, tolerated up to the
same one-in-a-million epsilon the index already enforces (≤ ~6 per run at
current size). Every reader in the system — postprocessing, the sweep, the
compactor — already cannot read those lines, so nothing observable is lost. The
honest invariant is **nothing readable is ever lost**, not that nothing is lost.
Readable-but-garbled lines, including the file's one glued line, are carried
through verbatim.

## Failure modes

| when | state | recovery |
|------|-------|----------|
| during index build | nothing written | delete nothing, restart collector |
| during write | `.new` partial, original intact | delete `.new` |
| hard kill mid-write | `.new` orphaned, tens of GB | `check_and_refresh.sh` deletes it at start — it must, or the next rebuild's `MIN_FREE_GB` gate exits the script before reaching any cleanup |
| after cursor reset, before rename | cursor 0, old file intact | sweep re-laps from the front; wasteful, harmless |
| after rename | `.old` holds the previous file | dropped once the collector is back |
| collector fails to restart | file fine | trap restarts it; refresh pings `/fail` |

`.old` is deleted in the same run rather than held for the next rebuild. It is a
hardlink, so it shares blocks with the pre-compaction file and insures against a
compaction logic bug and nothing else — not media corruption, and not anything
the sweep would not itself repair by re-crawling every record every ~6 days.
Held overnight it costs ~60 GB at exactly the moment the next rebuild needs
`MIN_FREE_GB=40` to start, leaving single-digit GB of slack; anything else on
the box taking that would deadlock the two against each other permanently. The
size-freeze and count-continuity guards above are what replace it.

`FREE_MARGIN` is therefore 10 GB, not 40: it only has to keep the box off zero
for the minutes both files exist.

## Not doing

- **Per-record deletion.** No filesystem operation removes bytes from the middle
  of a file and closes the gap. `fallocate --collapse-range` does, and btrfs
  does not support it; rewriting the tail per deletion is compaction performed
  6.1M times.
- **`fallocate --punch-hole`.** Supported, and it preserves byte offsets so the
  cursor and index would survive — but it is block-granular, so a ~6.8 KB record
  at an arbitrary offset gives back roughly half its space and sometimes none;
  it leaves NUL runs that read as corrupt lines and would blow through the
  prefix-mismatch guard; and it requires the collector to hold a 6.1M-entry
  id → offset map, making it a second writer of truth and giving the one process
  that currently *cannot* destroy data the ability to blank arbitrary ranges.
