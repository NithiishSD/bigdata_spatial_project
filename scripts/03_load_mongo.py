#!/usr/bin/env python
"""Phase 3 — load every processed layer into MongoDB with a 2dsphere index.

Idempotent: each collection is dropped and reloaded.

Run:  python scripts/03_load_mongo.py
      python scripts/03_load_mongo.py --only villages --only forests
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from forestgeo import config  # noqa: E402
from forestgeo.clean import CLEANERS, read_processed  # noqa: E402
from forestgeo.db import get_db, safe_uri  # noqa: E402
from forestgeo.load import gdf_to_docs, load_collection, verify  # noqa: E402
from forestgeo.logutil import banner, setup  # noqa: E402

log = logging.getLogger("load")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", action="append", choices=list(CLEANERS))
    args = ap.parse_args()
    targets = args.only or list(CLEANERS)

    setup()
    config.ensure_dirs()
    db = get_db()
    banner(f"Phase 3 — load into MongoDB | {safe_uri()} | db={db.name}")

    summaries, failures = [], []
    for name in targets:
        print()
        try:
            gdf = read_processed(name)
        except FileNotFoundError as exc:
            log.warning("skipped %s: %s", name, exc)
            failures.append(f"{name}: no processed file")
            continue
        docs = gdf_to_docs(gdf, name)
        summaries.append(load_collection(db, name, docs))

    banner("Verification")
    rep = verify(db)
    print(rep.to_string(index=False))
    path = config.OUTPUT_DIR / "load_summary.csv"
    rep.to_csv(path, index=False)
    log.info("wrote %s", path)

    loaded = rep[rep["count"] > 0]
    missing_idx = loaded[~loaded["has_2dsphere"]]["collection"].tolist()
    total_rejected = sum(s["rejected"] for s in summaries)
    print(f"\ntotal documents: {int(rep['count'].sum())} across {len(loaded)} collections")
    if total_rejected:
        print(f"rejected documents: {total_rejected} (see outputs/rejected_*.jsonl)")
        failures.append(f"{total_rejected} rejected documents")
    if missing_idx:
        failures.append(f"missing 2dsphere index: {missing_idx}")

    if failures:
        banner("ISSUES")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nPhase 3 complete — all layers loaded and indexed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
