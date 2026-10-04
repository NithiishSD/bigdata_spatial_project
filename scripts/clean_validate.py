#!/usr/bin/env python
"""Phase 2 - validate and clean every raw dataset into data/processed/.

Writes outputs/validation_report.csv: the fixed and dropped counts that the report
cites as evidence the data was handled properly. Idempotent - each processed file is
replaced, never appended to.

Run:  python scripts/clean_validate.py
      python scripts/clean_validate.py --only forests --only villages
"""

from __future__ import annotations

import argparse

import pandas as pd

from forestgeo import config
from forestgeo.clean import CLEANERS, all_valid, write_processed

COLS = ["collection", "family", "rows_in", "fixed", "dropped_empty", "dropped_family",
        "dropped_bbox", "dropped_duplicate", "dropped_attr", "rows_out",
        "geom_types", "all_valid"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", action="append", choices=list(CLEANERS))
    args = ap.parse_args()
    targets = args.only or list(CLEANERS)

    print(f"Phase 2 - clean & validate | {config.REGION_NAME}\n")
    rows, failures = [], []

    for name in targets:
        family = config.COLLECTIONS[name]
        try:
            gdf, st = CLEANERS[name]()
        except FileNotFoundError as exc:
            print(f"  {name:16} SKIPPED - {exc}")
            failures.append(f"{name}: missing raw file")
            continue
        except Exception as exc:
            print(f"  {name:16} FAILED  - {type(exc).__name__}: {exc}")
            failures.append(f"{name}: {type(exc).__name__}")
            continue

        if not all_valid(gdf):
            n_bad = int((~gdf.geometry.is_valid).sum())
            print(f"  {name:16} {n_bad} INVALID geometries survived cleaning")
            failures.append(f"{name}: {n_bad} invalid")

        st["family"] = family
        st["geom_types"] = ("|".join(sorted(set(gdf.geometry.geom_type)))
                            if len(gdf) else "-")
        st["all_valid"] = all_valid(gdf)
        write_processed(name, gdf)
        dropped = (st["dropped_empty"] + st["dropped_family"] + st["dropped_bbox"]
                   + st["dropped_duplicate"] + st["dropped_attr"])
        print(f"  {name:16} {st['rows_in']:6} -> {st['rows_out']:6}"
              f"  (fixed {st['fixed']}, dropped {dropped})  {st['geom_types']}")
        rows.append(st)

    if rows:
        rep = pd.DataFrame(rows)[COLS]
        path = config.OUTPUT_DIR / "validation_report.csv"
        if path.exists() and args.only:          # accumulate across partial runs
            old = pd.read_csv(path)
            rep = (pd.concat([old, rep], ignore_index=True)
                     .drop_duplicates(subset="collection", keep="last"))
        order = {c: i for i, c in enumerate(CLEANERS)}
        rep = rep.sort_values("collection", key=lambda s: s.map(order))
        rep.to_csv(path, index=False)
        print("\nValidation report")
        print(rep.to_string(index=False))
        print(f"\ntotal rows out: {int(rep.rows_out.sum()):,}  ->  {path}")

    if failures:
        print(f"\nISSUES: {failures}")
        return 1
    print("\nPhase 2 complete - every processed geometry is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
