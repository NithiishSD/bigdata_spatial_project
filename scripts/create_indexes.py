#!/usr/bin/env python
"""Phase 3b - (re)create every index, then prove the 2dsphere indexes work.

Script load_mongo.py already creates indexes at load time. This is the standalone,
re-runnable check, and it also demonstrates - deliberately - that $nearSphere FAILS
without a geospatial index. That error message is a finding the report quotes.

Run:  python scripts/create_indexes.py
"""

from __future__ import annotations

import json

from pymongo.errors import OperationFailure

from forestgeo import config
from forestgeo.db import get_db, verify
from forestgeo.load import EXTRA_INDEXES

PROBE_COLLECTION = "_index_probe"      # temporary, dropped at the end


def main() -> int:
    db = get_db()
    print(f"Phase 3b - indexes | db={db.name}\n")

    existing = set(db.list_collection_names())
    for name in config.COLLECTIONS:
        if name not in existing:
            print(f"  {name:16} (collection does not exist yet - skipped)")
            continue
        db[name].create_index([("geometry", "2dsphere")], name="geometry_2dsphere")
        for keys in EXTRA_INDEXES.get(name, []):
            db[name].create_index(keys)
        names = [ix["name"] for ix in db[name].list_indexes()]
        print(f"  {name:16} {len(names)} indexes: {', '.join(names)}")

    rep = verify(db)
    rep.to_csv(config.OUTPUT_DIR / "index_report.csv", index=False)

    # --- 1. $nearSphere works WITH an index -------------------------------------
    lon, lat = config.bbox_centre()
    point = {"type": "Point", "coordinates": [lon, lat]}   # [longitude, latitude]
    print("\n$nearSphere WITH a 2dsphere index (20 km of region centre):")
    for name in ("villages", "fire_hotspots", "sightings"):
        if db[name].count_documents({}) == 0:
            continue
        hits = list(db[name].find(
            {"geometry": {"$nearSphere": {"$geometry": point,
                                          "$maxDistance": 20_000}}}  # metres
        ).limit(3))
        nearest = hits[0].get("name") or hits[0].get("species") or hits[0]["source_id"]
        print(f"  {name:16} {len(hits)} returned, nearest = {nearest}")

    # --- 2. $nearSphere FAILS without one ---------------------------------------
    print("\n$nearSphere WITHOUT an index (deliberate failure):")
    probe = db[PROBE_COLLECTION]
    probe.drop()
    probe.insert_one({"geometry": point})      # no 2dsphere index created
    try:
        list(probe.find({"geometry": {"$nearSphere": {"$geometry": point}}}).limit(1))
        print("  unexpectedly succeeded - was an index already present?")
        err = None
    except OperationFailure as exc:
        err = exc.details.get("errmsg", str(exc))
        print(f"  OperationFailure: {err}")

    # --- 3. ...and $geoWithin still works without one ---------------------------
    radians = 5 / config.EARTH_RADIUS_KM        # $centerSphere wants RADIANS
    n = probe.count_documents(
        {"geometry": {"$geoWithin": {"$centerSphere": [[lon, lat], radians]}}})
    print(f"  $geoWithin + $centerSphere without an index: {n} doc(s) - it works, "
          "just by scanning")
    probe.drop()

    if err:
        path = config.OUTPUT_DIR / "nearsphere_without_index_error.json"
        path.write_text(json.dumps({
            "operation": "$nearSphere on a collection with no 2dsphere index",
            "error": err,
            "note": ("$nearSphere/$near/$geoNear require a geospatial index. "
                     "$geoWithin and $geoIntersects do not - they fall back to a "
                     "collection scan."),
        }, indent=2))
        print(f"\n  error text saved for the report -> {path}")

    print("\nPhase 3b complete - indexes verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
