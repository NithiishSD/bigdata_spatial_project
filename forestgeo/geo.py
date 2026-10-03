"""Geometry helpers: validate, clean, reproject, buffer, measure.

Two rules drive everything here (see docs/04_QUERY_COOKBOOK.md §1):
  * geometries are *stored* in EPSG:4326 (degrees), because that is what MongoDB needs;
  * anything measured in metres — buffers, areas, distances, simplification — happens in
    EPSG:32643 (UTM 43N). Never buffer in degrees.
"""

from __future__ import annotations

import logging
from typing import Iterator, Literal

import shapely
from pyproj import Transformer
from shapely.geometry import MultiLineString, MultiPolygon, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform

from forestgeo.config import BBOX, COORD_PRECISION, CRS_METRIC, CRS_WGS84

log = logging.getLogger(__name__)

Family = Literal["point", "line", "polygon"]

# always_xy=True is mandatory: it makes the transformers take and return (lon, lat) /
# (easting, northing) — the same axis order as GeoJSON. Without it pyproj uses the
# CRS's declared order (lat, lon for EPSG:4326) and every coordinate comes out swapped.
_to_m = Transformer.from_crs(CRS_WGS84, CRS_METRIC, always_xy=True).transform
_to_ll = Transformer.from_crs(CRS_METRIC, CRS_WGS84, always_xy=True).transform

BASE: dict[str, str] = {"point": "Point", "line": "LineString", "polygon": "Polygon"}
GRID = 10.0 ** -COORD_PRECISION  # 1e-6 degrees ~= 0.11 m at the equator


def to_metric(g: BaseGeometry) -> BaseGeometry:
    """EPSG:4326 (degrees) -> EPSG:32643 (metres)."""
    return transform(_to_m, g)


def to_wgs84(g: BaseGeometry) -> BaseGeometry:
    """EPSG:32643 (metres) -> EPSG:4326 (degrees)."""
    return transform(_to_ll, g)


def flatten(g: BaseGeometry) -> Iterator[BaseGeometry]:
    """Yield single-part geometries from Multi* / GeometryCollection, recursively."""
    if hasattr(g, "geoms"):
        for part in g.geoms:
            yield from flatten(part)
    else:
        yield g


def _keep_family(g: BaseGeometry, family: Family) -> BaseGeometry | None:
    """Keep only the parts matching the expected geometry family.

    make_valid() can turn a broken polygon into a GeometryCollection holding a polygon
    plus a stray line; MongoDB would index that, but our queries assume one family.
    """
    parts = [p for p in flatten(g) if p.geom_type == BASE[family] and not p.is_empty]
    if not parts:
        return None
    if family == "point":
        return parts[0]
    if family == "line":
        return parts[0] if len(parts) == 1 else MultiLineString(parts)
    merged = shapely.union_all(parts)  # polygons: dissolve overlapping pieces
    return merged if not merged.is_empty else None


def clean_geometry(g: BaseGeometry | None, family: Family) -> BaseGeometry | None:
    """A MongoDB-safe geometry of the given family, or None if nothing usable survives.

    make_valid -> keep family -> snap to a 1e-6 degree grid -> drop repeated points.
    Every geometry must pass through here before it is inserted.
    """
    if g is None or g.is_empty:
        return None
    if not g.is_valid:
        g = shapely.make_valid(g)
    kept = _keep_family(g, family)
    if kept is None:
        return None
    # set_precision rounds coordinates to the grid and removes the near-duplicate
    # vertices that trigger MongoDB's "Duplicate vertices" / "Edges cross" errors.
    snapped = shapely.set_precision(kept, GRID)
    snapped = shapely.remove_repeated_points(snapped)
    if snapped.is_empty:
        return None
    if not snapped.is_valid:
        snapped = shapely.make_valid(snapped)
    # set_precision can collapse a polygon to a line, so re-check the family.
    return _keep_family(snapped, family)


def simplify_m(g: BaseGeometry, tol_m: float) -> BaseGeometry:
    """Simplify with a tolerance expressed in metres (performed in the metric CRS)."""
    return to_wgs84(to_metric(g).simplify(tol_m, preserve_topology=True))


def buffer_m(g: BaseGeometry, dist_m: float, **kwargs) -> BaseGeometry:
    """Buffer by metres. Positive grows, negative shrinks. Input and output are WGS84."""
    return to_wgs84(to_metric(g).buffer(dist_m, **kwargs))


def area_km2(g: BaseGeometry) -> float:
    """Area in km^2, measured in the metric CRS (never in degrees)."""
    return to_metric(g).area / 1e6


def length_km(g: BaseGeometry) -> float:
    """Length in km, measured in the metric CRS."""
    return to_metric(g).length / 1000


def bbox_polygon(bbox=BBOX) -> Polygon:
    """The study-region bbox as a WGS84 polygon — used to clip every dataset."""
    w, s, e, n = bbox
    return box(w, s, e, n)


def in_bbox(g: BaseGeometry, bbox=BBOX) -> bool:
    """True if the geometry intersects the study region at all."""
    return g is not None and not g.is_empty and g.intersects(bbox_polygon(bbox))


def clip_to_bbox(g: BaseGeometry, bbox=BBOX) -> BaseGeometry | None:
    """Intersect with the study-region bbox. Returns None if the result is empty."""
    if g is None or g.is_empty:
        return None
    clipped = g.intersection(bbox_polygon(bbox))
    return None if clipped.is_empty else clipped


def as_point(g: BaseGeometry | None) -> BaseGeometry | None:
    """Collapse any geometry to a representative Point.

    OSM tags some places as polygons (a village boundary); the villages collection is
    Point-only, so those become an interior point. representative_point() is used rather
    than centroid() because it is guaranteed to fall inside the shape.
    """
    if g is None or g.is_empty:
        return None
    if g.geom_type == "Point":
        return g
    return g.representative_point()


def to_multipolygon(g: BaseGeometry) -> MultiPolygon:
    """Wrap a Polygon as a MultiPolygon so a collection's geometry type stays uniform."""
    if g.geom_type == "MultiPolygon":
        return g
    return MultiPolygon([g])


def summarise(label: str, geoms) -> dict:
    """Quick validity/type census — used by the Phase 2 validation report."""
    geoms = [g for g in geoms if g is not None]
    types: dict[str, int] = {}
    for g in geoms:
        types[g.geom_type] = types.get(g.geom_type, 0) + 1
    n_invalid = sum(1 for g in geoms if not g.is_valid)
    log.info("%s: %d geometries %s | invalid=%d", label, len(geoms), types, n_invalid)
    return {"label": label, "n": len(geoms), "types": types, "n_invalid": n_invalid}
