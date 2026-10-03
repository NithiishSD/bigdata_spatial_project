# 03 — Data Acquisition (step by step)

All data is open and fetched by script, so the project is reproducible. Study region:

```python
BBOX = (76.20, 11.10, 77.10, 11.70)   # west, south, east, north  (The Nilgiris)
```

> Before fetching everything, **do a tiny test** with a small bbox (e.g. `(76.65, 11.35, 76.75, 11.45)`
> around Ooty) to check your code, then run the full region.

Write each fetcher in `forestgeo/fetch_*.py` and call them from `scripts/01_fetch_data.py`.

---

## 1. OpenStreetMap (villages, lines, polygons) — via osmnx

No API key. osmnx queries the Overpass API and returns a GeoDataFrame (EPSG:4326).

```python
# forestgeo/fetch_osm.py
import osmnx as ox
import geopandas as gpd
from forestgeo.config import BBOX

ox.settings.use_cache = True          # re-runs are instant (cache/ folder)
ox.settings.requests_timeout = 300
ox.settings.log_console = True

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
    "farmland": {"landuse": ["farmland", "orchard"]},   # tea estates are often orchard/farmland
}

def fetch_layer(name: str) -> gpd.GeoDataFrame:
    gdf = ox.features_from_bbox(bbox=BBOX, tags=LAYERS[name])   # osmnx 2.x: (left, bottom, right, top)
    gdf = gdf.reset_index()          # index → columns "element", "id"
    gdf.to_file(f"data/raw/osm_{name}.geojson", driver="GeoJSON")
    return gdf
```

**Important details**
- osmnx returns **mixed geometry types** (e.g. a `highway=bus_stop` node appears as a Point in the
  transport layer). Filter in Phase 2: lines keep `LineString/MultiLineString`, polygon layers keep
  `Polygon/MultiPolygon`, villages → Points (use `representative_point()` for polygons).
- osmnx < 2.0 used `features_from_bbox(north, south, east, west, tags)`. Check `ox.__version__`.
- Many columns (hundreds of tags). Keep only what you need: `id, element, name, highway, railway,
  waterway, place, landuse, natural, boundary, protect_class, geometry`.
- `kind` for transport: `railway` if `railway` notna, `track` if `highway == "track"`, else `road`.

**If Overpass times out / 429 "Too Many Requests"**: wait a minute; fetch one layer at a time; or
split the bbox into 4 tiles and `pd.concat` (then drop duplicate `id`s).

**Alternative (offline, bigger areas):** download the Tamil Nadu extract from Geofabrik
(https://download.geofabrik.de/asia/india.html) and read it with `pyrosm`. Only needed if Overpass fails
repeatedly.

---

## 2. NASA FIRMS fire hotspots (VIIRS 375 m)

### 2.1 Get a MAP_KEY
https://firms.modaps.eosdis.nasa.gov/api/map_key/ → enter email → key arrives immediately.
Limit: ~5000 transactions / 10 minutes (you'll use ~30).

Check key: `https://firms.modaps.eosdis.nasa.gov/mapserver/mapkey_status/?MAP_KEY=YOUR_KEY`
Check which dates each sensor has: `https://firms.modaps.eosdis.nasa.gov/api/data_availability/csv/YOUR_KEY/all`

### 2.2 Choose a source
| Source code | Use for |
|---|---|
| `VIIRS_SNPP_SP` | Historical, science-quality (use this for 2024 fire season) |
| `VIIRS_NOAA20_SP` | Second VIIRS satellite, historical (optional: more detections) |
| `VIIRS_SNPP_NRT` / `VIIRS_NOAA20_NRT` | Near-real-time, last ~2 months only |
| `MODIS_SP` | 1 km, older/coarser — only if you want a comparison |

### 2.3 Fetch in 5-day chunks
API format: `/api/area/csv/{MAP_KEY}/{SOURCE}/{west,south,east,north}/{DAY_RANGE 1-5}/{YYYY-MM-DD}`
(returns DATE … DATE + DAY_RANGE − 1).

```python
# forestgeo/fetch_firms.py
import io, os, time, datetime as dt
import pandas as pd, requests
from forestgeo.config import BBOX, FIRE_SEASON

BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

def fetch_firms(source: str = "VIIRS_SNPP_SP") -> pd.DataFrame:
    key = os.environ["FIRMS_MAP_KEY"]
    area = ",".join(str(v) for v in BBOX)
    start, end = (dt.date.fromisoformat(d) for d in FIRE_SEASON)
    frames, day = [], start
    while day <= end:
        span = min(5, (end - day).days + 1)
        url = f"{BASE}/{key}/{source}/{area}/{span}/{day:%Y-%m-%d}"
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        if not r.text.startswith("latitude"):          # errors come back as plain text
            raise RuntimeError(f"FIRMS error for {day}: {r.text[:200]}")
        frames.append(pd.read_csv(io.StringIO(r.text)))
        day += dt.timedelta(days=span)
        time.sleep(1)
    df = pd.concat(frames, ignore_index=True).drop_duplicates()
    df.to_csv("data/raw/firms_viirs.csv", index=False)
    return df
```

**Columns you'll get (VIIRS):** `latitude, longitude, bright_ti4, scan, track, acq_date, acq_time,
satellite, instrument, confidence, version, bright_ti5, frp, daynight`.

- `acq_time` is **HHMM in UTC** as an integer (e.g. `745` = 07:45). Build the timestamp:
  `pd.to_datetime(df.acq_date + " " + df.acq_time.astype(str).str.zfill(4), format="%Y-%m-%d %H%M", utc=True)`
- VIIRS `confidence` is `l` / `n` / `h` (low/nominal/high). Drop `l`. (MODIS uses 0–100.)
- `frp` = Fire Radiative Power (MW) — a proxy for intensity; use it to rank hotspots.

**Fallback:** if the API misbehaves, use the web *Archive Download* (https://firms.modaps.eosdis.nasa.gov/download/),
draw the bbox, choose VIIRS S-NPP, CSV. It emails a link. Save the CSV as `data/raw/firms_viirs.csv`.

**Tip:** Nilgiris fire season is roughly **Feb–April**. If 2024 looks sparse, try 2023 or extend to
two seasons — just update `FIRE_SEASON` in `forestgeo/config.py` and log it in
`01_PROJECT_GUIDE.md §6`.

---

## 3. GBIF wildlife sightings (includes iNaturalist)

No key needed for search. Docs: https://techdocs.gbif.org/en/openapi/v1/occurrence

```python
# forestgeo/fetch_gbif.py
import time, requests, pandas as pd
from forestgeo.config import BBOX

API = "https://api.gbif.org/v1/occurrence/search"

def bbox_wkt(b):
    w, s, e, n = b                   # counter-clockwise ring — GBIF requires CCW
    return f"POLYGON(({w} {s},{e} {s},{e} {n},{w} {n},{w} {s}))"

KEEP = ["key", "species", "scientificName", "class", "order", "family",
        "decimalLatitude", "decimalLongitude", "eventDate", "year",
        "coordinateUncertaintyInMeters", "basisOfRecord", "datasetKey",
        "datasetName", "iucnRedListCategory"]

def fetch_gbif(class_key: int, max_records: int = 20_000) -> pd.DataFrame:
    params = {
        "geometry": bbox_wkt(BBOX),
        "classKey": class_key,
        "hasCoordinate": "true",
        "hasGeospatialIssue": "false",
        "occurrenceStatus": "PRESENT",
        "year": "2015,2025",
        "limit": 300,
    }
    rows, offset = [], 0
    while offset < max_records:
        r = requests.get(API, params={**params, "offset": offset}, timeout=60)
        r.raise_for_status()
        page = r.json()
        rows += [{k: rec.get(k) for k in KEEP} for rec in page["results"]]
        if page["endOfRecords"]:
            break
        offset += 300
        time.sleep(0.2)
    return pd.DataFrame(rows)
```

Usage:
```python
mammals = fetch_gbif(359)                      # Mammalia
birds   = fetch_gbif(212, max_records=15_000)  # Aves (eBird makes this large — cap it)
pd.concat([mammals, birds]).drop_duplicates("key").to_csv("data/raw/gbif_sightings.csv", index=False)
```

- Verify a class key: `https://api.gbif.org/v1/species/match?name=Mammalia` → `classKey` / `usageKey`.
- **iNaturalist only?** add `"datasetKey": "50c9509d-22c7-4a22-a47d-8c48425ef4a7"` (iNaturalist
  Research-grade Observations). Mentioning that GBIF aggregates iNaturalist covers the brief.
- The search API stops at 100,000 records. If you need more, use the GBIF **download API** (free
  account, returns a DOI you can cite — nice for the report).
- Filter in Phase 2: `coordinateUncertaintyInMeters` ≤ 1000 (or null), drop missing species.

**Citation:** GBIF asks you to cite downloads. With the search API, cite "GBIF.org (accessed <date>)
GBIF Occurrence Search, filters: …".

---

## 4. Data inventory (write this down, the report needs it)

| Dataset | File | Rows (raw) | Rows (clean) | Date fetched | Source/licence |
|---|---|---|---|---|---|
| Villages | osm_villages.geojson | | | | OSM, ODbL |
| Transport | osm_transport.geojson | | | | OSM, ODbL |
| Rivers | osm_rivers.geojson | | | | OSM, ODbL |
| Protected areas | osm_protected_areas.geojson | | | | OSM, ODbL |
| Forests | osm_forests.geojson | | | | OSM, ODbL |
| Water bodies | osm_water_bodies.geojson | | | | OSM, ODbL |
| Farmland | osm_farmland.geojson | | | | OSM, ODbL |
| Fire hotspots | firms_viirs.csv | | | | NASA FIRMS |
| Sightings | gbif_sightings.csv | | | | GBIF.org |

Save it as `outputs/data_inventory.csv` from code so it's always accurate.

## 5. Quick sanity check snippet

```python
import geopandas as gpd, matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(8, 6))
gpd.read_file("data/raw/osm_protected_areas.geojson").plot(ax=ax, color="lightgreen")
gpd.read_file("data/raw/osm_transport.geojson").plot(ax=ax, linewidth=0.3, color="grey")
df = pd.read_csv("data/raw/firms_viirs.csv"); ax.scatter(df.longitude, df.latitude, s=3, c="red")
plt.savefig("outputs/sanity_raw.png", dpi=150)
```
If points appear at the wrong place or the plot is blank: check `[lon, lat]` order and the bbox.
