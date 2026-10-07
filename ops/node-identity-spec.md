# Node identity: when to drop a duplicate and when to merge it

Cleaning has exactly one primitive — remove a node — and its docstring states
the invariant plainly: *"Nothing is merged and no edges are rewritten."* That
is the right primitive for noise. Three of the four duplicate classes in the
dataset are not noise: they are one artist holding two nodes, and for those,
removal silently discards every edge that pointed at the loser.

A fourth class (below) is new, is unambiguously our own bug, and is what
surfaced this.

## The asymmetry removal ignores

Two nodes for one artist have **duplicate out-edges and disjoint in-edges**.
Out-edges come from crawling, and both nodes crawl the same thing. In-edges
come from whoever cited them, and each citer picked one node or the other.

Measured on the live graph for Lana Del Rey:

| | MBID node | synthesised twin | both |
|---|---|---|---|
| in-edges | 245 | 29 | **0** |

Dropping the twin does not deduplicate those 29. It deletes them.

## The four classes

| class | what splits the node | same Last.fm page? | out-edges | primitive |
|---|---|---|---|---|
| **URL twin** | our `mbid or uuid5(url)` rule | **yes** | agree on 914/979, bimodally | **remap, gated** |
| decoration variant | `♪Lana Del Rey` is its own page | no | differ | open |
| translit variant | Cyrillic original vs romanization | no | differ | open |
| collab credit | not an artist at all | n/a | n/a | remove |

### The line that separates them

**Whose claim is the edge?**

- **URL twin.** Last.fm said "X is similar to the artist at
  `last.fm/music/Lana+Del+Rey`". Both ids *are* that page. The split is
  manufactured entirely by `collector.py:133` and `collector.py:232`
  (`mbid` when Last.fm supplies one, `uuid5(NAMESPACE_URL, url)` when it does
  not — and Last.fm omits the mbid inconsistently between listings of the same
  artist). A remap here **restores the edge Last.fm actually sent**. It carries
  zero editorial content, and blocklisting is the option that departs from
  Last.fm's data.

- **Decoration / translit variant.** Last.fm said "X is similar to the artist at
  `last.fm/music/♪Lana+Del+Rey`" — a real, distinct Last.fm page with its own
  similar-artists list. Remapping it asserts `♪Lana Del Rey ≡ Lana Del Rey`.
  That is *our* judgement, not Last.fm's. Defensible curation, but a different
  kind of claim, and it is the actual question this spec exists to put on the
  table: **does artistpath serve Last.fm's graph, or a curated artist graph?**

Collabs stay removals under either answer. A credit node is not an artist, and
redistributing its edges to its members would invent edges outright.

## Class 1: URL twins

Population, from a full scan of `metadata.ndjson` (6,544,605 records,
6,542,048 distinct URLs), counting **distinct** ids per URL:

| shape | URLs | disposition |
|---|---|---|
| exactly one MBID + its `uuid5(url)` twin | **985** | remap the twin onto the MBID |
| two or more MBIDs | 108 | **never merge** — see below (111 URLs hold >=2 MBIDs; 108 have exactly 2 ids and no twin) |
| 3–4 ids, mixed | 3 | excluded by the lone-MBID rule |

All 985 synthetic ids are exactly `uuid5(NAMESPACE_URL, url)` — no near-misses.

**Why a URL with two MBIDs must not be merged.** Last.fm's URL is name-derived,
so two MusicBrainz entities sharing a name share a page — but `artist.getsimilar`
by mbid returns genuinely different lists for each:

| name | MBID A returns | MBID B returns |
|---|---|---|
| Selena | Gloria Trevi, Kumbia Kings | Thea Devy, Julia Steen |
| Nelly | Sorley, Calle Lebraun | Ja Rule, Ludacris, Chingy |
| David Allan Coe | Hank Williams Jr., Waylon Jennings | sandrom, Franky Klassen |

Merging those fuses two artists. This is the same reasoning
`cleaning._lone_mbid` already applies to names, and it is why **URL alone is
not a safe identity key** — only "URL with exactly one MBID" is.

**Cost of getting it wrong by blocklisting instead.** Across a 60-pair sample,
2,832 of 14,163 in-edges (20%) would be deleted; extrapolated to all 985 pairs,
~46k edges **gross** — before cleaning, which removes ~25% of nodes, so some of
those sources never reach the binary. Net recovery is unmeasured. In 8 of 60 pairs the synthesised node is the *more*-connected of the
two, so blocklisting deletes the better-connected node to keep the better-named
one. On credit-shaped sources the twin's citers are 14.8% against the MBID node's
8.2% — **1.8x enriched, not cleaner**. The claim is only that 85% of them are
still ordinary artists (Lucha Villa, Patrick Hernandez), which is a far weaker
statement than "not the junk cluster" and is not by itself the reason to remap.
The reason is that the two nodes are one Last.fm page.

**Gate: Jaccard of out-edge sets >= 0.5.** Both ids name one page, so a crawl
of either returns that page's similar-artists list. Exact set equality does not
work: the two sides are crawled at different times, so drift alone separates
them. Measured over all 985 pairs from `graph.ndjson` (surviving records only):

| out-edge agreement | pairs | reading |
|---|---|---|
| identical | 442 | same page |
| Jaccard 0.9-1.0 | 420 | same page, crawl drift |
| 0.8-0.9 | 38 | same page, more drift |
| **0.3-0.8** | **26** | the valley the threshold sits in |
| below 0.5 | 65 | **different entities — reject** |

The distribution is bimodal with only 26 pairs across the whole 0.3-0.8 band, so
a threshold at 0.5 has margin on both sides. That margin is the point: which
side of an *exact-equality* gate a pair falls on is decided by when each side was
last re-crawled, so nightly rebuilds would merge a pair, un-merge it next lap and
re-merge it later — churning node ids in the served data for reasons that have
nothing to do with identity. A Jaccard threshold in a sparse valley does not
churn; exact equality would also have rejected 537 of the 979 pairs this exists
to fix.

**Both sides almost always own a record: 979 of 985** (5 neither, 1 MBID-only,
**0 twin-only**). The collector crawls a synthesised id by name
(`collector.fetch_similar_artists`), so the twin is a crawled node, not a bare
edge target. This makes the gate mandatory rather than an escape hatch, and it
means blocklisting the twin discards a real out-edge set every time.

**On MusicBrainz conflation pages.** The lone-MBID guard tests "one MBID
*observed so far*", not identity, so a Last.fm page that conflates two entities
(`John Williams`, `Fergie`) is a stated risk. The gate answers it empirically:
both of those pairs come back at Jaccard **1.000** — byte-identical similar-artist
lists. The graph holds no information separating them, so keeping them split
ships two identical nodes rather than preserving a distinction. Whether Last.fm
conflates the composer and the guitarist is a Last.fm data-quality question that
exists with or without our id split.

**Self-loops are a signal, not a rule.** 98 pairs have one member citing the
other, and they are ~6x enriched below the threshold (30 of 65 rejected pairs
vs 68 of 914 accepted). Enriched, but not separating — rejecting on self-loop
alone would throw out 68 good pairs. The Jaccard gate already subsumes it.

## Classes 2 and 3: decided — keep deleting

The question is whether to redirect a decoration/translit variant's in-edges to
the canonical node instead of dropping them. **No.** The deciding evidence is
who cites the loser.

| | citers of the loser | against baseline |
|---|---|---|
| URL twin | 14.8% credit-shaped; the rest are artists (Lucha Villa, Patrick Hernandez) | ordinary population |
| decoration variant | MBID-keyed sources are **under 5%** of what points at a decorated spelling | **23.5% of all out-edges — ~4.7x depleted** |

That depletion is the scrobble-artifact cluster, and it is the finding `dd06be3`
rests on. Deleting a decorated spelling is what makes the cluster stop
mattering. Remapping would take the 5,056 in-edges Pink Floyd currently
discards and reattach them to Pink Floyd — re-admitting the exact population
that commit removed.

**And the junk citers survive cleaning**, which is what makes this bite rather
than wash out. `[HD] Pink Floyd` has skeleton `hd pink floyd`, which does not
match `pink floyd`, and does not decompose into two known artists. Nothing
blocklists it. Those edges would not vanish with their sources — they would
land on the canonical node.

**No gate is available.** Class 1 confirms on out-edge agreement, which is
evidence from the graph. Classes 2 and 3 are *by construction* different pages
with different out-edges, so no equivalent check exists; they would rest on the
name rule alone — exactly what failed when in-degree handed "Pink Floyd" to
"♫ Pink Floyd". Deletion's failure mode is a lost edge. Remap's is pollution
that propagates into pathfinding. Under an ungateable rule, take the milder
failure.

`dd06be3`'s "19% of the graph" is a share of *nodes*; the comparable baseline is
the MBID-keyed share of *edge sources*, sampled at **23.5% of out-edges** (18.5%
of record owners, 13.9% of all metadata ids). Using the right baseline makes the
depletion larger, not smaller, so the conclusion holds — but the ratio must be
quoted against 23.5%, not 19%.

**What would overturn this.** One measurement, costing a full cleaning run plus
one extra graph pass: of the in-edges pointing at decoration variants, the
fraction whose source both survives cleaning *and* is a real artist rather than
a scrobble artifact. Non-MBID is not synonymous with junk. If that fraction came
back high, the loss would be real and this decision should flip.

## Mechanics any remap needs

Order matters: **remap first, then apply the blocklist mask.** Reversed, edges
to a remap source get deleted before they can be redirected.

**Invariant: no remap target may be blocklisted.** "Remap first" is necessary
but not sufficient — if target T is blocklisted, every edge remapped onto it
dies at `graph.py:225`, including the twin in-edges this change exists to keep,
turning the fix into a silent deletion. This is reachable: any rule (a
sentinel, the duplicate fallback, a translit representative, a collab) can drop
the MBID node itself. `run_postprocessing` removes such pairs from the remap and
keeps their twin blocklisted, so the artist goes with its MBID node rather than
having edges redirected onto a node that won't ship, and logs how many.
`process_graph` raises `ValueError` if a remap source is not blocklisted or a
target is, so a direct caller cannot ship the quiet loss.

**The record owner is never remapped — only edge targets.** Remapping
`data["id"]` would make `forward_index[artist_id]` (`graph.py:318`) keep one of
two records for T while `graph.bin` carries the other unreferenced, and would
mint two source ordinals for one uuid in the reverse pass
(`graph.py:375-377`). The twin's own record is dropped by the blocklist, not
rewritten.

**In-degrees must be folded before they are voted on.** `identify_cleaning_uuids`
runs at `run_postprocessing.py:97`, before `process_graph` at `:114`, and every
in-degree-driven decision (`cleaning.py:324` duplicate fallback, `:403`/`:431`
translit rep, `:536-537` collab centrality) would count the twin's in-edges
against the twin while the shipped graph assigns them to the MBID. A decorated
spelling beating the MBID pre-remap but not post-remap flips a blocklist
decision. Fix needs no extra pass: after the gate confirms, move `indeg[twin]`
into `indeg[mbid]` and rewrite the `_stream_adjacency` maps through the alias
table — both are O(aliases) fold-ups over data already in memory. It slightly
over-counts where one source cites both members (15 of 1,959 sampled records),
which is the same overlap the dedup below collapses.

- Applied in `_process_forward_chunk` (before `graph.py:225`) and again in the
  sequential reverse pass (`graph.py:372-384`). The reverse graph is built from
  the NDJSON, not from the forward output, so it cannot inherit the transform.
  **One shared helper, called twice** — two spellings of one rule is how
  forward and reverse drift. The table is a few thousand entries, so it is a
  plain `{twin: mbid}` dict handed to each worker; an empty table returns edges
  unchanged.

**Self-loops and duplicate out-edges already exist and are kept today** — of
1,959 pair-member records, 66 cite themselves and 10 already carry duplicate
out-edges. So the policy must be explicit: in a record that cites a twin,
**drop the self-loops the remap created and collapse every edge to that twin's
MBID node** (redirected ones and any the record already had) into one edge at
the first one's position. Edges to every other target, including existing
self-loops and duplicates, are untouched, and a record citing no twin passes
through as is. Applying it globally would change edges unrelated to this fix
and break the empty-table equivalence run below.

- Dedup rule for edges collapsed onto an MBID node: keep `max` weight. This is the
  **one number the remap invents** — it is the only choice that cannot lower an
  edge Last.fm reported, but it is fabricated either way and is the sole
  editorial act in class 1.

## Verification

- **Empty remap table must reproduce the current binaries byte-for-byte**, with
  both runs pinned to the same `survivors.npy` — `graph.ndjson` is appended to
  continuously, so an unpinned "diff against the current build" differs
  everywhere. This is the discipline of commit `11a6cb7`.
- **A forward edge counter is required first.** `graph.py:421-423` returns
  `total_conns` — computed in the reverse pass at `graph.py:393` — as *both*
  `forward_connections` and `reverse_connections`, so diffing them today
  compares a number with itself and cannot see a forward/reverse divergence,
  which is exactly the risk of implementing the transform twice.
- Per-pair: each merged MBID node (914 at the scan above; 1,280 on the
  2026-10-07 build) ends with
  `in(mbid) + in(twin) - overlap - self_citations`, counted over **surviving
  sources only** (120 M<->S citations exist among the pairs; blocklisted sources
  never reach the binary).
- Gate-rejected pairs (65 at the scan; 76 on the 2026-10-07 build) must be
  unchanged except for losing sources that are themselves merged twins.

## Recommendation

Ship class 1 alone. It is a bug fix with no editorial content: it restores
edges Last.fm sent that our own id rule dropped, and it is gated on evidence
from the graph rather than on a naming rule.

Classes 2 and 3 keep removal. The identity claim there is ours rather than
Last.fm's, it cannot be gated on graph evidence, and the population it would
re-admit is the one `dd06be3` was written to exclude. Revisit only if the
survivor-source measurement above comes back high.

## Prevention

Postprocessing-only. The collector keeps minting twins, and every rebuild
collapses them, so search is permanently clean and new twins self-heal. A
collector-side `uuid5(url) -> mbid` map would stop the twin ever being created,
to save ~985 redundant crawl slots per sweep lap out of 6.5M. The memory cost is
not the reason: it needs `uuid5(url) -> mbid` for the 912,298 MBID-keyed ids
(13.9% of the dataset), which as a sorted S16 array is ~29 MB, not the
~200-300 MB first estimated. The reason
is that postprocessing also heals the 985 twins that already exist, which a
collector-side fix cannot, so the collector change would be additive work for no
additional correctness.
