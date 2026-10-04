import os

from math import floor
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

REGION_NAME="The Nilgiris"
#Bounding box min Longitude, min Latitude, max Longitude, max Latitude
BBOX=(76.20,11.10,77.10,11.70)  #(west,south,east,north) in wgs84 (world geodetic system 1984 standard global coordinate reference system used by GPS and most web maps.)
#Coordinates: positions are given as latitude and longitude in decimal degrees (EPSG code 4326).
#Longitude: -180 to 180 (west to east)
#Latitude: -90 to 90 (south to north)
#West = 76.20°E (min longitude)
#South = 11.10°N (min latitude)
#East = 77.10°E (max longitude)
#North = 11.70°N (max latitude)

#osmnx (osm openstreetmap + nx networkx )
#Coordinate Reference System — the framework that tells GIS software how coordinates in your data map to real locations on Earth
#the two coordinate system
CRS_WGS84 = "EPSG:4326"    # storage CRS — degrees; what MongoDB requires
CRS_METRIC = "EPSG:32643"  # UTM zone 43N — metres; for buffers, areas, distances

#analysis parameter

FIRE_SEASON = ("2024-01-01", "2024-05-31")
HOTSPOT_BUFFER_M = 1000      # burn-risk buffer around each fire hotspot
HABITAT_GAP_CLOSE_M = 50     # close small gaps between adjacent forest polygons
HABITAT_BUFFER_M = 2000       # habitat block grown outward -> habitat_buffer zone
NEAR_VILLAGE_M = 5000        # search radius: villages around a hotspot
NEAR_ROAD_M = 500            # search radius: roads around a sighting

#note these are in meters _m specify meters
SIMPLIFY_TOLERANCE_M = 10     # polygon simplification, applied in the metric CRS
COORD_PRECISION = 6           # decimal places kept on stored coordinates
GBIF_MAX_UNCERTAINTY_M = 1000 # discard sightings vaguer than this
EARTH_RADIUS_KM = 6378.1      # $centerSphere wants radians = km / this  $maxDistance with $nearSphere on GeoJSON is in metres, but $centerSphere takes a radius in radians.
MIN_HABITAT_BLOCK_KM2 = 1.0  # discard habitat fragments smaller than this (km2)

#secerets

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB = os.getenv("MONGODB_DB", "forestgeo")
FIRMS_MAP_KEY = os.getenv("FIRMS_MAP_KEY") #this is NASA FIRMS(fire information for resource management system)

#collection


COLLECTIONS = {
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

# Synthetic collection used only by the index benchmark. Not a real theme, so it
# is kept out of COLLECTIONS and never appears in the load/verify reports.
BENCH_COLLECTION = "bench_points"

#these collectoins define the validation of datatype for each theme/location type since OSM is messy and provide a lot of data for a single request so to remove unnecessay we go for this
#GIS (Geographic Information System)

#paths
ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
OUTPUT_DIR = ROOT / "outputs"


#helper function
#UTM (Universal Transverse Mercator) used to measue the area in meters ratehr than lat or long
#India spans six UTM zones (42N–47N) in the WGS 84 datum.wgs 84 84 is teh version
#epsg is a registry to indentify a utm of a country
#these both are to ensure the crs_metrix are correct
def utm_epsg(lon: float, lat: float) -> str:
    """EPSG code of the UTM zone containing (lon, lat)."""
    zone = floor((lon + 180) / 6) + 1
    return f"EPSG:{(32600 if lat >= 0 else 32700) + zone}"

#used to get regios midpoint
def bbox_centre() -> tuple[float, float]:
    """(lon, lat) centre of BBOX."""
    west, south, east, north = BBOX
    return (west + east) / 2, (south + north) / 2