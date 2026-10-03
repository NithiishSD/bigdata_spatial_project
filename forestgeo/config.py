"""Single source of truth for region, CRS codes, collection names and env config.

Every other module imports its constants from here. Changing the region means
changing BBOX *and* CRS_METRIC (see utm_epsg below).
"""

from __future__ import annotations

import os
from math import floor

from dotenv import load_dotenv

load_dotenv()

# --- Study region -----------------------------------------------------------
REGION_NAME = "The Nilgiris"
BBOX = (76.20, 11.10, 77.10, 11.70)  # (west, south, east, north) in WGS84 degrees

# --- Coordinate reference systems ------------------------------------------
CRS_WGS84 = "EPSG:4326"   # storage CRS — what MongoDB GeoJSON requires
CRS_METRIC = "EPSG:32643"  # WGS84 / UTM 43N — all buffers, areas and unions

# --- Analysis parameters ----------------------------------------------------
FIRE_SEASON = ("2024-01-01", "2024-05-31")
HOTSPOT_BUFFER_M = 1000      # burn-risk buffer around each hotspot
HABITAT_GAP_CLOSE_M = 50     # close small gaps between adjacent forest polygons
HABITAT_BUFFER_M = 2000      # habitat block -> habitat_buffer zone
NEAR_VILLAGE_M = 5000        # $nearSphere radius villages <-> hotspots
NEAR_ROAD_M = 500            # $nearSphere radius sightings <-> roads
MIN_HABITAT_BLOCK_KM2 = 1.0  # drop habitat fragments smaller than this
SIMPLIFY_TOLERANCE_M = 10    # polygon simplification in the metric CRS
COORD_PRECISION = 6          # decimal places kept on stored coordinates
GBIF_MAX_UNCERTAINTY_M = 1000

EARTH_RADIUS_KM = 6378.1  # for $centerSphere: radians = km / EARTH_RADIUS_KM

# --- Database ---------------------------------------------------------------
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB = os.getenv("MONGODB_DB", "forestgeo")
FIRMS_MAP_KEY = os.getenv("FIRMS_MAP_KEY")

# --- Collections ------------------------------------------------------------
# name -> expected geometry family ("point" | "line" | "polygon")
COLLECTIONS: dict[str, str] = {
    "villages": "point",
    "fire_hotspots": "point",
    "sightings": "point",
    "transport": "line",
    "rivers": "line",
    "protected_areas": "polygon",
    "forests": "polygon",
    "water_bodies": "polygon",
    "farmland": "polygon",
    "derived_zones": "polygon",
}
SOURCE_COLLECTIONS = [c for c in COLLECTIONS if c != "derived_zones"]
BENCH_COLLECTION = "bench_points"

# --- Paths ------------------------------------------------------------------
from pathlib import Path  # noqa: E402  (kept next to the paths it defines)

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
OUTPUT_DIR = ROOT / "outputs"


def utm_epsg(lon: float, lat: float) -> str:
    """EPSG code of the UTM zone containing (lon, lat). Used to sanity-check CRS_METRIC."""
    zone = floor((lon + 180) / 6) + 1
    return f"EPSG:{(32600 if lat >= 0 else 32700) + zone}"


def bbox_centre() -> tuple[float, float]:
    """(lon, lat) centre of BBOX."""
    w, s, e, n = BBOX
    return (w + e) / 2, (s + n) / 2


def ensure_dirs() -> None:
    for d in (RAW_DIR, PROCESSED_DIR, OUTPUT_DIR):
        d.mkdir(parents=True, exist_ok=True)
