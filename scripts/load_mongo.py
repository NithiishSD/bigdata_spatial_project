#!/usr/bin/env python
"""Phase 3 - load every processed layer into MongoDB with a 2dsphere index.

Idempotent: each collection is dropped and reloaded.

Run:  python scripts/load_mongo.py
      python scripts/load_mongo.py --only villages --only forests
"""

from __future__ import annotations

import argparse

from forestgeo import config
from forestgeo.clean import CLEANERS, read_processed
from forestgeo.db import get_db, safe_uri, verify
from forestgeo.load import gdf_to_docs, load_collection


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", action="append", choices=list(CLEANERS))
    args = ap.parse_args()
    targets = args.only or list(CLEANERS)

    db = get_db()
    print(f"Phase 3 - load into MongoDB | {safe_uri()} | db={db.name}\n")

    summaries, failures = [], []
    for name in targets:
        try:
            gdf = read_processed(name)
        except FileNotFoundError:
            print(f"  {name:16} SKIPPED - no processed file")
            failures.append(f"{name}: no processed file")
            continue
        docs = gdf_to_docs(gdf, name)
        s = load_collection(db, name, docs)
        print(f"  {name:16} inserted {s['inserted']:6}/{s['docs_built']:<6}"
              f" rejected {s['rejected']:3}  indexes: {len(s['indexes'])}")
        summaries.append(s)

    rep = verify(db)
    print("\nVerification")
    print(rep[["collection", "count", "geom_types", "has_2dsphere", "n_indexes"]]
          .to_string(index=False))
    path = config.OUTPUT_DIR / "load_summary.csv"
    rep.to_csv(path, index=False)

    loaded = rep[rep["count"] > 0]
    missing = loaded[~loaded["has_2dsphere"]]["collection"].tolist()
    total_rejected = sum(s["rejected"] for s in summaries)
    print(f"\ntotal documents: {int(rep['count'].sum()):,} "
          f"across {len(loaded)} collections  ->  {path}")
    if total_rejected:
        failures.append(f"{total_rejected} rejected documents")
    if missing:
        failures.append(f"missing 2dsphere index: {missing}")

    if failures:
        print(f"\nISSUES: {failures}")
        return 1
    print("\nPhase 3 complete - all layers loaded and indexed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
