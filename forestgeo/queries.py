"""The four core spatial operations, as MongoDB queries.

Operator cheat-sheet:

  $nearSphere   sorted by distance, nearest first. REQUIRES a geospatial index and
                accepts only a Point as the reference. Cannot be used inside
                count_documents().
  $geoNear      the aggregation-pipeline form of the same thing. Its advantage is
                distanceField, which returns the computed distance in METRES. Must be
                the FIRST stage of a pipeline.
  $geoWithin    "entirely inside". No index required (falls back to a scan), can be
                counted. With $geometry it takes a polygon; with $centerSphere a
                circle whose radius is in RADIANS (km / 6378.1).
  $geoIntersects "touches, crosses, or is inside". The right operator for a line
                crossing a polygon - $geoWithin would demand the whole line be inside.

Units: $maxDistance and $geoNear distances are METRES when the reference is GeoJSON.
$centerSphere is the exception and wants radians.
"""

from __future__ import annotations

import pandas as pd
from pymongo.database import Database

from forestgeo.config import EARTH_RADIUS_KM, NEAR_ROAD_M, NEAR_VILLAGE_M, OUTPUT_DIR


def point(lon: float, lat: float) -> dict:
    """A GeoJSON Point. Coordinates are [longitude, latitude] - never the reverse."""
    return {"type": "Point", "coordinates": [lon, lat]}


def km_to_radians(km: float) -> float:
    """$centerSphere expresses its radius in radians, not metres."""
    return km / EARTH_RADIUS_KM


# ------------------------------------------------- Q1  $nearSphere / $geoNear

def villages_near_hotspots(db: Database, top_n: int = 20,
                           max_m: int = NEAR_VILLAGE_M) -> pd.DataFrame:
    """Q1 - villages within max_m of the most intense fire hotspots.

    FRP (Fire Radiative Power, in megawatts) is the intensity proxy, so the top N
    hotspots by FRP are the most severe detections of the season.

    Uses $geoNear rather than $nearSphere because distanceField gives the actual
    distance in metres, which is what the report needs.
    """
    hotspots = list(db.fire_hotspots.find(
        {"frp": {"$ne": None}},
        {"geometry": 1, "frp": 1, "acq_datetime": 1, "confidence": 1, "source_id": 1},
    ).sort("frp", -1).limit(top_n))

    rows = []
    for h in hotspots:
        lon, lat = h["geometry"]["coordinates"]
        near = db.villages.aggregate([
            {"$geoNear": {
                "near": point(lon, lat),
                "distanceField": "distance_m",   # metres, written into each result
                "maxDistance": max_m,
                "spherical": True,
            }},
        ])
        for v in near:
            rows.append({
                "hotspot_id": h["source_id"],
                "hotspot_frp_mw": h.get("frp"),
                "hotspot_date": h.get("acq_datetime"),
                "hotspot_confidence": h.get("confidence"),
                "village": v.get("name") or "(unnamed)",
                "village_place": v.get("place"),
                "distance_m": round(v["distance_m"], 1),
            })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["hotspot_frp_mw", "distance_m"],
                            ascending=[False, True]).reset_index(drop=True)
    return df


# --------------------------------------------------------- Q2  $nearSphere

def sightings_near_roads(db: Database, max_m: int = NEAR_ROAD_M,
                         precision: str = "precise",
                         exclude_roadkill: bool = True) -> pd.DataFrame:
    """Q2 - distance from each wildlife sighting to the nearest road.

    Two filters that matter methodologically:
      * precision="precise" keeps only records accurate to <= 1 km. A point that may
        be 31 km off cannot be tested against a 500 m buffer.
      * exclude_roadkill drops the Global Roadkill Data records. That dataset is
        defined by animals found on roads, so including it makes "% near a road"
        circular - it would measure the dataset's definition, not animal behaviour.
    """
    query: dict = {}
    if precision:
        query["precision"] = precision
    if exclude_roadkill:
        query["is_roadkill"] = False

    rows = []
    for s in db.sightings.find(query, {"geometry": 1, "species": 1, "class": 1,
                                       "iucn_category": 1, "gbif_id": 1,
                                       "uncertainty_m": 1}):
        lon, lat = s["geometry"]["coordinates"]
        nearest = list(db.transport.aggregate([
            {"$geoNear": {
                "near": point(lon, lat),
                "distanceField": "distance_m",
                "maxDistance": max_m,
                "spherical": True,
            }},
            {"$limit": 1},          # only the closest road is of interest
        ]))
        rows.append({
            "gbif_id": s.get("gbif_id"),
            "species": s.get("species"),
            "class": s.get("class"),
            "iucn_category": s.get("iucn_category"),
            "uncertainty_m": s.get("uncertainty_m"),
            "near_road": bool(nearest),
            "nearest_road_m": round(nearest[0]["distance_m"], 1) if nearest else None,
            "road_kind": nearest[0].get("kind") if nearest else None,
            "road_name": nearest[0].get("name") if nearest else None,
        })
    return pd.DataFrame(rows)


def sightings_near_roads_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Per-species share of sightings within the search radius of a road."""
    if df.empty:
        return df
    g = (df.groupby("species")
           .agg(n=("near_road", "size"),
                n_near=("near_road", "sum"),
                median_m=("nearest_road_m", "median"))
           .reset_index())
    g["pct_near"] = (100 * g.n_near / g.n).round(1)
    return g.sort_values(["n", "pct_near"], ascending=False).reset_index(drop=True)


# ----------------------------------------------------------- Q3  $geoWithin

def protected_area_counts(db: Database) -> pd.DataFrame:
    """Q3 - how many sightings and hotspots fall inside each protected area.

    $geoWithin with $geometry asks "is this point entirely inside that polygon?".
    It needs no index, but the 2dsphere index makes it far faster - which is exactly
    what the benchmark phase measures.
    """
    rows = []
    for pa in db.protected_areas.find({}, {"geometry": 1, "name": 1, "area_km2": 1,
                                           "protect_class": 1}):
        inside = {"geometry": {"$geoWithin": {"$geometry": pa["geometry"]}}}
        n_sight = db.sightings.count_documents(inside)
        n_hot = db.fire_hotspots.count_documents(inside)
        n_vill = db.villages.count_documents(inside)
        area = pa.get("area_km2") or 0
        rows.append({
            "protected_area": pa.get("name") or "(unnamed)",
            "protect_class": pa.get("protect_class"),
            "area_km2": round(area, 2),
            "n_sightings": n_sight,
            "n_hotspots": n_hot,
            "n_villages": n_vill,
            "sightings_per_km2": round(n_sight / area, 3) if area else None,
            "hotspots_per_km2": round(n_hot / area, 3) if area else None,
        })
    df = pd.DataFrame(rows)
    return (df.sort_values("n_hotspots", ascending=False).reset_index(drop=True)
            if not df.empty else df)


# ------------------------------------------------------- Q4  $geoIntersects

def crossings(db: Database) -> pd.DataFrame:
    """Q4 - linear features crossing protected areas and water bodies.

    $geoIntersects is required here, not $geoWithin: a road that enters a reserve and
    leaves again is not *entirely inside* it, so $geoWithin would miss it. Any shared
    point is enough for $geoIntersects.
    """
    rows = []
    for pa in db.protected_areas.find({}, {"geometry": 1, "name": 1, "area_km2": 1}):
        crosses = {"geometry": {"$geoIntersects": {"$geometry": pa["geometry"]}}}
        for kind in ("road", "track", "railway"):
            n = db.transport.count_documents({**crosses, "kind": kind})
            rows.append({"target_type": "protected_area",
                         "target": pa.get("name") or "(unnamed)",
                         "target_area_km2": round(pa.get("area_km2") or 0, 2),
                         "feature": kind,
                         "n_crossing": n})
        rows.append({"target_type": "protected_area",
                     "target": pa.get("name") or "(unnamed)",
                     "target_area_km2": round(pa.get("area_km2") or 0, 2),
                     "feature": "river",
                     "n_crossing": db.rivers.count_documents(crosses)})

    # Bridges and fords: transport lines crossing water bodies, aggregated.
    n_water_cross = 0
    for wb in db.water_bodies.find({}, {"geometry": 1}).limit(200):
        n_water_cross += db.transport.count_documents(
            {"geometry": {"$geoIntersects": {"$geometry": wb["geometry"]}}})
    rows.append({"target_type": "water_bodies (first 200)", "target": "all",
                 "target_area_km2": None, "feature": "transport",
                 "n_crossing": n_water_cross})
    return pd.DataFrame(rows)


# ------------------------------------------------- $geoWithin + $centerSphere

def count_within_km(db: Database, collection: str, lon: float, lat: float,
                    km: float) -> int:
    """Count documents within km of a point.

    $nearSphere cannot be used in count_documents(), so counting uses
    $geoWithin + $centerSphere - whose radius is in RADIANS, not metres.
    """
    return db[collection].count_documents({
        "geometry": {"$geoWithin": {"$centerSphere": [[lon, lat], km_to_radians(km)]}}
    })


def save(df: pd.DataFrame, name: str) -> str:
    """Write a result to outputs/ so the report can cite it."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / name
    df.to_csv(path, index=False)
    return str(path)
