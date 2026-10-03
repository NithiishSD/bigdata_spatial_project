"""Phase 2 sanity checks for the geometry helpers."""

import shapely
from shapely.geometry import LineString, MultiPolygon, Point, Polygon

from forestgeo import config
from forestgeo.geo import (area_km2, as_point, buffer_m, clean_geometry, clip_to_bbox,
                           flatten, in_bbox, simplify_m, to_metric, to_wgs84)

CENTRE = config.bbox_centre()


def test_metric_crs_matches_region():
    assert config.utm_epsg(*CENTRE) == config.CRS_METRIC


def test_roundtrip_reprojection_is_lossless():
    p = Point(*CENTRE)
    back = to_wgs84(to_metric(p))
    assert abs(back.x - p.x) < 1e-7 and abs(back.y - p.y) < 1e-7


def test_lon_lat_order_not_swapped():
    """A (lon, lat) in the Nilgiris must land in UTM 43N's plausible easting/northing."""
    x, y = to_metric(Point(*CENTRE)).coords[0]
    assert 600_000 < x < 800_000
    assert 1_200_000 < y < 1_320_000


def test_buffer_in_metres_gives_expected_area():
    """A 1 km buffer around a point is ~pi km^2 — proves we buffer in metres, not degrees."""
    circle = buffer_m(Point(*CENTRE), 1000)
    assert abs(area_km2(circle) - 3.1416) < 0.01


def test_clean_geometry_fixes_bowtie():
    bowtie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])  # self-intersecting
    assert not bowtie.is_valid
    cleaned = clean_geometry(bowtie, "polygon")
    assert cleaned is not None and cleaned.is_valid


def test_clean_geometry_drops_foreign_family():
    assert clean_geometry(LineString([(0, 0), (1, 1)]), "polygon") is None
    assert clean_geometry(Point(0, 0), "line") is None


def test_clean_geometry_keeps_polygon_from_collection():
    """make_valid can emit a GeometryCollection; only the polygon part should survive."""
    coll = shapely.GeometryCollection([Polygon([(0, 0), (0, 1), (1, 1), (1, 0)]),
                                       LineString([(2, 2), (3, 3)])])
    cleaned = clean_geometry(coll, "polygon")
    assert cleaned is not None and cleaned.geom_type in ("Polygon", "MultiPolygon")


def test_clean_geometry_rounds_to_six_decimals():
    cleaned = clean_geometry(Point(76.1234567891, 11.9876543219), "point")
    lon, lat = cleaned.coords[0]
    assert lon == round(lon, config.COORD_PRECISION)
    assert lat == round(lat, config.COORD_PRECISION)


def test_clean_geometry_removes_repeated_points():
    line = LineString([(0, 0), (0, 0), (1, 1)])
    cleaned = clean_geometry(line, "line")
    assert len(cleaned.coords) == 2


def test_as_point_falls_inside_polygon():
    poly = Polygon([(0, 0), (0, 2), (2, 2), (2, 0)])
    pt = as_point(poly)
    assert pt.geom_type == "Point" and poly.contains(pt)


def test_flatten_multipolygon():
    mp = MultiPolygon([Polygon([(0, 0), (0, 1), (1, 1)]), Polygon([(2, 2), (2, 3), (3, 3)])])
    assert len(list(flatten(mp))) == 2


def test_bbox_clip():
    w, s, e, n = config.BBOX
    inside = Point((w + e) / 2, (s + n) / 2)
    outside = Point(w - 1, s - 1)
    assert in_bbox(inside) and not in_bbox(outside)
    assert clip_to_bbox(outside) is None
    # A line half in, half out is cut at the boundary.
    crossing = LineString([(w - 0.5, (s + n) / 2), ((w + e) / 2, (s + n) / 2)])
    clipped = clip_to_bbox(crossing)
    assert clipped is not None and clipped.bounds[0] >= w - 1e-9


def test_simplify_reduces_vertices():
    pts = [(76.3 + i * 0.0001, 11.3 + (i % 2) * 0.00005) for i in range(200)]
    line = LineString(pts)
    assert len(simplify_m(line, 50).coords) < len(line.coords)
