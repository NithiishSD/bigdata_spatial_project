#!/usr/bin/env python
"""Phase 2 — validate and clean every raw dataset into data/processed/.

Writes outputs/validation_report.csv (the fixed/dropped counts go straight into the report).
Idempotent: each processed GeoJSON is replaced, never appended to.

Run:  python scripts/02_clean_validate.py
      python scripts/02_clean_validate.py --only forests --only villages
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from forestgeo import config  # noqa: E402
from forestgeo.clean import CLEANERS, all_valid, write_processed  # noqa: E402
from forestgeo.logutil import banner, setup  # noqa: E402

log = logging.getLogger("clean")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", action="append", choices=list(CLEANERS),
                    help="clean only these collections (repeatable)")
    args = ap.parse_args()
    targets = args.only or list(CLEANERS)

    setup()
    config.ensure_dirs()
    banner(f"Phase 2 — clean & validate | {config.REGION_NAME}")

    rows, failures = [], []
    for name in targets:
        print()
        log.info("--- %s (expects %s) ---", name, config.COLLECTIONS[name])
        try:
            gdf, st = CLEANERS[name]()
        except FileNotFoundError as exc:
            log.warning("skipped %s: %s", name, exc)
            failures.append(f"{name}: missing raw file")
            continue
        except Exception as exc:
            log.exception("failed %s: %s", name, exc)
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
            continue

        if not all_valid(gdf):
            n_bad = int((~gdf.geometry.is_valid).sum())
            log.error("%s: %d INVALID geometries survived cleaning", name, n_bad)
            failures.append(f"{name}: {n_bad} invalid geometries")
        st["geom_types"] = "|".join(sorted(set(gdf.geometry.geom_type))) if len(gdf) else "-"
        st["all_valid"] = all_valid(gdf)
        path = write_processed(name, gdf)
        log.info("%s: %d -> %d rows | %s | wrote %s",
                 name, st["rows_in"], st["rows_out"], st["geom_types"], path)
        rows.append(st)

    banner("Validation report")
    if rows:
        cols = ["collection", "rows_in", "fixed", "dropped_invalid", "dropped_family",
                "dropped_bbox", "dropped_duplicate", "dropped_attr", "rows_out",
                "geom_types", "all_valid"]
        rep = pd.DataFrame(rows)[cols]
        path = config.OUTPUT_DIR / "validation_report.csv"
        if path.exists():  # accumulate across partial runs
            old = pd.read_csv(path)
            rep = (pd.concat([old, rep], ignore_index=True)
                   .drop_duplicates(subset="collection", keep="last"))
        order = {c: i for i, c in enumerate(CLEANERS)}
        rep = rep.sort_values("collection", key=lambda s: s.map(order))
        rep.to_csv(path, index=False)
        print(rep.to_string(index=False))
        print(f"\ntotal rows out: {int(rep['rows_out'].sum())}")
        log.info("wrote %s", path)

    if failures:
        banner("ISSUES")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nPhase 2 complete — every processed geometry is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
