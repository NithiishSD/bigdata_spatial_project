"""Geometry helpers: validate, clean, reproject, buffer, measure.

Two rules drive this module:
  * geometries are STORED in EPSG:4326 (degrees), because that is what MongoDB's
    2dsphere index requires;
  * anything MEASURED in metres - buffers, areas, lengths, simplification - happens
    in EPSG:32643 (UTM zone 43N). Never buffer or compute area in degrees.
"""

from __future__ import annotations

from typing import Iterator, Literal

import shapely
from pyproj import Transformer
from shapely.geometry import MultiLineString, MultiPolygon, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform

from forestgeo.config import BBOX, COORD_PRECISION, CRS_METRIC, CRS_WGS84

Family = Literal["point", "line", "polygon"]

# always_xy=True is mandatory. It makes the transformers accept and return
# (longitude, latitude) / (easting, northing) - the same axis order GeoJSON uses.
# Without it, pyproj honours each CRS's declared axis order, and EPSG:4326 declares
# LATITUDE FIRST, so every coordinate silently comes out swapped.
_to_m = Transformer.from_crs(CRS_WGS84, CRS_METRIC, always_xy=True).transform
_to_ll = Transformer.from_crs(CRS_METRIC, CRS_WGS84, always_xy=True).transform

# The single-part geometry type each family is allowed to contain.
BASE: dict[str, str] = {"point": "Point", "line": "LineString", "polygon": "Polygon"}

# Coordinate snapping grid: 1e-6 degrees is about 0.11 m at the equator.
GRID = 10.0 ** -COORD_PRECISION


# --------------------------------------------------------------- reprojection

def to_metric(g: BaseGeometry) -> BaseGeometry:
    """EPSG:4326 (degrees) -> EPSG:32643 (metres)."""
    return transform(_to_m, g)


def to_wgs84(g: BaseGeometry) -> BaseGeometry:
    """EPSG:32643 (metres) -> EPSG:4326 (degrees)."""
    return transform(_to_ll, g)


# ------------------------------------------------------------------ inspection

def flatten(g: BaseGeometry) -> Iterator[BaseGeometry]:
    """Yield single-part geometries from Multi*/GeometryCollection, recursively."""
    if hasattr(g, "geoms"):
        for part in g.geoms:
            yield from flatten(part)
    else:
        yield g


# -------------------------------------------------------------------- cleaning

def _keep_family(g: BaseGeometry, family: Family) -> BaseGeometry | None:
    """Keep only the parts matching the expected geometry family.

    make_valid() can turn one broken polygon into a GeometryCollection holding a
    polygon plus a stray line. MongoDB would index that, but every query in this
    project assumes one family per collection, so the strays are dropped here.
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

    Pipeline: make_valid -> keep family -> snap to grid -> drop repeated points.
    Every geometry must pass through here before insert.
    """
    if g is None or g.is_empty:
        return None
    if not g.is_valid:
        # Fixes self-intersections, bow-ties and unclosed rings. Without this,
        # MongoDB rejects the document with "Can't extract geo keys ... Edges cross".
        g = shapely.make_valid(g)
    kept = _keep_family(g, family)
    if kept is None:
        return None
    # set_precision rounds coordinates onto the grid and removes the near-duplicate
    # vertices that trigger MongoDB's "Duplicate vertices" error.
    snapped = shapely.set_precision(kept, GRID)
    snapped = shapely.remove_repeated_points(snapped)
    if snapped.is_empty:
        return None
    if not snapped.is_valid:
        snapped = shapely.make_valid(snapped)
    # Snapping can collapse a thin polygon into a line, so re-check the family.
    return _keep_family(snapped, family)


# ----------------------------------------------------------- metric operations

def simplify_m(g: BaseGeometry, tol_m: float) -> BaseGeometry:
    """Simplify with a tolerance in METRES (performed in the metric CRS)."""
    return to_wgs84(to_metric(g).simplify(tol_m, preserve_topology=True))


def buffer_m(g: BaseGeometry, dist_m: float, **kwargs) -> BaseGeometry:
    """Buffer by METRES. Positive grows, negative shrinks. In and out are WGS84."""
    return to_wgs84(to_metric(g).buffer(dist_m, **kwargs))


def area_km2(g: BaseGeometry) -> float:
    """Area in square kilometres, measured in the metric CRS."""
    return to_metric(g).area / 1e6


def length_km(g: BaseGeometry) -> float:
    """Length in kilometres, measured in the metric CRS."""
    return to_metric(g).length / 1000


# ------------------------------------------------------------------- bbox work

def bbox_polygon(bbox=BBOX) -> Polygon:
    """The study-region bounding box as a WGS84 polygon."""
    west, south, east, north = bbox
    return box(west, south, east, north)


def in_bbox(g: BaseGeometry | None, bbox=BBOX) -> bool:
    """True if the geometry touches the study region at all."""
    return g is not None and not g.is_empty and g.intersects(bbox_polygon(bbox))


def clip_to_bbox(g: BaseGeometry | None, bbox=BBOX) -> BaseGeometry | None:
    """Intersect with the study region. Returns None if nothing remains.

    Essential: Overpass returns the COMPLETE geometry of any feature touching the
    bbox, so ~42% of the fetched forest area and ~48% of protected-area extent lies
    outside the study region. Without clipping, every area statistic is inflated.
    """
    if g is None or g.is_empty:
        return None
    clipped = g.intersection(bbox_polygon(bbox))
    return None if clipped.is_empty else clipped


# ------------------------------------------------------------ type conversions

def as_point(g: BaseGeometry | None) -> BaseGeometry | None:
    """Collapse any geometry to a representative Point.

    44 of 421 OSM villages are mapped as area boundaries rather than nodes. They must
    be converted, not discarded. representative_point() is used instead of centroid()
    because for a concave shape - a village wrapped around a hillside - the centroid
    can fall OUTSIDE the polygon. representative_point() is guaranteed to lie inside.
    """
    if g is None or g.is_empty:
        return None
    if g.geom_type == "Point":
        return g
    return g.representative_point()


def to_multipolygon(g: BaseGeometry) -> MultiPolygon:
    """Wrap a Polygon as a MultiPolygon so a collection's geometry type stays uniform."""
    return g if g.geom_type == "MultiPolygon" else MultiPolygon([g])
