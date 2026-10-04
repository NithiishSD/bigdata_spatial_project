"""
OSM gives 7 of your 10 collections
to access osm data we need to use overpass a api to access it(without api key) and osmnx a python wrapper used to query to osm and get the data
we get Geodatframe osm data model in teh form key=value pair

"""

import geopandas as gpd
import osmnx as ox

from forestgeo.config import BBOX, CRS_WGS84, RAW_DIR

ox.settings.use_cache = True
ox.settings.cache_folder = "cache" #to avoid re fetching same query throught network and search it in local 
ox.settings.requests_timeout = 300
#ox.settings.overpass_url = "https://overpass.kumi.systems/api"   #use this teh normal default fails with econnrefused 

LAYERS = {
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
#tehse are the information we need from each landscape
KEEP = ["element", "id", "name", "place", "highway", "railway", "waterway",
        "landuse", "natural", "boundary", "leisure", "protect_class", "water",
        "geometry"]
#we are fetching a layer
def fetch_layer(name: str, bbox=BBOX, save: bool = True) -> gpd.GeoDataFrame:
    """Fetch one OSM layer into a GeoDataFrame and save it to data/raw/."""
    gdf = ox.features_from_bbox(bbox=bbox, tags=LAYERS[name]).reset_index()

    cols = [c for c in KEEP if c in gdf.columns]
    gdf = gpd.GeoDataFrame(gdf[cols], geometry="geometry", crs=CRS_WGS84)

    print(f"{name}: {len(gdf)} features | {dict(gdf.geometry.geom_type.value_counts())}")
    if save:
        gdf.to_file(RAW_DIR / f"osm_{name}.geojson", driver="GeoJSON")
    return gdf


#sequencially request all layers
def fetch_all(bbox=BBOX) -> dict[str, gpd.GeoDataFrame]:
    """Fetch every OSM layer, one at a time."""
    return {name: fetch_layer(name, bbox=bbox) for name in LAYERS}


"""

- use_cache = True — without it, every iteration on your cleaning code means another wait on Overpass. With it, the second run is instant. You already have 16 cached responses, so some layers will return immediately.
- The osmnx 2.x bbox order — (left, bottom, right, top). Version 1.x used (north, south, east, west), so almost every tutorial you find online will silently fetch the wrong rectangle.
- The print of geometry types — when you fetch transport you'll see Point in that output. Those are bus stops. They're not a bug and you should not filter them here; that's the clean step's job, and keeping the stages separate is what lets your validation report honestly say "dropped 83 points from the transport layer".
"""