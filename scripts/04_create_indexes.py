#!/usr/bin/env python
"""Phase 4 prerequisite — (re)create every index and prove the 2dsphere ones work.

Script 03 already creates indexes at load time; this script is the standalone,
re-runnable check: it ensures each index exists, then runs a $nearSphere probe that
can only succeed with a geospatial index in place.

Run:  python scripts/04_create_indexes.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pymongo.errors import OperationFailure  # noqa: E402

from forestgeo import config  # noqa: E402
from forestgeo.db import get_db  # noqa: E402
from forestgeo.load import EXTRA_INDEXES, verify  # noqa: E402
from forestgeo.logutil import banner, setup  # noqa: E402

log = logging.getLogger("indexes")


def main() -> int:
    setup()
    db = get_db()
    banner(f"Phase 3b — indexes | db={db.name}")

    existing = db.list_collection_names()
    for name in config.COLLECTIONS:
        if name not in existing:
            log.warning("%s: collection does not exist yet — skipping", name)
            continue
        db[name].create_index([("geometry", "2dsphere")], name="geometry_2dsphere")
        for keys in EXTRA_INDEXES.get(name, []):
            db[name].create_index(keys)
        log.info("%s: %s", name, [ix["name"] for ix in db[name].list_indexes()])

    banner("Index report")
    rep = verify(db)
    print(rep.to_string(index=False))
    rep.to_csv(config.OUTPUT_DIR / "index_report.csv", index=False)

    banner("$nearSphere probe (only works with a 2dsphere index)")
    lon, lat = config.bbox_centre()
    ok = True
    for name in ("villages", "fire_hotspots", "sightings"):
        if db[name].count_documents({}) == 0:
            log.warning("%s: empty, skipping probe", name)
            continue
        try:
            n = len(list(db[name].find(
                {"geometry": {"$nearSphere": {"$geometry": {"type": "Point",
                                                            "coordinates": [lon, lat]},
                                              "$maxDistance": 20_000}}}).limit(5)))
            print(f"  {name}: $nearSphere returned {n} docs within 20 km of the region centre")
        except OperationFailure as exc:
            ok = False
            print(f"  {name}: FAILED — {exc.details.get('errmsg', exc)}")

    print("\n" + ("Indexes verified." if ok else "Index probe failed — see above."))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
