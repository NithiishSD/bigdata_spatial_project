"""Fetch OpenStreetMap layers for the study region via osmnx (Overpass API). No API key."""

from __future__ import annotations

import logging
import time

import geopandas as gpd
import osmnx as ox
import pandas as pd
from osmnx._errors import InsufficientResponseError

from forestgeo.config import BBOX, CRS_WGS84, RAW_DIR

log = logging.getLogger(__name__)

ox.settings.use_cache = True
ox.settings.cache_folder = "cache"
ox.settings.requests_timeout = 300

# OSM tag selectors per target collection. See docs/03_DATA_ACQUISITION.md §1.
LAYERS: dict[str, dict] = {
    "villages": {"place": ["village", "hamlet", "town"]},
    "transport": {
        "highway": ["motorway", "trunk", "primary", "secondary", "tertiary",
                    "unclassified", "residential", "track"],
        "railway": ["rail", "narrow_gauge", "light_rail"],
    },
    "rivers": {"waterway": ["river", "stream"]},
    "protected_areas": {"boundary": ["protected_area", "national_park"],
                        "leisure": "nature_reserve"},
    "forests": {"landuse": "forest", "natural": "wood"},
    "water_bodies": {"natural": "water", "landuse": "reservoir"},
    "farmland": {"landuse": ["farmland", "orchard"]},
}

# Only these tag columns are kept — OSM returns hundreds.
KEEP_COLS = [
    "element", "id", "name", "place", "highway", "railway", "waterway",
    "landuse", "natural", "boundary", "leisure", "protect_class",
    "protection_title", "water", "surface", "tracktype", "geometry",
]


def _tiles(bbox: tuple[float, float, float, float], n: int = 2):
    """Split a bbox into an n x n grid — the fallback when Overpass times out."""
    w, s, e, nn = bbox
    dx, dy = (e - w) / n, (nn - s) / n
    return [(w + i * dx, s + j * dy, w + (i + 1) * dx, s + (j + 1) * dy)
            for i in range(n) for j in range(n)]


def _features(bbox, tags) -> gpd.GeoDataFrame:
    """osmnx 2.x takes bbox as (left, bottom, right, top)."""
    return ox.features_from_bbox(bbox=bbox, tags=tags)


def _empty() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame({"id": [], "name": []}, geometry=[], crs=CRS_WGS84)


def fetch_layer(name: str, bbox=BBOX, save: bool = True) -> gpd.GeoDataFrame:
    """Fetch one OSM layer. Falls back to 2x2 tiles if the single request fails."""
    tags = LAYERS[name]
    try:
        gdf = _features(bbox, tags)
    except InsufficientResponseError:
        # Genuinely nothing tagged this way in the bbox — not an error. Tiling cannot help.
        log.warning("%s: no matching features in bbox %s — writing empty layer", name, bbox)
        gdf = _empty()
    except Exception as exc:  # Overpass timeout / 429
        log.warning("%s: single-request fetch failed (%s) — retrying as 2x2 tiles", name, exc)
        frames = []
        ok = 0
        for i, tile in enumerate(_tiles(bbox), 1):
            try:
                frames.append(_features(tile, tags))
                ok += 1
                log.info("  tile %d/4 ok (%d features)", i, len(frames[-1]))
            except InsufficientResponseError:
                ok += 1  # empty tile counts as a successful query
                log.info("  tile %d/4 empty", i)
            except Exception as texc:
                log.warning("  tile %d/4 failed: %s", i, texc)
            time.sleep(2)
        if ok == 0:
            raise RuntimeError(f"all Overpass attempts failed for layer {name!r}") from exc
        gdf = (gpd.GeoDataFrame(pd.concat(frames), crs=CRS_WGS84) if frames else _empty())

    if gdf.empty:
        if save:
            out = RAW_DIR / f"osm_{name}.geojson"
            gdf.to_file(out, driver="GeoJSON")
        return gdf

    gdf = gdf.reset_index()  # MultiIndex (element, id) -> columns
    if "id" in gdf.columns:
        gdf = gdf.drop_duplicates(subset="id")
    cols = [c for c in KEEP_COLS if c in gdf.columns]
    gdf = gpd.GeoDataFrame(gdf[cols], geometry="geometry", crs=CRS_WGS84)

    log.info("%s: %d features | geometry types: %s", name, len(gdf),
             dict(gdf.geometry.geom_type.value_counts()))
    if save:
        out = RAW_DIR / f"osm_{name}.geojson"
        gdf.to_file(out, driver="GeoJSON")
        log.info("%s: wrote %s", name, out)
    return gdf


def fetch_all(bbox=BBOX) -> dict[str, gpd.GeoDataFrame]:
    """Fetch every OSM layer, one at a time (kinder to Overpass than parallel requests)."""
    out = {}
    for name in LAYERS:
        log.info("--- OSM layer: %s ---", name)
        out[name] = fetch_layer(name, bbox=bbox)
        time.sleep(2)
    return out
