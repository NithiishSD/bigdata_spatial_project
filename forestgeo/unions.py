"""Geometric union in Shapely, with the result stored back in MongoDB.

Why this module exists: MongoDB has NO union operator. It can test spatial
relationships ($geoWithin, $geoIntersects) but it cannot construct new geometry by
merging shapes. So the union is computed in Shapely, in the metric CRS, then written
into the derived_zones collection where ordinary MongoDB operators can query it.

All four zones:
  habitat_block         forests merged into continuous blocks (gaps closed)
  burn_risk_footprint   hotspots buffered by 1 km and merged
  habitat_buffer        habitat_block grown outward by 2 km
  critical_zone         burn_risk_footprint INTERSECTED with habitat_buffer
"""

from __future__ import annotations

import datetime as dt

import shapely
from pymongo.database import Database
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry

from forestgeo import geo
from forestgeo.config import (HABITAT_BUFFER_M, HABITAT_GAP_CLOSE_M, HOTSPOT_BUFFER_M,
                              MIN_HABITAT_BLOCK_KM2)

COLLECTION = "derived_zones"
SIMPLIFY_M = 20            # derived zones are for analysis and display, not survey
MAX_DOC_MB = 12            # BSON documents are capped at 16 MB; stay well clear


def _load_geoms(db: Database, collection: str, query: dict | None = None):
    """Read geometries out of MongoDB as Shapely objects."""
    cur = db[collection].find(query or {}, {"geometry": 1})
    return [shapely.geometry.shape(d["geometry"]) for d in cur]


def _store(db: Database, zone_type: str, geom: BaseGeometry, params: dict,
           input_count: int) -> dict:
    """Write one derived zone, replacing any previous version of the same type."""
    coll = db[COLLECTION]
    coll.create_index([("geometry", "2dsphere")], name="geometry_2dsphere")
    coll.create_index([("zone_type", 1)])
    coll.delete_many({"zone_type": zone_type})        # idempotent

    parts = list(geo.flatten(geom))
    doc = {
        "source": "computed",
        "source_id": zone_type,
        "zone_type": zone_type,
        "params": params,
        "input_count": input_count,
        "n_parts": len(parts),
        "area_km2": round(geo.area_km2(geom), 4),
        "geometry": mapping(geom),
        "created_at": dt.datetime.now(dt.timezone.utc),
    }
    size_mb = len(str(doc["geometry"])) / 1e6
    if size_mb > MAX_DOC_MB:
        raise ValueError(f"{zone_type} geometry is ~{size_mb:.1f} MB; "
                         "raise SIMPLIFY_M or split into parts")
    coll.insert_one(doc)
    return {"zone_type": zone_type, "input_count": input_count,
            "n_parts": len(parts), "area_km2": doc["area_km2"],
            "size_mb": round(size_mb, 2)}


def build_habitat_block(db: Database) -> dict:
    """Merge forest polygons into continuous habitat, closing small gaps.

    The buffer(+50) then buffer(-50) trick is a morphological CLOSING. Two forest
    patches separated by a 30 m gap - a track, or just a mapping seam - are not
    ecologically separate, but as polygons they are disjoint. Growing both by 50 m
    makes them touch and merge; shrinking the merged shape back by 50 m restores the
    original outline with the gap now sealed. Done in metres, never degrees.
    """
    forests = _load_geoms(db, "forests")
    if not forests:
        raise ValueError("no forests loaded")

    metric = [geo.to_metric(g) for g in forests]
    grown = [g.buffer(HABITAT_GAP_CLOSE_M) for g in metric]
    merged = shapely.union_all(grown)                     # the actual union
    closed = merged.buffer(-HABITAT_GAP_CLOSE_M)          # shrink back

    kept = [p for p in geo.flatten(closed)
            if p.geom_type == "Polygon" and p.area / 1e6 >= MIN_HABITAT_BLOCK_KM2]
    if not kept:
        kept = [p for p in geo.flatten(closed) if p.geom_type == "Polygon"]
    block = shapely.union_all(kept).simplify(SIMPLIFY_M, preserve_topology=True)

    wgs = geo.clean_geometry(geo.to_wgs84(block), "polygon")
    wgs = geo.clip_to_bbox(wgs)
    wgs = geo.clean_geometry(wgs, "polygon")
    return _store(db, "habitat_block", wgs, {
        "gap_close_m": HABITAT_GAP_CLOSE_M,
        "min_block_km2": MIN_HABITAT_BLOCK_KM2,
        "simplify_m": SIMPLIFY_M,
    }, len(forests))


def build_burn_risk_footprint(db: Database) -> dict:
    """Buffer every fire hotspot by 1 km and merge the circles into one footprint.

    A hotspot is the centre of a 375 m VIIRS pixel, not an exact ignition point, so a
    1 km buffer (about three pixel widths) represents that positional uncertainty
    honestly. Merging the overlapping circles converts 1,564 points into the area
    plausibly affected by fire.
    """
    hotspots = _load_geoms(db, "fire_hotspots")
    if not hotspots:
        raise ValueError("no fire hotspots loaded")

    circles = [geo.to_metric(g).buffer(HOTSPOT_BUFFER_M) for g in hotspots]
    merged = shapely.union_all(circles).simplify(SIMPLIFY_M, preserve_topology=True)
    wgs = geo.clean_geometry(geo.to_wgs84(merged), "polygon")
    wgs = geo.clean_geometry(geo.clip_to_bbox(wgs), "polygon")
    return _store(db, "burn_risk_footprint", wgs, {
        "buffer_m": HOTSPOT_BUFFER_M,
        "simplify_m": SIMPLIFY_M,
        "fire_season": "see config.FIRE_SEASON",
    }, len(hotspots))


def build_habitat_buffer(db: Database) -> dict:
    """Grow the habitat block outward by 2 km - the zone of influence around habitat."""
    blocks = _load_geoms(db, COLLECTION, {"zone_type": "habitat_block"})
    if not blocks:
        raise ValueError("habitat_block missing - build it first")
    grown = geo.to_metric(blocks[0]).buffer(HABITAT_BUFFER_M)
    grown = grown.simplify(SIMPLIFY_M, preserve_topology=True)
    wgs = geo.clean_geometry(geo.to_wgs84(grown), "polygon")
    wgs = geo.clean_geometry(geo.clip_to_bbox(wgs), "polygon")
    return _store(db, "habitat_buffer", wgs,
                  {"buffer_m": HABITAT_BUFFER_M, "from": "habitat_block"}, 1)


def build_critical_zone(db: Database) -> dict:
    """burn_risk_footprint INTERSECT habitat_buffer - fire pressure meeting habitat.

    This is the cross-theme geometry: areas that both burned and sit within reach of
    continuous forest. Intersection, like union, has no MongoDB operator.
    """
    burn = _load_geoms(db, COLLECTION, {"zone_type": "burn_risk_footprint"})
    hab = _load_geoms(db, COLLECTION, {"zone_type": "habitat_buffer"})
    if not burn or not hab:
        raise ValueError("burn_risk_footprint and habitat_buffer must exist first")

    inter = geo.to_metric(burn[0]).intersection(geo.to_metric(hab[0]))
    if inter.is_empty:
        raise ValueError("critical zone is empty - the two zones do not overlap")
    wgs = geo.clean_geometry(geo.to_wgs84(inter), "polygon")
    wgs = geo.clean_geometry(geo.clip_to_bbox(wgs), "polygon")
    return _store(db, "critical_zone", wgs,
                  {"operation": "burn_risk_footprint INTERSECT habitat_buffer"}, 2)


def build_all(db: Database) -> list[dict]:
    """Build the four zones in dependency order."""
    return [
        build_habitat_block(db),
        build_burn_risk_footprint(db),
        build_habitat_buffer(db),      # needs habitat_block
        build_critical_zone(db),       # needs the two above
    ]


def zone(db: Database, zone_type: str) -> dict | None:
    """Fetch one derived zone document."""
    return db[COLLECTION].find_one({"zone_type": zone_type})
