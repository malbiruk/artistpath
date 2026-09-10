# Dataset cleaning: validation lab

The cleaning rules that ship in `data_collection/postprocessing/cleaning.py`
(see the README section "Data Cleaning") were each measured here before being
enabled. This folder is the method and the evidence, not production code:
nothing in the pipeline imports it. It has its own `uv` project; run scripts
from this directory with `uv run python <script>.py` against the built
binaries in `../../data/`.

Every rule went through the same loop:

1. **Generate candidates** from the graph (`gen_*`, `validate_*`, `check_*`).
2. **Draw a labelling sample**, stratified so rare cases are covered
   (`make_*_sample`, `gen_*_sample`), and enrich it with Last.fm `artist.getInfo`
   so a labeller can decide (`fetch_*`).
3. **Label** it in three independent passes; the verdicts are
   `results/*_labels_p{0,1,2}.json` (majority vote).
4. **Score** precision per stratum and extrapolate to the population (`score_*`).

`results/` keeps the label inputs and verdicts in git (about 1 MB). Candidate
dumps and other EDA outputs are gitignored and regenerable.

## Shared plumbing

| Script | Role |
|---|---|
| `binio.py` | Low-memory random access to `graph.bin` / `metadata.bin` via mmap. |
| `keys.py` | Normalisation keys used to generate candidates (`skeleton`, splitting on connectors). Must stay byte-for-byte compatible with `normalization.clean_str`, which the Rust side mirrors. |
| `translit_key.py` | Loose transliteration block key (candidate generation only, never a merge key). |
| `analyze.py` | The original read-only EDA that motivated the first two rules; also `load_names`. |
| `smoke.py`, `lookup.py` | Sanity check of keys + binary parsing; ad-hoc artist lookup with degrees. |

## Rules and how they were measured

### Skeleton duplicates (shipped, ~96-97% precision)

Same visual skeleton, different spelling; collapse to the highest in-degree
spelling. `validate_dedup.py` → `results/dedup_sample.csv` → `fetch_dedup.py`
→ `results/dedup_label_input.json` → labels → `score_dedup2.py`.
A centrality gate on top (`validate_dedup2.py`, `score_dedup2.py`,
`type_dedup.py`, round-2 files `dedup_*2*`) did not separate true from false
merges and was not added.

### Collaboration / feature credits (shipped)

A name that splits into two or more known artists on `feat`/`ft`/`x`/`&`/`,`/`/`/`+`.

- Centrality gate (`CENTRALITY_FRAC=0.2`, ~99.4%): `make_label_sample.py` →
  `results/label_sample.csv` → `fetch_lastfm.py` → `results/label_input.json` →
  labels → `score_labels.py`. `centrality_dist.py` and `verify_features.py`
  are the probes that chose the ratio.
- Member co-occurrence gate (`MM_FRAC=0.5`, ~99.3%, also spares real bands such
  as "X & The Y"): `gen_mm_candidates.py` → `make_mm_sample.py` →
  `results/mm_label_input.json` → labels → `score_mm.py`.
- `x` as a connector (97.5%): `check_x.py` → `make_x_sample.py` → labels →
  `score_x.py`.
- Folding a standalone Cyrillic/Greek `Х`/`Χ` to `x` so Russian credits split
  (100%): `gen_fold_sample.py` → labels → `score_fold.py`.
- `feat`/`ft` credits are removed outright (no real artist is named that way).
- `and`/`with` as connectors were checked (`check_and.py`) and not adopted.

### Transliteration duplicates (shipped, ~100% precision, ~13% recall)

Spellings across scripts (`Пошлая Молли` / `Poshlaya Molly`). Blocked by
`translit_key`, merged only when a direct similarity edge links the spellings.
`gen_translit_candidates.py` → `gen_translit_sample.py` →
`results/translit_label_input.json` → labels → `score_translit.py`.

### Same cleaned name, different skeleton (measured, not adopted)

`gen_sameclean_candidates.py`: 4,734 groups whose names clean to the same
string but keep distinct skeletons (`Twenty Øne Piløts`, `Стинг`/`Sting`), with
the same edge-connectivity check. Also contains cross-language homonyms
(`Hana`/`はな`/`하나`), so it needs its own labelling round before any rule.

## Dropped approaches (do not retry without new evidence)

- String-only transliteration matching: ~50% precision; the direct edge is the
  only gate that held.
- Shared-neighbour / overlap gates instead of the direct edge: ~67%.
- Widening to 2 hops for collab members (`cluster_check.py`): does not
  separate; viral-collab members share almost no neighbours, real duos share many.
- Neighbour-coverage separation (`coverage_proto.py`) and the refinements in
  `probe_refine.py`: both read cluster dumps from an interactive session that
  no longer exists, so they document the idea but cannot be re-run as is.
