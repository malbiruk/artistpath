"""Quick correctness check of keys + binary parsing."""
from pathlib import Path

import orjson

from binio import GraphStore, uuid_to_bytes
from keys import clean_str, mixed_script_name, skeleton

# 1. keys
print("clean_str / skeleton / mixed:")
for s in ["Björk", "Молчат Дома", "Сream", "Lаnа Del Rey", "Justice League"]:
    print(f"  {s!r:22} phon={clean_str(s)!r:18} skel={skeleton(s)!r:18} mixed={mixed_script_name(s)}")

# 2. graph store
data_dir = Path("../../data").resolve()
print(f"\nloading store from {data_dir} ...")
store = GraphStore(data_dir)
print(f"n_nodes={store.n_nodes:,}  fwd={len(store.fwd_index):,}  rev={len(store.rev_index):,}")
print(f"mean out-degree (5k sample) = {store.sample_mean_out_degree(5000):.1f}")

# 3. degree + adjacency on the first graph.ndjson record (a real source node)
with (data_dir / "graph.ndjson").open("rb") as f:
    rec = orjson.loads(f.readline())
src = rec["id"]
src_b = uuid_to_bytes(src)
print(f"\nfirst source node {src}")
print(f"  out_degree(store)={store.out_degree(src_b)}  ndjson_conns={len(rec['connections'])}")
print(f"  in_degree(store)={store.in_degree(src_b)}")
if rec["connections"]:
    nbr = rec["connections"][0][0]
    nbr_b = uuid_to_bytes(nbr)
    print(f"  first ndjson neighbor {nbr}: in out_neighbors={nbr_b in store.out_neighbors(src_b)}  adjacent={store.adjacent(src_b, nbr_b)}")
