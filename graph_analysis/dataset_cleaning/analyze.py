#!/usr/bin/env python3
"""Read-only EDA to validate two cleaning rules before touching postprocessing.

Rule 1 (transliteration / homoglyph dupes): artists sharing a normalization key
  are dup-candidates; if they're directly connected in the graph it's evidence
  they're the same artist (same listeners) -> keep the higher in-degree node.
  Two keys are tested: clean_str (phonetic, what serving uses) and skeleton
  (visual/homoglyph, catches look-alike spoofs clean_str misses).

Rule 2 (features / collabs): a name that decomposes into >=2 known artist names
  (+ connector tokens) and is adjacent to them is likely a collab entity.

Nothing is mutated. Outputs: a printed report + labeled JSON samples under
results/ for manual precision eyeballing.

Run:  uv run analyze.py --rule all
"""

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

import orjson
from binio import GraphStore, uuid_to_bytes
from keys import segment_name
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

console = Console()

SEG_KNOWN_FRAC = 1.0     # fraction of segments that must be known artist nodes (popularity-blind)
CENTRALITY_FRAC = 0.2    # set from the labeled threshold sweep: ~99.4% precision, knee of the
                         # act-rate curve (above this, real bands start appearing among deletes)


# --- fast combined normalization (ascii fast path) ---------------------------


def compute_keys(name: str) -> tuple[str, str, bool]:
    """Return (phon_key, skel_key, mixed_script). ascii names take a cheap path
    that is identical to the full clean_str/skeleton result."""
    if name.isascii():
        lo = name.lower()
        phon = " ".join(lo.split())
        skel = " ".join("".join(c if (c.isalnum() or c.isspace()) else " " for c in lo).split())
        return phon, skel, False
    # non-ascii: full path
    from keys import clean_str, mixed_script_name, skeleton

    return clean_str(name), skeleton(name), mixed_script_name(name)


# --- data loading ------------------------------------------------------------


def load_names(metadata_ndjson: Path) -> dict[str, Any]:
    """One pass over metadata.ndjson. Builds id->name and the two key groupings."""
    names: dict[str, str] = {}
    phon_groups: dict[str, list[str]] = {}
    skel_groups: dict[str, list[str]] = {}
    mixed: list[str] = []  # ids with a mixed-script token

    total = 5_404_991  # from `wc -l`; only drives the progress bar
    with (
        metadata_ndjson.open("rb") as f,
        Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress,
    ):
        task = progress.add_task("Reading metadata + normalizing...", total=total)
        for i, raw in enumerate(f):
            if not raw.strip():
                continue
            try:
                e = orjson.loads(raw)
                aid = e["id"]
                name = e["name"]
            except (orjson.JSONDecodeError, KeyError):
                continue
            names[aid] = name
            phon, skel, mix = compute_keys(name)
            phon_groups.setdefault(phon, []).append(aid)
            skel_groups.setdefault(skel, []).append(aid)
            if mix:
                mixed.append(aid)
            if (i & 0x3FFFF) == 0:
                progress.update(task, completed=i)
        progress.update(task, completed=total)

    return {
        "names": names,
        "phon_groups": phon_groups,
        "skel_groups": skel_groups,
        "mixed": mixed,
    }


# --- helpers -----------------------------------------------------------------


def rep_id(store: GraphStore, ids: list[str]) -> str:
    """The 'canonical' member of a group: highest in-degree."""
    return max(ids, key=lambda a: store.in_degree(uuid_to_bytes(a)))


def group_adjacency(store: GraphStore, ids: list[str]) -> tuple[int, int]:
    """(#adjacent pairs, #total pairs) among group members (directed either-way)."""
    bys = [uuid_to_bytes(a) for a in ids]
    adj = 0
    tot = 0
    for i in range(len(bys)):
        for j in range(i + 1, len(bys)):
            tot += 1
            if store.adjacent(bys[i], bys[j]):
                adj += 1
    return adj, tot


def write_samples(out_dir: Path, fname: str, rows: list[dict]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / fname
    p.write_bytes(orjson.dumps(rows, option=orjson.OPT_INDENT_2))
    return p


# --- Rule 1: transliteration / homoglyph dupes -------------------------------


def analyze_translit(
    data: dict, store: GraphStore, out_dir: Path, n_samples: int, baseline: float
) -> None:
    console.rule("[bold]Rule 1 - transliteration / homoglyph dupes")
    names = data["names"]
    phon_groups = data["phon_groups"]
    skel_groups = data["skel_groups"]

    phon_coll = {k: v for k, v in phon_groups.items() if len(v) >= 2}
    n_nodes_in_groups = sum(len(v) for v in phon_coll.values())

    console.print(
        f"phonetic-key collision groups (>=2 ids): [cyan]{len(phon_coll):,}[/] "
        f"covering [cyan]{n_nodes_in_groups:,}[/] nodes"
    )

    # Adjacency of collisions vs baseline. We test each group: are its members
    # connected? Adjacent => evidence of true dupe; not adjacent => likely
    # homonyms (different artists, same spelling) which we must NOT delete.
    size_hist: Counter = Counter()
    groups_any_adjacent = 0
    groups_all_adjacent = 0
    pair_adj = 0
    pair_tot = 0
    indeg_ratios: list[float] = []
    adjacent_samples: list[dict] = []
    nonadjacent_samples: list[dict] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Checking collision adjacency...", total=len(phon_coll))
        for key, ids in phon_coll.items():
            progress.advance(task)
            size_hist[min(len(ids), 5)] += 1
            adj, tot = group_adjacency(store, ids)
            pair_adj += adj
            pair_tot += tot
            if adj > 0:
                groups_any_adjacent += 1
            if adj == tot:
                groups_all_adjacent += 1

            indegs = sorted(((store.in_degree(uuid_to_bytes(a)), a) for a in ids), reverse=True)
            top, second = indegs[0][0], indegs[1][0]
            if top > 0:
                indeg_ratios.append((top - second) / top)  # 1.0 => one node dominates

            row = {
                "key": key,
                "members": [{"name": names.get(a, a), "id": a, "in_degree": d} for d, a in indegs],
                "adjacent_pairs": adj,
                "total_pairs": tot,
                "keep": names.get(indegs[0][1], indegs[0][1]),
            }
            if adj > 0 and len(adjacent_samples) < n_samples:
                adjacent_samples.append(row)
            elif adj == 0 and len(nonadjacent_samples) < n_samples:
                nonadjacent_samples.append(row)

    pair_rate = pair_adj / pair_tot if pair_tot else 0.0
    console.print(
        f"groups with [b]any[/] adjacent pair: [green]{groups_any_adjacent:,}[/] "
        f"({groups_any_adjacent / len(phon_coll):.1%})   "
        f"all-adjacent: [green]{groups_all_adjacent:,}[/] "
        f"({groups_all_adjacent / len(phon_coll):.1%})"
    )
    console.print(
        f"pairwise adjacency rate among same-name pairs: [green]{pair_rate:.3%}[/]  "
        f"vs random-pair baseline ~[dim]{baseline:.2e}[/]  "
        f"([b]{(pair_rate / baseline) if baseline else float('inf'):.0f}x[/] baseline)"
    )

    import numpy as np

    if indeg_ratios:
        arr = np.array(indeg_ratios)
        console.print(
            "in-degree dominance within group (1.0 = top node has all in-edges): "
            f"median [cyan]{np.median(arr):.2f}[/], "
            f"share>=0.9: [cyan]{(arr >= 0.9).mean():.1%}[/]"
        )

    t = Table(title="phonetic collision group sizes")
    t.add_column("members")
    t.add_column("groups", justify="right")
    for k in sorted(size_hist):
        t.add_row("5+" if k == 5 else str(k), f"{size_hist[k]:,}")
    console.print(t)

    # --- homoglyph delta: skel collisions that phon does NOT already catch ----
    phon_keyset = phon_coll.keys()
    homoglyph_extra: list[dict] = []
    n_homoglyph_groups = 0
    for key, ids in skel_groups.items():
        if len(ids) < 2:
            continue
        # ids whose names are NOT all collapsed by phon already
        phon_keys = {compute_keys(names[a])[0] for a in ids}
        if len(phon_keys) < 2:
            continue  # phon already merges them -> not a new catch
        # require at least one non-ascii member (a real look-alike spoof)
        if all(names[a].isascii() for a in ids):
            continue
        n_homoglyph_groups += 1
        if len(homoglyph_extra) < n_samples:
            adj, tot = group_adjacency(store, ids)
            homoglyph_extra.append(
                {
                    "skeleton": key,
                    "members": [
                        {
                            "name": names[a],
                            "phon": compute_keys(names[a])[0],
                            "id": a,
                            "in_degree": store.in_degree(uuid_to_bytes(a)),
                        }
                        for a in ids
                    ],
                    "adjacent_pairs": adj,
                    "total_pairs": tot,
                }
            )
    console.print(
        f"\n[b]homoglyph delta[/]: skeleton groups missed by phonetic key "
        f"(visual dupes in different lookup buckets): [magenta]{n_homoglyph_groups:,}[/]"
    )

    # --- mixed-script standalone signal --------------------------------------
    mixed = data["mixed"]
    console.print(
        f"[b]mixed-script[/] names (token mixing >1 script, near-certain spoof): "
        f"[magenta]{len(mixed):,}[/]"
    )
    mixed_samples = [
        {"name": names[a], "id": a, "in_degree": store.in_degree(uuid_to_bytes(a))}
        for a in mixed[: n_samples * 2]
    ]

    p1 = write_samples(out_dir, "translit_adjacent.json", adjacent_samples)
    p2 = write_samples(out_dir, "translit_nonadjacent.json", nonadjacent_samples)
    p3 = write_samples(out_dir, "translit_homoglyph_delta.json", homoglyph_extra)
    p4 = write_samples(out_dir, "translit_mixed_script.json", mixed_samples)
    console.print(f"[dim]samples -> {p1.name}, {p2.name}, {p3.name}, {p4.name}[/]")


# --- Rule 2: features / collabs ----------------------------------------------


def full_decompose(
    tokens: list[str], known: set, exclude: str, maxspan: int = 6
) -> list[str] | None:
    """Greedily partition tokens into known-artist spans (longest first),
    refusing to match the whole name (`exclude`). Returns the spans only if the
    WHOLE name is covered with no leftover tokens and there are >=2 of them.
    Used for space-only collab detection ("A B" with no connector)."""
    n = len(tokens)
    i = 0
    parts: list[str] = []
    while i < n:
        hit = None
        for j in range(min(n, i + maxspan), i, -1):
            span = " ".join(tokens[i:j])
            if span != exclude and span in known:
                hit = (span, j)
                break
        if hit is None:
            return None
        parts.append(hit[0])
        i = hit[1]
    return parts if len(parts) >= 2 else None


def analyze_features(
    data: dict,
    store: GraphStore,
    out_dir: Path,
    n_samples: int,
    seg_known_frac: float,
    centrality_frac: float,
) -> None:
    console.rule("[bold]Rule 2 - features / collabs (delimiter segmentation)")
    names = data["names"]
    phon_groups = data["phon_groups"]
    known = set(phon_groups.keys())

    rep_cache: dict[str, tuple[bytes, int]] = {}

    def rep_and_indeg(nn: str) -> tuple[bytes, int]:
        c = rep_cache.get(nn)
        if c is None:
            rb = uuid_to_bytes(rep_id(store, phon_groups[nn]))
            c = (rb, store.in_degree(rb))
            rep_cache[nn] = c
        return c

    # funnel
    n_multi = 0     # splits into >=2 segments
    n_known = 0     # + (>= frac) segments are known artist nodes, >=2 of them
    n_delete = 0    # + (strong connector OR secondary-by-centrality)
    del_with_adj = 0
    by_reason: Counter = Counter()
    seg_hist: Counter = Counter()
    dir_f2c = dir_c2f = dir_both = adj_components = 0
    n_space_decomp = n_space_delete = 0   # tier 3: space-only (no connector)
    samples_space: list[dict] = []

    samples_delete: list[dict] = []
    samples_kept_duo: list[dict] = []      # all-known, weak-only, NOT secondary -> spared (real duos)
    samples_unknown_seg: list[dict] = []   # has delimiter but a segment isn't an artist

    candidates = [k for k in known if " " in k]

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Segmenting names...", total=len(candidates))
        for normname in candidates:
            progress.advance(task)
            segs, has_strong, has_weak = segment_name(normname)
            if len(segs) < 2:
                # tier 3 (experimental): no connector at all -> try to decompose
                # the bare "A B" name into >=2 known artists. Gated HARD on the
                # collab being secondary, else real multi-word bands get hit.
                toks = normname.split()
                if len(toks) >= 2:
                    parts = full_decompose(toks, known, normname)
                    if parts:
                        n_space_decomp += 1
                        _, ci = rep_and_indeg(normname)
                        mc = max(rep_and_indeg(p)[1] for p in parts)
                        if ci < centrality_frac * mc:
                            n_space_delete += 1
                            if len(samples_space) < n_samples:
                                samples_space.append(
                                    {
                                        "name": names.get(phon_groups[normname][0], normname),
                                        "norm": normname,
                                        "collab_in_degree": ci,
                                        "parts": [
                                            {"artist": p, "in_degree": rep_and_indeg(p)[1]}
                                            for p in parts
                                        ],
                                    }
                                )
                continue
            n_multi += 1

            known_segs = [s for s in segs if s != normname and s in known]
            frac_known = len(known_segs) / len(segs)
            if len(known_segs) < 2 or frac_known < seg_known_frac:
                if len(known_segs) >= 1 and len(samples_unknown_seg) < n_samples:
                    samples_unknown_seg.append(
                        {
                            "name": names.get(phon_groups[normname][0], normname),
                            "norm": normname,
                            "segments": segs,
                            "known_segments": known_segs,
                            "frac_known": round(frac_known, 2),
                        }
                    )
                continue
            n_known += 1
            seg_hist[min(len(known_segs), 4)] += 1

            cand_b, cand_ind = rep_and_indeg(normname)
            comp = [(s, *rep_and_indeg(s)) for s in known_segs]  # (span, bytes, in_degree)
            max_comp = max(ind for _, _, ind in comp)
            # "secondary": the collab is far less central than its biggest member
            # -> derived credit, not a primary act like a famous duo.
            secondary = cand_ind < centrality_frac * max_comp

            # connectivity (reported, NOT gated — recall is low, see translit finding)
            cand_out = store.out_neighbors(cand_b)
            n_adj = 0
            comp_rows = []
            for span, rb, ind in comp:
                f2c = rb in cand_out                       # collab lists member
                c2f = cand_b in store.out_neighbors(rb)    # member lists collab
                is_adj = f2c or c2f
                if is_adj:
                    n_adj += 1
                    adj_components += 1
                    if f2c and c2f:
                        dir_both += 1
                    elif f2c:
                        dir_f2c += 1
                    else:
                        dir_c2f += 1
                comp_rows.append(
                    {
                        "artist": span,
                        "in_degree": ind,
                        "adjacent": is_adj,
                        "dir": "both" if (f2c and c2f) else "F->c" if f2c else "c->F" if c2f else "none",
                    }
                )

            row = {
                "name": names.get(phon_groups[normname][0], normname),
                "norm": normname,
                "collab_in_degree": cand_ind,
                "n_segments": len(known_segs),
                "has_strong": has_strong,
                "has_weak": has_weak,
                "secondary": secondary,
                "n_adjacent": n_adj,
                "components": comp_rows,
            }

            # decision is PURELY graph centrality; the connector only split the name.
            if secondary:
                n_delete += 1
                del_with_adj += int(n_adj > 0)
                by_reason["feat-split" if has_strong else "symbol-split"] += 1
                if len(samples_delete) < n_samples:
                    samples_delete.append(row)
            elif len(samples_kept_duo) < n_samples:  # central -> primary act, spared
                samples_kept_duo.append(row)

    console.print("[b]funnel[/] (symbols + feat, decision = graph centrality):")
    t = Table(show_header=True)
    t.add_column("filter")
    t.add_column("names", justify="right")
    t.add_row("multi-token names scanned", f"{len(candidates):,}")
    t.add_row("splits into >=2 segments (symbols + feat)", f"{n_multi:,}")
    t.add_row(f"+ >=2 segments are known artists (>= {seg_known_frac:.0%})", f"{n_known:,}")
    t.add_row("+ secondary by centrality -> DELETE", f"{n_delete:,}")
    console.print(t)

    r = Table(title="split marker among deletes")
    r.add_column("split on")
    r.add_column("names", justify="right")
    for label in ("symbol-split", "feat-split"):
        r.add_row(label, f"{by_reason.get(label, 0):,}")
    console.print(r)
    console.print(
        f"all-known names spared as central/primary acts: "
        f"[green]{n_known - n_delete:,}[/]   "
        f"deletes that ARE graph-adjacent to a member: [cyan]{del_with_adj:,}[/] "
        f"({del_with_adj / n_delete:.1%} — connectivity has low recall, so it's reported not gated)"
    )

    sh = Table(title="# known segments per collab")
    sh.add_column("segments")
    sh.add_column("names", justify="right")
    for k in sorted(seg_hist):
        sh.add_row("4+" if k == 4 else str(k), f"{seg_hist[k]:,}")
    console.print(sh)

    if adj_components:
        d = Table(title="direction of adjacent collab<->member links")
        d.add_column("direction")
        d.add_column("count", justify="right")
        d.add_column("share", justify="right")
        for label, c in [
            ("collab -> member", dir_f2c),
            ("member -> collab", dir_c2f),
            ("both", dir_both),
        ]:
            d.add_row(label, f"{c:,}", f"{c / adj_components:.1%}")
        console.print(d)
        console.print(
            f"[dim]one-way-enough: requiring BOTH directions keeps only "
            f"{dir_both / adj_components:.1%} of adjacent links[/]"
        )

    console.print(
        f"\n[b]tier 3 (space-only, experimental)[/]: bare 'A B' names that fully "
        f"decompose into >=2 known artists: [magenta]{n_space_decomp:,}[/]; of those, "
        f"secondary -> would delete: [magenta]{n_space_delete:,}[/]"
    )

    p1 = write_samples(out_dir, "features_delete.json", samples_delete)
    p2 = write_samples(out_dir, "features_kept_duo.json", samples_kept_duo)
    p3 = write_samples(out_dir, "features_unknown_seg.json", samples_unknown_seg)
    p4 = write_samples(out_dir, "features_space_only.json", samples_space)
    console.print(
        f"[dim]samples -> {p1.name} (would delete), {p2.name} (spared as real duo), "
        f"{p3.name} (delimiter present, a segment isn't a known artist), "
        f"{p4.name} (space-only — EYEBALL for false positives)[/]"
    )


# --- main --------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="../../data")
    ap.add_argument("--rule", choices=["translit", "features", "all"], default="all")
    ap.add_argument("--samples", type=int, default=200)
    ap.add_argument("--out-dir", default="results")
    ap.add_argument("--seg-known-frac", type=float, default=SEG_KNOWN_FRAC)
    ap.add_argument("--centrality-frac", type=float, default=CENTRALITY_FRAC)
    args = ap.parse_args()

    data_dir = Path(args.data_dir).resolve()
    out_dir = Path(args.out_dir).resolve()

    console.print(f"[cyan]Loading graph store (mmap) from {data_dir}...")
    store = GraphStore(data_dir)
    n = store.n_nodes
    mean_out = store.sample_mean_out_degree(5000)
    baseline = mean_out / n if n else 0.0
    console.print(
        f"[green]nodes={n:,}  mean out-degree~{mean_out:.0f}  "
        f"random-pair adjacency baseline~{baseline:.2e}"
    )

    data = load_names(data_dir / "metadata.ndjson")
    console.print(
        f"[green]loaded {len(data['names']):,} names, "
        f"{len(data['phon_groups']):,} phonetic keys, "
        f"{len(data['skel_groups']):,} skeleton keys"
    )

    if args.rule in ("translit", "all"):
        analyze_translit(data, store, out_dir, args.samples, baseline)
    if args.rule in ("features", "all"):
        analyze_features(
            data,
            store,
            out_dir,
            args.samples,
            args.seg_known_frac,
            args.centrality_frac,
        )


if __name__ == "__main__":
    main()
