"""The cross-theme query: combine fire, habitat, settlement and wildlife themes.

This is where the project's separate collections finally answer one question:
WHICH VILLAGES ARE MOST EXPOSED, and by what combination of pressures?

It exercises every operation at once - $geoWithin against computed union geometry,
$geoWithin + $centerSphere for counting inside a radius, and $geoNear for distance -
and shows two equivalent ways to express the same spatial logic.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pymongo.database import Database

from forestgeo.config import NEAR_VILLAGE_M
from forestgeo.queries import km_to_radians, point
from forestgeo.unions import zone

# Risk score weights. Deliberately simple and explicit so they can be defended and
# changed: each component is 0-1, so the score is 0-100.
WEIGHTS = {
    "in_critical_zone": 35,     # fire pressure AND habitat proximity - the worst case
    "in_burn_footprint": 25,    # inside the area plausibly affected by fire
    "hotspot_density": 25,      # how many hotspots within NEAR_VILLAGE_M, capped
    "proximity": 15,            # how close the nearest hotspot is
}
# Hotspot counts per village are heavily right-skewed (median 8, max 239), so a
# linear scale with a cap put 68 of 421 villages at the same maximum and the score
# stopped discriminating. log1p spreads the top end: 10 -> 0.44, 40 -> 0.68,
# 100 -> 0.84, 239 -> 1.00. log1p (log of 1+x) is used rather than log so that a
# village with zero hotspots maps to 0 instead of negative infinity.


def village_risk(db: Database, radius_m: int = NEAR_VILLAGE_M) -> pd.DataFrame:
    """One row per village, combining four themes into a risk score.

    For each village:
      * n_hotspots_5km  - $geoWithin + $centerSphere (radius in RADIANS)
      * nearest_hotspot_m - $geoNear, which returns the distance in metres
      * in_burn_footprint / in_habitat_buffer / in_critical_zone - $geoWithin against
        the Shapely-computed union geometry stored in derived_zones
      * n_sightings_5km - wildlife presence nearby
    """
    burn = zone(db, "burn_risk_footprint")
    hab = zone(db, "habitat_buffer")
    crit = zone(db, "critical_zone")
    if not (burn and hab and crit):
        raise ValueError("derived zones missing - run scripts/build_unions.py first")

    radius_rad = km_to_radians(radius_m / 1000)
    rows = []

    for v in db.villages.find({}, {"geometry": 1, "name": 1, "place": 1}):
        lon, lat = v["geometry"]["coordinates"]
        circle = {"$geoWithin": {"$centerSphere": [[lon, lat], radius_rad]}}

        # $nearSphere cannot be used inside count_documents(), so counting uses
        # $geoWithin + $centerSphere instead.
        n_hot = db.fire_hotspots.count_documents({"geometry": circle})
        n_sight = db.sightings.count_documents({"geometry": circle,
                                               "precision": "precise"})

        nearest = list(db.fire_hotspots.aggregate([
            {"$geoNear": {"near": point(lon, lat), "distanceField": "distance_m",
                          "spherical": True}},
            {"$limit": 1},
        ]))
        nearest_m = round(nearest[0]["distance_m"], 1) if nearest else None

        # A village is a Point, so "inside this polygon" is $geoWithin.
        here = {"_id": v["_id"]}
        in_burn = db.villages.count_documents(
            {**here, "geometry": {"$geoWithin": {"$geometry": burn["geometry"]}}}) > 0
        in_hab = db.villages.count_documents(
            {**here, "geometry": {"$geoWithin": {"$geometry": hab["geometry"]}}}) > 0
        in_crit = db.villages.count_documents(
            {**here, "geometry": {"$geoWithin": {"$geometry": crit["geometry"]}}}) > 0

        rows.append({
            "village": v.get("name") or "(unnamed)",
            "place": v.get("place"),
            "lon": lon, "lat": lat,
            "n_hotspots_5km": n_hot,
            "nearest_hotspot_m": nearest_m,
            "n_sightings_5km": n_sight,
            "in_burn_footprint": in_burn,
            "in_habitat_buffer": in_hab,
            "in_critical_zone": in_crit,
        })

    df = pd.DataFrame(rows)
    return add_risk_score(df, radius_m)


def add_risk_score(df: pd.DataFrame, radius_m: int = NEAR_VILLAGE_M) -> pd.DataFrame:
    """Combine the components into a 0-100 score. Each part is normalised to 0-1."""
    if df.empty:
        return df
    peak = max(int(df.n_hotspots_5km.max()), 1)
    density = np.log1p(df.n_hotspots_5km) / np.log1p(peak)
    # Proximity: 1 when the nearest hotspot is at the village, 0 at the search radius.
    prox = (1 - (df.nearest_hotspot_m.fillna(radius_m) / radius_m)).clip(lower=0)

    df["risk_score"] = (
        df.in_critical_zone.astype(int) * WEIGHTS["in_critical_zone"]
        + df.in_burn_footprint.astype(int) * WEIGHTS["in_burn_footprint"]
        + density * WEIGHTS["hotspot_density"]
        + prox * WEIGHTS["proximity"]
    ).round(1)
    return df.sort_values("risk_score", ascending=False).reset_index(drop=True)


def features_in_critical_zone(db: Database) -> pd.DataFrame:
    """What else sits in the critical zone, by theme and transport kind."""
    crit = zone(db, "critical_zone")
    within = {"geometry": {"$geoWithin": {"$geometry": crit["geometry"]}}}
    crosses = {"geometry": {"$geoIntersects": {"$geometry": crit["geometry"]}}}
    rows = [
        {"feature": "villages", "operator": "$geoWithin",
         "n": db.villages.count_documents(within)},
        {"feature": "sightings (precise)", "operator": "$geoWithin",
         "n": db.sightings.count_documents({**within, "precision": "precise"})},
        {"feature": "fire_hotspots", "operator": "$geoWithin",
         "n": db.fire_hotspots.count_documents(within)},
        {"feature": "farmland", "operator": "$geoIntersects",
         "n": db.farmland.count_documents(crosses)},
    ]
    for kind in ("road", "track", "railway"):
        rows.append({"feature": f"transport: {kind}", "operator": "$geoIntersects",
                     "n": db.transport.count_documents({**crosses, "kind": kind})})
    return pd.DataFrame(rows)


def two_predicate_equivalence(db: Database) -> dict:
    """Show MongoDB combining two spatial predicates gives the same answer.

    critical_zone was built in Shapely as burn_risk_footprint INTERSECT
    habitat_buffer. The same question can be asked of MongoDB directly by requiring a
    village to be inside BOTH zones. The counts should match - which validates the
    Shapely intersection against the database's own spatial reasoning.
    """
    burn = zone(db, "burn_risk_footprint")
    hab = zone(db, "habitat_buffer")
    crit = zone(db, "critical_zone")

    via_shapely = db.villages.count_documents(
        {"geometry": {"$geoWithin": {"$geometry": crit["geometry"]}}})
    via_mongo = db.villages.count_documents({"$and": [
        {"geometry": {"$geoWithin": {"$geometry": burn["geometry"]}}},
        {"geometry": {"$geoWithin": {"$geometry": hab["geometry"]}}},
    ]})
    return {"via_shapely_intersection": via_shapely,
            "via_mongodb_two_predicates": via_mongo,
            "match": via_shapely == via_mongo}
