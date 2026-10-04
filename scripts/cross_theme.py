#!/usr/bin/env python
"""Phase 6 - the cross-theme query: which villages are most exposed, and why.

Run:  python scripts/cross_theme.py
"""

from __future__ import annotations

from forestgeo import config
from forestgeo.cross_theme import (WEIGHTS, features_in_critical_zone,
                                   two_predicate_equivalence, village_risk)
from forestgeo.db import get_db
from forestgeo.queries import save


def main() -> int:
    db = get_db()
    print(f"Phase 6 - cross-theme query | {config.REGION_NAME}\n")

    print("What sits inside the critical zone (burn footprint INTERSECT habitat buffer):")
    feats = features_in_critical_zone(db)
    print(feats.to_string(index=False))
    save(feats, "q6_critical_zone_contents.csv")

    print(f"\nVillage risk score, weights = {WEIGHTS}")
    risk = village_risk(db)
    cols = ["village", "place", "n_hotspots_5km", "nearest_hotspot_m",
            "n_sightings_5km", "in_burn_footprint", "in_critical_zone", "risk_score"]
    print(risk[cols].head(15).to_string(index=False))
    print(f"\n  {len(risk)} villages scored | "
          f"{int(risk.in_critical_zone.sum())} in the critical zone | "
          f"{int(risk.in_burn_footprint.sum())} in the burn footprint")
    print("   ->", save(risk, "q6_village_risk.csv"))

    print("\nValidating the Shapely intersection against MongoDB's own logic:")
    eq = two_predicate_equivalence(db)
    for k, v in eq.items():
        print(f"  {k:28} {v}")
    if not eq["match"]:
        print("  !! counts differ - the intersection and the two-predicate form "
              "should agree")

    print("\nPhase 6 complete - MVP checkpoint B reached.")
    return 0 if eq["match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
