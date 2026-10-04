"""Indexed vs unindexed query performance, measured with explain("executionStats").

Why server-side timing: this project talks to MongoDB over a socket. Wall-clock time
around a query includes network latency and BSON decoding, which on Atlas dominates
the query itself. explain("executionStats").executionTimeMillis is measured INSIDE the
server, so it isolates the work the database actually did.

Why .hint({"$natural": 1}) instead of dropping the index: $natural means "read the
documents in the order they are stored", which forces a COLLSCAN. Dropping and
rebuilding a 2dsphere index would take far longer and would change the collection
between runs.

Vocabulary from the explain output:
  COLLSCAN   collection scan - every document is read and tested
  IXSCAN     index scan - only index entries matching the predicate are read
  FETCH      fetch the full document for an index entry
  nReturned        documents the query returned
  totalDocsExamined  documents the server had to read (the real cost)
  totalKeysExamined  index entries the server had to read
"""

from __future__ import annotations

import json
import random
import statistics

import pandas as pd
from pymongo.database import Database

from forestgeo.config import BENCH_COLLECTION, BBOX, EARTH_RADIUS_KM, OUTPUT_DIR

RUNS = 5                 # repeat each measurement and take the median
BENCH_SIZES = (10_000, 50_000, 100_000, 250_000)


def explain_query(db: Database, collection: str, filt: dict,
                  natural: bool = False) -> dict:
    """Run a query under explain() and pull out the four numbers that matter."""
    cur = db[collection].find(filt)
    if natural:
        cur = cur.hint([("$natural", 1)])       # force a collection scan
    plan = cur.explain()
    stats = plan.get("executionStats", {})
    stage = stats.get("executionStages", {})
    # Unwrap FETCH/SHARD stages to find the access method underneath.
    while stage.get("stage") in ("FETCH", "SHARDING_FILTER", "LIMIT", "SKIP") \
            and "inputStage" in stage:
        stage = stage["inputStage"]
    return {
        "stage": stage.get("stage", "?"),
        "n_returned": stats.get("nReturned"),
        "docs_examined": stats.get("totalDocsExamined"),
        "keys_examined": stats.get("totalKeysExamined"),
        "millis": stats.get("executionTimeMillis"),
        "plan": plan,
    }


def timed(db: Database, collection: str, filt: dict, natural: bool,
          runs: int = RUNS) -> dict:
    """Median of several explain() runs - one run can be skewed by cache warming."""
    results = [explain_query(db, collection, filt, natural) for _ in range(runs)]
    first = results[0]
    return {
        "stage": first["stage"],
        "n_returned": first["n_returned"],
        "docs_examined": first["docs_examined"],
        "keys_examined": first["keys_examined"],
        "millis_median": statistics.median(r["millis"] for r in results),
        "millis_min": min(r["millis"] for r in results),
        "plan": first["plan"],
    }


# -------------------------------------------------------------- real-data runs

def real_data_benchmark(db: Database) -> pd.DataFrame:
    """Compare indexed vs COLLSCAN on the project's own collections."""
    from forestgeo.unions import zone

    burn = zone(db, "burn_risk_footprint")
    pa = db.protected_areas.find_one({"name": {"$regex": "Mudumalai"}}) \
        or db.protected_areas.find_one({})

    cases = [
        ("sightings  $geoWithin protected_area", "sightings",
         {"geometry": {"$geoWithin": {"$geometry": pa["geometry"]}}}),
        ("fire_hotspots $geoWithin protected_area", "fire_hotspots",
         {"geometry": {"$geoWithin": {"$geometry": pa["geometry"]}}}),
        ("transport  $geoIntersects protected_area", "transport",
         {"geometry": {"$geoIntersects": {"$geometry": pa["geometry"]}}}),
        ("villages   $geoWithin burn_footprint", "villages",
         {"geometry": {"$geoWithin": {"$geometry": burn["geometry"]}}}),
        ("sightings  $geoWithin 5km circle", "sightings",
         {"geometry": {"$geoWithin": {"$centerSphere":
                                      [[76.70, 11.41], 5 / EARTH_RADIUS_KM]}}}),
    ]

    rows, plans = [], {}
    for label, coll, filt in cases:
        for natural in (False, True):
            r = timed(db, coll, filt, natural)
            rows.append({
                "query": label,
                "collection": coll,
                "collection_size": db[coll].count_documents({}),
                "mode": "COLLSCAN (hint $natural)" if natural else "indexed",
                "stage": r["stage"],
                "n_returned": r["n_returned"],
                "docs_examined": r["docs_examined"],
                "keys_examined": r["keys_examined"],
                "millis_median": r["millis_median"],
            })
            plans[f"{coll}_{'natural' if natural else 'indexed'}"] = r["plan"]
    return pd.DataFrame(rows), plans


# -------------------------------------------------------------- synthetic runs

def _random_points(n: int, bbox=BBOX) -> list[dict]:
    """n uniformly random points inside the bbox, as GeoJSON documents."""
    west, south, east, north = bbox
    rng = random.Random(42)              # fixed seed: the benchmark is reproducible
    return [{"i": i, "geometry": {"type": "Point",
                                  "coordinates": [rng.uniform(west, east),
                                                  rng.uniform(south, north)]}}
            for i in range(n)]


def _query_variants() -> dict[str, dict]:
    """Two queries over the same data, differing only in SELECTIVITY.

    Selectivity is the fraction of the collection a query returns, and it is the single
    biggest factor in whether an index helps. An index must read index entries, then
    fetch each matching document; a collection scan reads every document once but skips
    the index entirely. So:

      * selective query (~0.2% of rows)  -> the index reads a handful of entries and
        wins by orders of magnitude.
      * broad query (~25% of rows)       -> the scan reads everything once, while the
        index reads a quarter of the entries AND fetches a quarter of the documents.
        The advantage nearly vanishes, and can invert.

    The study bbox is roughly 98 x 67 km (6,519 km2). A 2 km circle covers 12.6 km2,
    about 0.19% of it, so the selective query returns ~0.2% of uniformly random points.
    """
    west, south, east, north = BBOX
    mid_lon, mid_lat = (west + east) / 2, (south + north) / 2
    quarter = {"type": "Polygon", "coordinates": [[
        [west, south], [mid_lon, south], [mid_lon, mid_lat], [west, mid_lat],
        [west, south],
    ]]}
    return {
        "selective (~0.2%)": {
            "geometry": {"$geoWithin": {"$centerSphere":
                                        [[mid_lon, mid_lat], 2 / EARTH_RADIUS_KM]}}},
        "broad (~25%)": {"geometry": {"$geoWithin": {"$geometry": quarter}}},
    }


def synthetic_benchmark(db: Database, sizes=BENCH_SIZES) -> pd.DataFrame:
    """Scale test at two selectivities: 10k -> 250k uniformly random points.

    The data is identical across runs (fixed random seed), and each query shape is held
    constant, so the only variable is collection size - which is what makes a growth
    comparison meaningful.
    """
    variants = _query_variants()
    coll = db[BENCH_COLLECTION]
    rows = []
    for n in sizes:
        coll.drop()
        coll.insert_many(_random_points(n), ordered=False)
        coll.create_index([("geometry", "2dsphere")], name="geometry_2dsphere")
        for label, filt in variants.items():
            for natural in (False, True):
                r = timed(db, BENCH_COLLECTION, filt, natural)
                rows.append({
                    "size": n,
                    "selectivity": label,
                    "mode": "COLLSCAN" if natural else "indexed (2dsphere)",
                    "stage": r["stage"],
                    "n_returned": r["n_returned"],
                    "pct_returned": round(100 * (r["n_returned"] or 0) / n, 3),
                    "docs_examined": r["docs_examined"],
                    "keys_examined": r["keys_examined"],
                    "millis_median": r["millis_median"],
                })
            pair = rows[-2:]
            print(f"  {n:>7,} docs | {label:18} "
                  + " | ".join(f"{x['mode']} {x['millis_median']:>4.0f} ms "
                               f"({x['docs_examined']:>7,} examined)" for x in pair))
    coll.drop()
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------- output

def save_plans(plans: dict, subdir: str = "explain") -> str:
    """Write raw explain output as JSON - evidence for the report appendix."""
    d = OUTPUT_DIR / subdir
    d.mkdir(parents=True, exist_ok=True)
    for name, plan in plans.items():
        (d / f"{name}.json").write_text(json.dumps(plan, indent=2, default=str))
    return str(d)


def plot(df: pd.DataFrame, path) -> str:
    """Four log-scale panels: time and documents examined, at each selectivity."""
    import matplotlib
    matplotlib.use("Agg")                 # no display needed on a headless machine
    import matplotlib.pyplot as plt

    levels = list(dict.fromkeys(df["selectivity"]))
    fig, axes = plt.subplots(len(levels), 2, figsize=(11, 4.2 * len(levels)),
                             squeeze=False)
    for row, level in enumerate(levels):
        sub = df[df["selectivity"] == level]
        for col, (field, ylab) in enumerate(
                [("millis_median", "server executionTimeMillis"),
                 ("docs_examined", "totalDocsExamined")]):
            ax = axes[row][col]
            for mode, grp in sub.groupby("mode"):
                grp = grp.sort_values("size")
                ax.plot(grp["size"], grp[field].clip(lower=0.1),
                        marker="o", label=mode)
            ax.set_xscale("log")
            ax.set_yscale("log")
            ax.set_xlabel("documents in collection")
            ax.set_ylabel(ylab)
            ax.set_title(f"{level} - {ylab}", fontsize=10)
            ax.grid(True, which="both", alpha=0.3)
            ax.legend(fontsize=8)
    fig.suptitle("2dsphere index vs collection scan: the advantage depends on "
                 "query selectivity", fontsize=11)
    # Be explicit: a log axis cannot display zero, and the indexed selective query
    # genuinely measures 0 ms at smaller sizes. Clipping it to 0.1 keeps the line
    # visible, so the caption must say so rather than imply sub-millisecond precision.
    fig.text(0.5, 0.005,
             "Server-side executionTimeMillis, median of 5 runs. Values of 0 ms are "
             "plotted at 0.1 ms because a log axis cannot show zero.",
             ha="center", fontsize=8, color="0.35")
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(path, dpi=150)
    return str(path)
