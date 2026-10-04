#!/usr/bin/env python
"""Phase 7 - prove the 2dsphere index matters, with explain("executionStats").

Three experiments:
  1. real collections: indexed vs forced COLLSCAN on the project's own queries
  2. synthetic scale test: 10k -> 250k random points, same query, both access methods
  3. the operators that REQUIRE an index, and what happens without one

Run:  python scripts/benchmark.py
"""

from __future__ import annotations

import pandas as pd
from pymongo.errors import OperationFailure

from forestgeo import config
from forestgeo.benchmark import plot, real_data_benchmark, save_plans, synthetic_benchmark
from forestgeo.db import get_db
from forestgeo.queries import point


def main() -> int:
    db = get_db()
    print(f"Phase 7 - index benchmark | {config.REGION_NAME}\n")

    # ------------------------------------------------------------ 1. real data
    print("1) Real collections: indexed vs COLLSCAN (median of 5 runs)")
    real, plans = real_data_benchmark(db)
    show = ["query", "collection_size", "mode", "stage", "n_returned",
            "docs_examined", "millis_median"]
    print(real[show].to_string(index=False))
    real.to_csv(config.OUTPUT_DIR / "benchmark_real.csv", index=False)

    # Speed-up factor per query, guarding against a 0 ms indexed measurement.
    piv = real.pivot_table(index="query", columns="mode", values="millis_median")
    if piv.shape[1] == 2:
        idx_col = [c for c in piv.columns if c == "indexed"][0]
        scan_col = [c for c in piv.columns if c != "indexed"][0]
        piv["speedup"] = (piv[scan_col] / piv[idx_col].clip(lower=0.5)).round(1)
        print("\n   speed-up (COLLSCAN ms / indexed ms, indexed floored at 0.5 ms):")
        print(piv[["speedup"]].to_string())

    print("\n   raw explain plans ->", save_plans(plans))

    # ------------------------------------------------------- 2. synthetic scale
    print(f"\n2) Synthetic scale test: {config.BENCH_COLLECTION}, "
          f"sizes {list(config.__dict__.get('BENCH_SIZES', (10_000, 50_000, 100_000, 250_000)))}")
    synth = synthetic_benchmark(db)
    synth.to_csv(config.OUTPUT_DIR / "benchmark.csv", index=False)
    print("\n" + synth.to_string(index=False))

    chart = plot(synth, config.OUTPUT_DIR / "benchmark.png")
    print(f"\n   chart -> {chart}")

    # Growth factor: how much each access method slowed from smallest to largest.
    for mode, grp in synth.groupby("mode"):
        grp = grp.sort_values("size")
        lo, hi = grp.iloc[0], grp.iloc[-1]
        docs_growth = hi.docs_examined / max(lo.docs_examined, 1)
        print(f"   {mode:22} {lo['size']:,} -> {hi['size']:,} docs: "
              f"docs_examined x{docs_growth:.1f}, "
              f"time {lo.millis_median:.0f} -> {hi.millis_median:.0f} ms")

    # ------------------------------------------- 3. operators that need an index
    print("\n3) Operators that REQUIRE a geospatial index")
    probe = db["_bench_probe"]
    probe.drop()
    probe.insert_one({"geometry": point(*config.bbox_centre())})
    try:
        list(probe.find({"geometry": {"$nearSphere": {"$geometry":
             point(*config.bbox_centre())}}}).limit(1))
        print("   $nearSphere unexpectedly succeeded without an index")
    except OperationFailure as exc:
        print(f"   $nearSphere without index -> OperationFailure: "
              f"{exc.details.get('errmsg', '')[:120]}")
    n = probe.count_documents({"geometry": {"$geoWithin": {"$centerSphere":
        [[*config.bbox_centre()], 5 / config.EARTH_RADIUS_KM]}}})
    print(f"   $geoWithin without index -> works, returned {n} (by scanning)")
    probe.drop()

    print("\nPhase 7 complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
