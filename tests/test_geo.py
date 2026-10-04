"""Tests for the geometry helpers.

These target the failures that produce NO exception - a swapped axis order, a buffer
computed in degrees, an invalid polygon reaching MongoDB. Those are the bugs that cost
hours, so they are the ones worth testing.
"""

import shapely
from shapely.geometry import LineString, MultiPolygon, Point, Polygon

from forestgeo import config
from forestgeo.geo import (area_km2, as_point, buffer_m, clean_geometry, clip_to_bbox,
                           flatten, in_bbox, length_km, simplify_m, to_metric, to_wgs84)

CENTRE = config.bbox_centre()


# --------------------------------------------------------------- CRS behaviour

def test_metric_crs_matches_region():
    """CRS_METRIC must be the UTM zone containing the region, or distances are wrong."""
    assert config.utm_epsg(*CENTRE) == config.CRS_METRIC


def test_reprojection_roundtrip_is_lossless():
    p = Point(*CENTRE)
    back = to_wgs84(to_metric(p))
    assert abs(back.x - p.x) < 1e-7
    assert abs(back.y - p.y) < 1e-7


def test_lon_lat_order_not_swapped():
    """A Nilgiris (lon, lat) must land in UTM 43N's plausible easting/northing window."""
    x, y = to_metric(Point(*CENTRE)).coords[0]
    assert 600_000 < x < 800_000, f"easting {x} implies swapped lon/lat"
    assert 1_200_000 < y < 1_320_000, f"northing {y} implies swapped lon/lat"


def test_buffer_is_in_metres_not_degrees():
    """A 1 km buffer must have area ~pi km2. In degrees it would be ~38,000 km2."""
    assert abs(area_km2(buffer_m(Point(*CENTRE), 1000)) - 3.1416) < 0.01


def test_length_in_km():
    """One degree of latitude is ~111 km."""
    line = LineString([(76.65, 11.0), (76.65, 12.0)])
    assert 110 < length_km(line) < 112


# ------------------------------------------------------------------- cleaning

def test_clean_geometry_fixes_self_intersection():
    bowtie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])
    assert not bowtie.is_valid
    cleaned = clean_geometry(bowtie, "polygon")
    assert cleaned is not None and cleaned.is_valid


def test_clean_geometry_drops_wrong_family():
    """A bus-stop Point in the transport layer must not survive as a line."""
    assert clean_geometry(Point(0, 0), "line") is None
    assert clean_geometry(LineString([(0, 0), (1, 1)]), "polygon") is None


def test_clean_geometry_keeps_only_polygon_from_collection():
    """make_valid can emit a GeometryCollection; only the polygon part should remain."""
    coll = shapely.GeometryCollection([Polygon([(0, 0), (0, 1), (1, 1), (1, 0)]),
                                       LineString([(2, 2), (3, 3)])])
    cleaned = clean_geometry(coll, "polygon")
    assert cleaned is not None
    assert cleaned.geom_type in ("Polygon", "MultiPolygon")


def test_clean_geometry_rounds_coordinates():
    cleaned = clean_geometry(Point(76.1234567891, 11.9876543219), "point")
    lon, lat = cleaned.coords[0]
    assert lon == round(lon, config.COORD_PRECISION)
    assert lat == round(lat, config.COORD_PRECISION)


def test_clean_geometry_removes_repeated_points():
    cleaned = clean_geometry(LineString([(0, 0), (0, 0), (1, 1)]), "line")
    assert len(cleaned.coords) == 2


def test_clean_geometry_rejects_empty_and_none():
    assert clean_geometry(None, "point") is None
    assert clean_geometry(Polygon(), "polygon") is None


# ------------------------------------------------------------ type conversions

def test_as_point_falls_inside_concave_polygon():
    """The real reason for representative_point(): a centroid can land outside."""
    c_shape = Polygon([(0, 0), (3, 0), (3, 1), (1, 1), (1, 2), (3, 2), (3, 3),
                       (0, 3), (0, 0)])
    assert not c_shape.contains(c_shape.centroid)      # centroid escapes
    pt = as_point(c_shape)
    assert pt.geom_type == "Point"
    assert c_shape.contains(pt)                        # representative point does not


def test_flatten_multipolygon():
    mp = MultiPolygon([Polygon([(0, 0), (0, 1), (1, 1)]),
                       Polygon([(2, 2), (2, 3), (3, 3)])])
    assert len(list(flatten(mp))) == 2


# ----------------------------------------------------------------- bbox clipping

def test_in_bbox():
    west, south, east, north = config.BBOX
    assert in_bbox(Point((west + east) / 2, (south + north) / 2))
    assert not in_bbox(Point(west - 1, south - 1))


def test_clip_removes_outside_and_trims_crossing():
    west, south, east, north = config.BBOX
    mid_lat = (south + north) / 2
    assert clip_to_bbox(Point(west - 1, south - 1)) is None
    crossing = LineString([(west - 0.5, mid_lat), ((west + east) / 2, mid_lat)])
    clipped = clip_to_bbox(crossing)
    assert clipped is not None
    assert clipped.bounds[0] >= west - 1e-9      # trimmed at the western edge


def test_clip_reduces_area_of_overlapping_polygon():
    """Mirrors the real finding: ~42% of fetched forest area lay outside the bbox."""
    west, south, east, north = config.BBOX
    straddling = Polygon([(west - 0.2, south - 0.2), (west + 0.2, south - 0.2),
                          (west + 0.2, south + 0.2), (west - 0.2, south + 0.2)])
    assert area_km2(clip_to_bbox(straddling)) < area_km2(straddling)


def test_simplify_reduces_vertices():
    pts = [(76.3 + i * 0.0001, 11.3 + (i % 2) * 0.00005) for i in range(200)]
    line = LineString(pts)
    assert len(simplify_m(line, 50).coords) < len(line.coords)
