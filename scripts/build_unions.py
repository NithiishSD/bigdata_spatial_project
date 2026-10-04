#!/usr/bin/env python
"""Phase 5 - compute the geometric unions in Shapely and store them in MongoDB.

MongoDB has no union operator, so the merging happens in Shapely (in the metric CRS)
and the results are written into derived_zones - where ordinary MongoDB operators can
then query them. The final section proves exactly that.

Run:  python scripts/build_unions.py
"""

from __future__ import annotations

import pandas as pd

from forestgeo import config
from forestgeo.db import get_db
from forestgeo.unions import build_all, zone


def main() -> int:
    db = get_db()
    print(f"Phase 5 - union & derived zones | {config.REGION_NAME}\n")

    results = build_all(db)
    rep = pd.DataFrame(results)
    print(rep.to_string(index=False))
    path = config.OUTPUT_DIR / "derived_zones_summary.csv"
    rep.to_csv(path, index=False)
    print(f"\n-> {path}")

    # The point of the whole phase: the computed geometry is now queryable in MongoDB.
    print("\nQuerying the derived zones with ordinary MongoDB operators:")
    burn = zone(db, "burn_risk_footprint")
    hab = zone(db, "habitat_block")
    crit = zone(db, "critical_zone")

    inside_burn = {"geometry": {"$geoWithin": {"$geometry": burn["geometry"]}}}
    print(f"  villages $geoWithin burn_risk_footprint : "
          f"{db.villages.count_documents(inside_burn)}")
    print(f"  sightings $geoWithin burn_risk_footprint: "
          f"{db.sightings.count_documents(inside_burn)}")

    touches_hab = {"geometry": {"$geoIntersects": {"$geometry": hab["geometry"]}}}
    print(f"  protected_areas $geoIntersects habitat_block: "
          f"{db.protected_areas.count_documents(touches_hab)}")
    print(f"  tracks $geoIntersects habitat_block         : "
          f"{db.transport.count_documents({**touches_hab, 'kind': 'track'})}")

    inside_crit = {"geometry": {"$geoWithin": {"$geometry": crit["geometry"]}}}
    print(f"  villages $geoWithin critical_zone        : "
          f"{db.villages.count_documents(inside_crit)}")

    print("\nPhase 5 complete - unions computed in Shapely, stored and queried in MongoDB.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
