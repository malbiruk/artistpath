"""Ad-hoc: look up artists by name and show in/out degree, plus collab entries
that contain the name (normalized, word-aware substring)."""
import sys
from pathlib import Path

from analyze import load_names
from binio import GraphStore, uuid_to_bytes
from keys import clean_str

QUERIES = sys.argv[1:] or ["acid drop king", "flowers in your eyes", "corn wave"]


def main() -> None:
    data_dir = Path("../../data").resolve()
    store = GraphStore(data_dir)
    data = load_names(data_dir / "metadata.ndjson")
    names, phon = data["names"], data["phon_groups"]

    for q in QUERIES:
        qn = clean_str(q)
        print(f"\n=== query: {q!r}  (norm {qn!r}) ===")
        exact = phon.get(qn, [])
        for aid in exact:
            b = uuid_to_bytes(aid)
            print(f"  [exact] {names[aid]!r:40} in={store.in_degree(b):<6} out={store.out_degree(b)}")
        if not exact:
            print("  [exact] (no exact node)")

        # collab entries: any normalized name that contains qn as a word-run
        pad = f" {qn} "
        hits = []
        for k in phon:
            kk = f" {k} "
            if k != qn and pad in kk:
                hits.append(k)
        hits.sort(key=len)
        print(f"  collab/containing entries: {len(hits)}")
        for k in hits[:12]:
            ids = phon[k]
            ind = max(store.in_degree(uuid_to_bytes(a)) for a in ids)
            print(f"      {names[ids[0]]!r:55} in(max)={ind}")


if __name__ == "__main__":
    main()
