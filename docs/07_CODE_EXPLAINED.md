# 07 — Code Explained, Line by Line

A learning companion to the code: every file, every block, **why that line is there**,
and what every unfamiliar word means.

---

## What this project is

**ForestGeo Risk Analyser** asks a question that no single dataset can answer:

> *In a forested hill region, where do wildfire, roads, settlements and wildlife
> overlap — and which villages are most exposed as a result?*

Four themes, four separate sources, none of which knows about the others:

| theme | source | what it contributes |
|---|---|---|
| **fire** | NASA FIRMS (satellite) | 1,564 thermal detections, Jan–May 2024 |
| **settlement & access** | OpenStreetMap | 421 villages, 37,665 roads/tracks/railways |
| **habitat** | OpenStreetMap | 119 forest areas, 9 protected areas |
| **wildlife** | GBIF | 2,661 mammal sightings, 72 species |

The answer requires putting all four into one **spatial database** and asking questions
that are geometric rather than textual — *near*, *inside*, *crossing*, *overlapping*.

### Why MongoDB, and what it can and cannot do

The database is **MongoDB**, a *document database*: it stores records as flexible JSON-
like documents rather than fixed table rows. It supports geospatial data natively
through the **2dsphere index**, which treats coordinates as points on a sphere so that
distances are true great-circle distances rather than flat-plane approximations.

MongoDB can answer four kinds of spatial question:

| operator | question it answers |
|---|---|
| `$nearSphere` | *what is closest to this point, in order?* |
| `$geoNear` | the same, but it returns the distance |
| `$geoWithin` | *what lies entirely inside this shape?* |
| `$geoIntersects` | *what touches or crosses this shape?* |

But it has a hard limit that shapes this whole project: **MongoDB cannot build new
geometry.** It can test whether shapes relate to each other; it cannot merge 1,564 fire
detections into a single burn-risk area, or weld scattered forest patches into
continuous habitat. There is no union operator.

So the project does the construction in **Shapely** — a Python geometry library — and
writes the result *back* into MongoDB, where it becomes queryable like any other
collection. That round trip is the intellectual core of the work:

```
MongoDB (points)  ->  Shapely (union, buffer, intersect)  ->  MongoDB (areas)
                                                                    |
                                                        queried with $geoWithin
```

### What the pipeline does, end to end

```
fetch       download 4 open datasets          -> data/raw/
clean       validate, repair, clip geometry   -> data/processed/
load        insert + build 2dsphere indexes   -> MongoDB
query       the four spatial operations       -> outputs/q1..q4 .csv
derive      Shapely union/intersection        -> MongoDB derived_zones
cross-theme combine every theme into one score-> outputs/q6_village_risk.csv
benchmark   indexed vs collection scan        -> outputs/benchmark.png
map         layered interactive map + timeline-> outputs/forestgeo_map.html
```

Each stage writes files you can open and inspect, so when something looks wrong you can
tell *which* stage produced it.

### The headline results

- **79 of 421 villages** sit inside the critical zone — where fire pressure and
  continuous habitat overlap.
- **Sathyamangalam Tiger Reserve** had the most fire detections (52) but the fewest
  wildlife records (14); **Mudumalai** had the most sightings (533).
- On 250,000 points, a selective `$geoWithin` was **180× faster with a 2dsphere index**
  and examined **334× fewer documents** — but on a broad query the same index gave only
  a 1.3× gain, because index value depends on **selectivity**.
- **24.7% of wildlife records are deliberately obscured** to ~31 km, and they are
  precisely the flagship species (170 elephant, 48 tiger, 16 leopard).

---

## How to use this document

Read the block, type or read the code, read the "why", then run the verification at the
end of each section before moving on.

Each section ends with **Interview answers** — the questions that code invites and how
to answer them. A **Glossary** at the end defines every acronym and term of art.

**Contents**
- [What this project is](#what-this-project-is)
- [How to use this document](#how-to-use-this-document)
- [§0 Two ideas behind everything](#0-two-ideas-behind-everything)
- [§1 `forestgeo/__init__.py`](#1-forestgeoinitpy)
- [§2 `forestgeo/config.py`](#2-forestgeoconfigpy)
- [§3 `forestgeo/db.py`](#3-forestgeodbpy)
- [§4 `scripts/check_connection.py`](#4-scriptscheckconnectionpy)
- [§5 `forestgeo/fetch_osm.py`](#5-forestgeofetchosmpy)
- [§6 `forestgeo/fetch_gbif.py`](#6-forestgeofetchgbifpy)
- [§7 `forestgeo/fetch_firms.py`](#7-forestgeofetchfirmspy)
- [§8 `forestgeo/geo.py` — the geometry engine](#8-forestgeogeopy-the-geometry-engine)
- [§9 `forestgeo/clean.py` — where data decisions become code](#9-forestgeocleanpy-where-data-decisions-become-code)
- [§10 `forestgeo/load.py` — Python objects into BSON](#10-forestgeoloadpy-python-objects-into-bson)
- [§11 `forestgeo/queries.py` — the four spatial operations](#11-forestgeoqueriespy-the-four-spatial-operations)
- [§12 `forestgeo/unions.py` — the part MongoDB cannot do](#12-forestgeounionspy-the-part-mongodb-cannot-do)
- [§13 `forestgeo/cross_theme.py` — combining every theme into one answer](#13-forestgeocrossthemepy-combining-every-theme-into-one-answer)
- [§14 `forestgeo/benchmark.py` — measuring the index](#14-forestgeobenchmarkpy-measuring-the-index)
- [§15 `forestgeo/mapviz.py` — the interactive map](#15-forestgeomapvizpy-the-interactive-map)
- [§16 The scripts](#16-the-scripts)
- [§17 Results](#17-results)
- [Glossary](#glossary)
- [In closing: what was built, and what it demonstrates](#in-closing-what-was-built-and-what-it-demonstrates)

- [§1 `forestgeo/__init__.py`](#1-forestgeoinitpy)
- [§2 `forestgeo/config.py`](#2-forestgeoconfigpy)
- [§3 `forestgeo/db.py`](#3-forestgeodbpy)
- [§4 `scripts/check_connection.py`](#4-scripts00_check_connectionpy)

---

## §0 Two ideas behind everything

Almost every bug in a spatial project comes from one of these two. Learn them first.

### Coordinates are `[longitude, latitude]` — longitude first

Backwards from how people speak ("lat, long") and backwards from Google Maps. GeoJSON
and MongoDB both demand longitude first.

The cruel part: **swapping them does not crash anything.** The Nilgiris is around
longitude 76.6, latitude 11.4. Swap it and you get longitude 11.4, latitude 76.6 —
a valid point, in the Arctic Ocean north of Norway. Your queries just return zero
rows and you hunt a bug that was never an exception.

One exception you meet at the very end: Folium's `location=` argument takes
`[lat, lon]`. Only there.

### Store in degrees, measure in metres

Data is stored as longitude/latitude — degrees, **EPSG:4326** — because that is what
MongoDB requires for a `2dsphere` index.

But a degree is not a fixed distance. One degree of longitude is ~111 km at the
equator and 0 km at the poles. So "buffer this forest by 1000" in degrees is
meaningless. To measure anything — a buffer, an area, a distance — reproject to a flat
metre grid (UTM zone 43N, **EPSG:32643**), do the maths there, convert back to degrees
to store.

> **Degrees for storage, metres for mathematics.**

---

## §1 `forestgeo/__init__.py`

```python
"""ForestGeo Risk Analyser — spatial analysis package."""
```

**Why the file exists at all:** Python only treats a folder as an importable package if
it contains `__init__.py`. Without it, `from forestgeo import config` fails with
`ModuleNotFoundError`. The docstring is only so the file is not empty.

---

## §2 `forestgeo/config.py`

**Purpose.** Every later file needs the region, the two CRS codes and the collection
names. If each file defines its own copy, one day you change the bbox in one place and
not another, and lose an evening wondering why half the data vanished. So: one file
holds every constant, everything else imports from it, and **no magic numbers appear
anywhere else.**

### Block 1 — imports

```python
import os
from math import floor
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
```

`load_dotenv()` reads `.env` and copies its values into the process environment. It
must run **at import time, before** any `os.getenv` call below — which is why it is a
bare call at module level, not inside a function. `floor` is for the UTM formula,
`Path` for folder locations.

### Block 2 — the region

```python
REGION_NAME = "The Nilgiris"
BBOX = (76.20, 11.10, 77.10, 11.70)   # (west, south, east, north) in WGS84 degrees
```

Keep that comment. `BBOX` is handed to both osmnx and the FIRMS API and **both want
west, south, east, north in that order** — while other libraries use north, south,
east, west. The comment is what stops you guessing wrong later.

### Block 3 — the two coordinate systems

```python
CRS_WGS84 = "EPSG:4326"    # storage CRS — degrees; what MongoDB requires
CRS_METRIC = "EPSG:32643"  # UTM zone 43N — metres; for buffers, areas, distances
```

§0's second idea, made concrete: two names, used everywhere, never a bare number.

### Block 4 — analysis parameters

```python
FIRE_SEASON = ("2024-01-01", "2024-05-31")

HOTSPOT_BUFFER_M = 1000       # burn-risk buffer around each fire hotspot
HABITAT_GAP_CLOSE_M = 50      # close small gaps between adjacent forest polygons
HABITAT_BUFFER_M = 2000       # habitat block grown outward -> habitat_buffer zone
NEAR_VILLAGE_M = 5000         # search radius: villages around a hotspot
NEAR_ROAD_M = 500             # search radius: roads around a sighting

SIMPLIFY_TOLERANCE_M = 10     # polygon simplification, applied in the metric CRS
COORD_PRECISION = 6           # decimal places kept on stored coordinates
GBIF_MAX_UNCERTAINTY_M = 1000 # discard sightings vaguer than this
EARTH_RADIUS_KM = 6378.1      # $centerSphere wants radians = km / this
```

Every distance ends in `_M` and states metres. These are the numbers an examiner asks
you to justify ("why 5 km?"), so they live in one visible place instead of buried
inside a query.

**Which phase consumes each one** — none of these is speculative:

| Constant | Used in | What it does |
|---|---|---|
| `FIRE_SEASON` | fetch | date range handed to the FIRMS API |
| `HOTSPOT_BUFFER_M` | union | each hotspot becomes a 1 km circle; merged = burn-risk footprint |
| `HABITAT_GAP_CLOSE_M` | union | buffer +50 m then −50 m, which welds forests separated by a thin gap into one block |
| `HABITAT_BUFFER_M` | cross-theme | habitat block grown 2 km; its overlap with the burn footprint is the critical zone |
| `NEAR_VILLAGE_M` | queries | `$nearSphere` `$maxDistance`, in metres |
| `NEAR_ROAD_M` | queries | same, for sightings near roads |
| `SIMPLIFY_TOLERANCE_M` | clean | drops redundant vertices; keeps documents small and the map file light |
| `COORD_PRECISION` | clean | 6 decimals ≈ 0.1 m — plenty, and it removes the near-duplicate vertices MongoDB rejects |
| `GBIF_MAX_UNCERTAINTY_M` | clean | a sighting accurate to ±5 km cannot be tested against a 500 m road buffer |
| `EARTH_RADIUS_KM` | queries, benchmark | `$centerSphere` takes a **radius in radians**, not metres — you divide km by this |

That last one is the subtlest trap in the project. MongoDB mixes units: `$maxDistance`
(with `$nearSphere` on GeoJSON) is **metres**, but `$centerSphere` is **radians**. Get
them confused and your 5 km search silently becomes a 5000-radian one.

> Deliberately *not* included: a minimum habitat-fragment size. The roadmap marks it
> optional, so add it in the union phase only if small fragments turn out to be noise.

### Block 5 — secrets

```python
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB = os.getenv("MONGODB_DB", "forestgeo")
FIRMS_MAP_KEY = os.getenv("FIRMS_MAP_KEY")
```

`os.getenv(name, default)` returns `default` when the variable is missing.
`FIRMS_MAP_KEY` deliberately has **no** default: if absent it becomes `None`, so the
fetch code can raise a clear error rather than sending the literal string `"None"` to
NASA. Nothing here is ever hard-coded or printed — `.env` is git-ignored, and a
hard-coded password is public forever once pushed.

### Block 6 — the collections

```python
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
```

The value is the geometry family each collection is *allowed* to hold. This matters
more than it looks: ask OSM for roads and it also returns bus-stop **points** tagged
`highway=bus_stop`. This dict is what you check against to discard them, so
`transport` ends up holding only lines.

**Why `farmland` is nearly free.** It is a polygon layer, so it reuses the identical
cleaning and loading path as `forests` and `water_bodies` — no new code, just one more
entry here and one more OSM tag group in the fetch step. The only real cost is one
extra Overpass request.

It also earns its place analytically: farmland pressed against forest edge is exactly
where human–wildlife conflict happens, so it gives the cross-theme query something
more interesting to say than fire alone. In the Nilgiris, tea estates are often tagged
`landuse=farmland` or `landuse=orchard`, so ask for both.

**`derived_zones` is different from the other nine.** The rest hold downloaded data;
this one holds geometry *you compute* — the Shapely unions from the later phases. It
starts empty and is filled in Phase 5, not by the loader.

### Block 7 — folder locations

```python
ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
OUTPUT_DIR = ROOT / "outputs"
```

`__file__` is this file's own path, `.resolve()` makes it absolute, and
`.parent.parent` climbs from `forestgeo/config.py` to the project root. Paths are
anchored to the project, not to wherever you happened to run `python` — a relative
`"data/raw"` breaks the moment a script runs from inside `scripts/`.

### Block 8 — the self-check

```python
def utm_epsg(lon: float, lat: float) -> str:
    """EPSG code of the UTM zone containing (lon, lat)."""
    zone = floor((lon + 180) / 6) + 1
    return f"EPSG:{(32600 if lat >= 0 else 32700) + zone}"


def bbox_centre() -> tuple[float, float]:
    """(lon, lat) centre of BBOX."""
    west, south, east, north = BBOX
    return (west + east) / 2, (south + north) / 2
```

`utm_epsg` encodes the zone formula so `CRS_METRIC` is **checkable rather than
trusted**. The world is cut into 60 UTM zones 6° wide; `+180` shifts longitude from
−180…180 into 0…360 so the division works, `+1` makes zones count from 1 rather than
0, `32600` is the northern-hemisphere EPSG base and `32700` the southern.

`bbox_centre` returns longitude first, matching §0, and unpacks `BBOX` in the same
west/south/east/north order as Block 2.

### Interview answers — `config.py`

**"Why two coordinate reference systems? Why not one?"**
Storage and measurement have different needs. MongoDB's `2dsphere` index requires
spherical longitude/latitude (EPSG:4326); accurate buffers and areas require a flat
metre grid (EPSG:32643, UTM 43N). So: degrees for storage, metres for mathematics. I
reproject to UTM, compute, then reproject back before storing. A buffer computed in
degrees would be distorted by over 2% across this bbox — and simply means nothing,
since a degree is not a distance.

**"How do you know your metric CRS is correct?"**
I assert it rather than trust it. `utm_epsg()` derives the correct zone from the bbox
centre using the standard formula, and the connection check fails if it disagrees with
`CRS_METRIC`. A wrong metric CRS throws no error and shows no symptom — every distance
is just quietly wrong — so it must be tested, not assumed.

**"Why a 5 km village radius, or a 1 km fire buffer?"**
Defensible defaults, deliberately exposed as parameters so they can be challenged.
1 km is roughly three VIIRS pixel widths, which respects the sensor's ~375 m
positional uncertainty instead of pretending a hotspot is a point. 5 km is a plausible
walking catchment for a village. Because both live in `config.py`, the whole pipeline
can be re-run at 500 m or 2 km to show how sensitive the conclusions are.

**"What is the difference between `$maxDistance` and `$centerSphere`?"**
Units, and capability. `$maxDistance` with `$nearSphere` on GeoJSON is **metres**;
`$centerSphere` takes a radius in **radians** (`km / 6378.1`). Also `$nearSphere`
sorts by distance and requires a geospatial index, while `$geoWithin` + `$centerSphere`
does not sort and *can* be used inside `count_documents()` — which is why counting
uses the latter.

**"Why one collection per theme rather than a single `features` collection?"**
Simpler queries (no `type` filter everywhere), one `2dsphere` index per theme so index
size matches the data searched, and per-theme benchmarking that makes the
indexed-vs-unindexed comparison legible. The cost is more collections to manage, which
at ten is negligible.

**"How are secrets handled?"**
`.env`, git-ignored, loaded by `python-dotenv` at import. `config.py` is the only file
that reads them; nothing is hard-coded or printed, and `safe_uri()` redacts the
password anywhere the URI is displayed. `.env.example` ships with blank placeholders
for reproducibility.

**"You developed on local mongod but the report says Atlas — why?"**
The spatial operators and `explain()` behave identically, so I iterated locally without
paying network latency per query, then re-ran the pipeline against an Atlas M0 cluster
for the final numbers and screenshots. Only the URI changes, because it is read from
`.env` in exactly one place.

### Verify

```bash
.venv/bin/python -c "
from forestgeo import config
print(config.BBOX)
print(config.utm_epsg(*config.bbox_centre()), 'should equal', config.CRS_METRIC)
"
```

Line 1 proves the package imports. Line 2 is the real test — it must print
`EPSG:32643 should equal EPSG:32643`. If those differ, the metric CRS is wrong for the
region and **every distance in the project is silently wrong**, which is precisely the
bug you cannot see by looking at a map.

---

## §3 `forestgeo/db.py`

**Purpose.** One place that knows how to reach MongoDB. Every other file says
`get_db()` and never thinks about URIs, timeouts or TLS again. It is ~20 lines and it
is the only file that touches the connection, which is why switching from local
`mongod` to Atlas later is a one-line change in `.env` and nothing else.

### Block 1 — imports

```python
from functools import lru_cache

import certifi
from pymongo import MongoClient

from forestgeo.config import MONGODB_DB, MONGODB_URI
```

Note what is imported from `config`: the URI and database name, never a literal. This
is the payoff of §2 — the secret lives in `.env`, `config` reads it, and `db` uses it.

### Block 2 — the cached client

```python
@lru_cache(maxsize=1)
def get_client() -> MongoClient:
    kwargs = {"serverSelectionTimeoutMS": 10_000}
    if MONGODB_URI.startswith("mongodb+srv://"):
        kwargs["tlsCAFile"] = certifi.where()
    return MongoClient(MONGODB_URI, **kwargs)
```

Three decisions in five lines:

**`@lru_cache(maxsize=1)`** — build the client once per process and hand the same one
back every time. A `MongoClient` is not a single connection; it owns a *connection
pool* and background monitor threads. Creating one per query would open sockets
repeatedly and is the classic PyMongo performance mistake. The cache makes
`get_client()` safe to call from anywhere.

**`serverSelectionTimeoutMS=10_000`** — how long PyMongo waits to find a reachable
server before raising. The default is 30 seconds, which feels like a hang when you
have simply typed the URI wrong. Ten seconds gives you the error while you still
remember what you changed.

**`tlsCAFile=certifi.where()`, only for `mongodb+srv://`** — Atlas requires TLS, and
on some Linux installs Python cannot find the system certificate bundle, producing
`CERTIFICATE_VERIFY_FAILED`. `certifi` ships its own bundle. The `if` matters: a local
`mongodb://localhost` connection has no TLS, and passing a CA file there is pointless.
**This branch is what makes the local → Atlas switch painless.**

### Block 3 — the database handle

```python
def get_db():
    return get_client()[MONGODB_DB]
```

Indexing a client by name gives a `Database` object; indexing that by name gives a
`Collection`. So `get_db()["villages"]` is the villages collection.

### Block 4 — never print a password

```python
def safe_uri() -> str:
    """The URI with any password redacted — safe to print or log."""
    if "@" not in MONGODB_URI:
        return MONGODB_URI
    scheme, rest = MONGODB_URI.split("://", 1)
    creds, host = rest.split("@", 1)
    return f"{scheme}://{creds.split(':', 1)[0]}:***@{host}"
```

An Atlas URI looks like `mongodb+srv://user:PASSWORD@cluster.mongodb.net/...`. The
next script prints which database it connected to, and you will paste that output into
your report or a screenshot. This function splits the URI at `@`, keeps the username,
and replaces the password with `***`. A local URI has no `@`, so it is returned
unchanged.

### The one thing that surprises people

**`MongoClient(...)` does not connect.** It returns immediately and connects lazily on
the first real operation. So a wrong URI, a dead server or a blocked IP produces *no
error here* — the failure surfaces later, at your first query, often in a confusing
place.

That is exactly why the next file exists: a script that deliberately issues a cheap
command (`ping`) to force the connection and report success or failure clearly.

### Interview answers — `db.py`

**"Why cache the client instead of creating a `MongoClient` per query?"**
A `MongoClient` is not one connection — it owns a connection pool and background
threads that monitor server health (PyMongo's server discovery and monitoring). One
client per query would reopen sockets, leak monitor threads and eventually exhaust
file descriptors. The documented practice is one client per application, reused; the
`lru_cache` enforces that while still letting any module just call `get_client()`.

**"Does creating a `MongoClient` connect to the database?"**
No. It returns immediately and connects lazily on the first real operation. So a wrong
URI or a stopped server raises nothing at construction — the error surfaces later at
the first query. That is precisely why there is a dedicated connection-check script
that issues a `ping` to force the round-trip and fail in one obvious place.

**"What does `serverSelectionTimeoutMS` do?"**
It bounds how long the driver waits to find a suitable server before raising
`ServerSelectionTimeoutError`. The default is 30 s, which is indistinguishable from a
hang during development; 10 s surfaces configuration mistakes quickly. It is a
*selection* timeout, not a query timeout.

**"How would you move this project to MongoDB Atlas?"**
Change one line in `.env`. The URI is read in `config.py` alone, so nothing else in
the codebase knows the difference. The only code that cares is the `mongodb+srv://`
branch in `get_client()`, which attaches `certifi`'s CA bundle because Atlas requires
TLS and some Linux Python builds cannot find the system certificate store.

**"Why redact the URI instead of just printing it?"**
An Atlas URI embeds the database password. The pipeline prints its connection target,
and that output ends up in screenshots and reports. `safe_uri()` keeps the username
and host — useful for debugging — and replaces the password with `***`. Both splits
use `maxsplit=1` because a password may legally contain `:` or `@`.

**"When are the database and collections actually created?"**
Lazily, on first write. `get_db()["villages"]` is just a handle; MongoDB materialises
the database and collection when the first document (or index) is created. This is why
the load step can simply drop and re-create collections without any schema setup.

### Verify

```bash
.venv/bin/python -c "
from forestgeo.db import get_db, safe_uri
print(safe_uri())
print(get_db().command('ping'))
"
```

`safe_uri()` should print your URI with no password visible. `command('ping')` is the
cheapest possible round-trip to the server and must print `{'ok': 1.0}`. If it hangs
~10 seconds and then raises `ServerSelectionTimeoutError`, the server is unreachable:
check that `mongod` is running (`systemctl is-active mongod`), or for Atlas that your
IP is allowlisted and the password is URL-encoded.

---

## §4 `scripts/check_connection.py`

**Purpose.** Prove the environment works *before* spending an hour downloading data. It
tests the three things that can silently ruin everything downstream: reprojection, the
choice of metric CRS, and the database connection.

### First: make the package importable

Python puts a script's **own folder** on the import path, not the project root. So a
file in `scripts/` cannot see `forestgeo/` and fails with `ModuleNotFoundError`.

Fix it once, with the line the README already promises:

```bash
.venv/bin/pip install -e .
```

`-e` means *editable*: pip does not copy the code into `site-packages`, it links to the
project folder, so edits take effect immediately. The alternative — three `sys.path`
lines at the top of all ten scripts — works but is repetitive and looks amateurish in a
submission.

### Block 1 — header and imports

```python
#!/usr/bin/env python
"""Phase 0 — prove the environment works: CRS, MongoDB, folders."""

from pymongo.errors import PyMongoError
from pyproj import Transformer

from forestgeo import config
from forestgeo.db import get_db, safe_uri
```

`PyMongoError` is the base class of every PyMongo exception, so one `except` covers
timeouts, authentication failures and TLS errors — without swallowing real bugs such as
a misspelled attribute.

### Block 2 — is the reprojection sane?

```python
def check_reprojection() -> bool:
    """Catch a swapped lon/lat: the UTM result must land in zone 43N's plausible range."""
    tf = Transformer.from_crs(config.CRS_WGS84, config.CRS_METRIC, always_xy=True)
    lon, lat = config.bbox_centre()
    x, y = tf.transform(lon, lat)
    ok = 600_000 < x < 800_000 and 1_200_000 < y < 1_320_000
    print(f"  (lon,lat)->UTM : ({lon:.3f}, {lat:.3f}) -> ({x:.0f}, {y:.0f}) m"
          f"  {'ok' if ok else 'SWAPPED?'}")
    return ok
```

**`always_xy=True` is mandatory.** Without it, pyproj honours each CRS's *declared*
axis order — and EPSG:4326 officially declares **latitude first**. So
`transform(76.6, 11.4)` would be interpreted as latitude 76.6, longitude 11.4 and
silently return coordinates near Svalbard. `always_xy=True` forces (x, y) = (lon, lat),
the order GeoJSON uses. This one argument is the most common silent bug in Python GIS.

**Why the numeric range:** a UTM easting is metres from the zone's false origin, a
northing is metres from the equator. For the Nilgiris, easting ≈ 680,000 and
northing ≈ 1,260,000. A swapped pair falls far outside that window, so the range check
converts an invisible bug into a visible failure.

### Block 3 — is the metric CRS right for this region?

```python
def check_crs() -> bool:
    """CRS_METRIC must be the UTM zone that actually contains the region centre."""
    lon, lat = config.bbox_centre()
    expected = config.utm_epsg(lon, lat)
    ok = expected == config.CRS_METRIC
    print(f"  CRS_METRIC     : {config.CRS_METRIC} (expected {expected})"
          f"  {'ok' if ok else 'MISMATCH — fix config.CRS_METRIC'}")
    return ok
```

This is where `utm_epsg()` from §2 earns its keep. Change `BBOX` to another region and
forget `CRS_METRIC`, and every buffer and area becomes wrong — with no exception and a
map that still looks plausible. This check is the only thing that catches it.

### Block 4 — can we reach MongoDB?

```python
def check_mongo() -> bool:
    print(f"  uri            : {safe_uri()}")
    try:
        db = get_db()
        ping = db.command("ping")
        print(f"  ping           : {ping}")
        print(f"  server version : {db.client.server_info()['version']}")
        print(f"  collections    : {db.list_collection_names() or '(none yet)'}")
        return ping.get("ok") == 1.0
    except PyMongoError as exc:
        print(f"  !! {type(exc).__name__}: {exc}")
        print("  -> see docs/05_TROUBLESHOOTING.md (URI, password encoding, IP allowlist)")
        return False
```

**Why `ping`:** it is the cheapest command a MongoDB server accepts — no database, no
collection, no permissions needed — and it forces the lazy connection from §3 to
actually happen. `{'ok': 1.0}` is the server saying yes.

**Why print the version and collections:** the version belongs in the report's
system-design section, and the collection list tells you immediately whether you are
pointed at the database you think you are — an easy mistake once both a local and an
Atlas URI exist.

### Block 5 — folders, result, exit code

```python
def main() -> int:
    print(f"\nForestGeo environment check — {config.REGION_NAME}\n")

    print("1) CRS")
    repro_ok = check_reprojection()
    crs_ok = check_crs()

    print("2) MongoDB")
    mongo_ok = check_mongo()

    print("3) folders")
    for d in (config.RAW_DIR, config.PROCESSED_DIR, config.OUTPUT_DIR):
        d.mkdir(parents=True, exist_ok=True)
        print(f"  {d.relative_to(config.ROOT)}")

    ok = repro_ok and crs_ok and mongo_ok
    print("\n" + ("ALL CHECKS PASSED — Phase 0 done." if ok else "CHECKS FAILED — see above."))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

**Why three separate `_ok` variables rather than one chained expression:** `and`
short-circuits. `ok = check_reprojection() and check_crs()` would skip the second check
entirely when the first fails — so it would never print, and you would fix one problem
only to discover another on the next run. Calling each explicitly means one run reports
everything that is wrong.

**`mkdir(parents=True, exist_ok=True)`** — `parents=True` creates intermediate folders
(`data/` before `data/raw/`), `exist_ok=True` makes it idempotent so re-running never
raises `FileExistsError`. Idempotency is a project rule: every script must be safe to
re-run.

**`if __name__ == "__main__"`** — runs only when the file is executed directly, not when
imported, so the file stays importable for testing while remaining runnable.

**`raise SystemExit(main())`** — `main()` returns 0 for success and 1 for failure, and
`SystemExit` turns that into the process exit code. That is the Unix convention, so
`python scripts/check_connection.py && python scripts/fetch_data.py` runs the second only if the
first succeeded.

### Interview answers — `check_connection.py`

**"What does `always_xy=True` do, and why does it matter?"**
It forces pyproj to take and return coordinates as (x, y) = (longitude, latitude).
Without it, pyproj follows each CRS's declared axis order, and EPSG:4326 declares
latitude first — so a (lon, lat) pair is silently read backwards and the point lands
thousands of kilometres away. Nothing raises; queries simply return nothing. It is the
most common silent bug in Python GIS, which is why there is an explicit test for it.

**"Why test the reprojection with a numeric range instead of comparing to a fixed
value?"**
The goal is not precision, it is catching a swapped axis order. A plausible-range
assertion on the UTM easting and northing turns an invisible error into a loud one
while staying robust to small changes in the bbox.

**"Why does the script `ping` instead of running a real query?"**
`MongoClient` connects lazily, so no error appears until the first operation. `ping` is
the cheapest possible operation — no database, collection or privileges required — so it
forces the connection and localises the failure to one obvious place instead of letting
it surface later inside a query.

**"Why return an exit code at all?"**
So failure is machine-detectable. `0` means success, non-zero means failure, which lets
the pipeline steps be chained with `&&` and lets any CI or shell script stop on the
first broken stage rather than continuing with bad data.

**"Your checks don't use `assert`. Why not?"**
`assert` raises on the first failure, reporting one problem per run, and it is stripped
entirely when Python runs with `-O`. Returning booleans and printing each result means
one run reports every problem, and the behaviour does not change under optimisation.

### Verify

```bash
.venv/bin/python scripts/check_connection.py ; echo "exit code: $?"
```

Expect `ALL CHECKS PASSED — Phase 0 done.` and `exit code: 0`. `$?` holds the previous
command's exit code, which proves the convention in Block 5 actually works.

---

## §5 `forestgeo/fetch_osm.py`

**Purpose.** Download 7 of the 10 collections from OpenStreetMap. No API key needed.

**Background.** OSM data is not downloaded as files — it is *queried* from **Overpass**, a
free public read-only API that is rate-limited and sometimes slow. `osmnx` builds the
Overpass query, sends it, and returns a GeoDataFrame. OSM's data model is free-form
`key=value` **tags** (`place=village`, `highway=primary`, `landuse=forest`), so "fetch
villages" means "fetch everything tagged `place=village`".

### Block 1 — imports and osmnx settings

```python
"""Fetch OpenStreetMap layers for the study region via osmnx (Overpass API). No API key."""

import geopandas as gpd
import osmnx as ox

from forestgeo.config import BBOX, CRS_WGS84, RAW_DIR

ox.settings.use_cache = True
ox.settings.cache_folder = "cache"
ox.settings.requests_timeout = 300
```

**`use_cache = True` is the most valuable line in the file.** osmnx writes every Overpass
response to disk, keyed by the query text. An identical re-run reads the cache instead of
the network, so iterating on the cleaning code takes seconds instead of minutes.
`cache_folder = "cache"` is already git-ignored — it is downloaded data, not source.

**`requests_timeout = 300`** — Overpass genuinely takes minutes over a large area. The
default is shorter, so a query that would have succeeded fails instead.

### Block 2 — the tag definitions

```python
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
```

One entry per collection. A dict rather than seven functions because the fetching logic is
identical for every layer — only the tags differ.

**How to read a tag spec.** `{"place": ["village", "hamlet", "town"]}` means *`place` is
any of these*. Multiple keys in one dict are **OR**-ed, so `forests` returns anything
tagged `landuse=forest` **or** `natural=wood`. That matters: OSM has no single canonical
forest tag and mappers use both, so asking for one would lose half the data.

**Why `orchard` sits under farmland:** Nilgiris tea estates are frequently tagged
`landuse=orchard` rather than `farmland`, so asking only for `farmland` would miss most of
the cultivated land in the region.

### Block 3 — fetching one layer

```python
KEEP = ["element", "id", "name", "place", "highway", "railway", "waterway",
        "landuse", "natural", "boundary", "leisure", "protect_class", "water",
        "geometry"]


def fetch_layer(name: str, bbox=BBOX, save: bool = True) -> gpd.GeoDataFrame:
    """Fetch one OSM layer into a GeoDataFrame and save it to data/raw/."""
    gdf = ox.features_from_bbox(bbox=bbox, tags=LAYERS[name]).reset_index()

    cols = [c for c in KEEP if c in gdf.columns]
    gdf = gpd.GeoDataFrame(gdf[cols], geometry="geometry", crs=CRS_WGS84)

    print(f"{name}: {len(gdf)} features | {dict(gdf.geometry.geom_type.value_counts())}")
    if save:
        gdf.to_file(RAW_DIR / f"osm_{name}.geojson", driver="GeoJSON")
    return gdf
```

**The version trap.** osmnx 2.x takes `bbox=(left, bottom, right, top)` — exactly our
`(west, south, east, north)`. **osmnx 1.x used `(north, south, east, west)`**, a different
order entirely. Most tutorials online are 1.x and will silently fetch the wrong rectangle.
This project is on osmnx 2.1.1.

**`.reset_index()`** — osmnx returns a GeoDataFrame indexed by a MultiIndex of
`(element, id)`, where `element` is `node`/`way`/`relation`. Resetting turns them into
ordinary columns so `id` can be used as `source_id` at load time.

**Why keep only some columns** — a real OSM response has *hundreds* of tag columns
(`wikidata`, `source:name`, `ele`, `operator`…), nearly all empty. They inflate the
GeoJSON for no benefit. The list comprehension keeps only columns that actually came back,
because which tags appear varies by layer.

**Why print the geometry types** — this line teaches you the data. Ask for `highway=*` and
the output will include `Point` counts: bus stops, traffic signals and crossings also
carry `highway=` tags. Seeing that is the reason `COLLECTIONS` exists.

**Nothing is filtered here, deliberately.** Fetch stays a faithful record of what OSM
returned; filtering happens in the clean step so the validation report can honestly state
how many features were dropped and why.

### Block 4 — fetching all layers

```python
def fetch_all(bbox=BBOX) -> dict[str, gpd.GeoDataFrame]:
    """Fetch every OSM layer, one at a time."""
    return {name: fetch_layer(name, bbox=bbox) for name in LAYERS}
```

Sequential, not parallel — Overpass is a shared public resource and concurrent requests
earn an HTTP 429 rate-limit response.

### Interview answers — `fetch_osm.py`

**"Where does the OpenStreetMap data come from? Did you download a file?"**
No — it is queried live from the Overpass API, a free public read-only endpoint over the
OSM database. `osmnx` composes the Overpass QL query from a bounding box and a tag filter
and returns a GeoDataFrame. That keeps the project reproducible: anyone can re-run the
fetch rather than needing a copy of my files.

**"Why does one layer need several tags?"**
OSM tagging is a community convention, not a schema, so the same real-world feature is
tagged inconsistently. Forest appears as both `landuse=forest` and `natural=wood`; tea
estates as `landuse=farmland` and `landuse=orchard`. Querying a single tag would silently
lose a large share of the features, so each layer lists every tag mappers actually use.

**"Your transport layer contains points. Isn't that a bug?"**
No — it is what OSM returns. Bus stops, crossings and traffic signals all carry `highway=`
tags, so a `highway=*` query legitimately includes nodes. The fetch stage stays faithful
to the source; the clean stage keeps only the LineStrings, using the per-collection
geometry family declared in `config.COLLECTIONS`. Keeping those stages separate is what
lets the validation report state exactly how many features were dropped and why.

**"How do you avoid hammering the Overpass API?"**
Responses are cached to disk by osmnx and keyed by query, so repeated runs do not hit the
network at all; layers are fetched sequentially rather than in parallel; and the timeout
is raised to 300 s so slow-but-valid queries complete instead of being retried. During
development I test against a small bounding box first so mistakes cost seconds.

**"What happens if Overpass has nothing matching your tags?"**
osmnx raises `InsufficientResponseError` rather than returning an empty GeoDataFrame. That
is worth knowing, because an empty layer is a legitimate result for a sparse theme in a
small area — not an error — so it should be handled as "zero features" rather than being
allowed to fail the whole fetch.

### What the fetch actually returned (real numbers, 2026-10-03)

Full region bbox `(76.20, 11.10, 77.10, 11.70)` — study area 6,519 km²:

| layer | features | geometry types | coverage |
|---|---|---|---|
| `villages` | 421 | Point 377, **Polygon 44** | — |
| `transport` | 37,814 | LineString 37,813, Polygon 1 | 13,830 km |
| `rivers` | 2,078 | LineString 2,078 | 2,769 km |
| `water_bodies` | 1,035 | Polygon 1,026, LineString 9 | 110 km² |
| `farmland` | 814 | Polygon 813, LineString 1 | 62 km² |
| `forests` | 167 | Polygon 152, **MultiPolygon 3**, Point 12 | 3,521 km² (54%) |
| `protected_areas` | 15 | Polygon 14, Point 1 | 1,551 km² (24%) |

**Lesson 1 — feature count is not coverage.** `forests` has only 167 features yet covers
54% of the region: just **3 MultiPolygons account for 1,949 km²**. Large forests are mapped
as single OSM *relations*, so one feature can be enormous. Never judge a layer by its row
count.

**Lesson 2 — Overpass returns features unclipped.** It hands back the *complete* geometry
of anything that merely touches the bounding box:

| layer | unclipped | clipped to bbox | lies outside the region |
|---|---|---|---|
| `forests` | 6,078 km² | 3,521 km² | 42% |
| `protected_areas` | 2,959 km² | 1,551 km² | 48% |

Nearly half that geometry is outside the study area. This is why the clean step **must**
clip to the bbox: without clipping the project would report 93% forest cover instead of
54% — a figure that would not survive scrutiny.

**Lesson 3 — a precise tag spec prevents junk.** Because `LAYERS["transport"]` enumerates
specific `highway` values rather than asking for `highway=*`, nodes such as
`highway=bus_stop` were never requested, so `transport` came back as 37,813 LineStrings and
a single stray Polygon. Asking for `highway=True` would have returned thousands of points.
The stray non-family geometries across all layers are trivial (1, 9, 1, 12 and 1 features)
and are removed by the family filter in cleaning.

**Lesson 4 — 44 of 421 villages (10.5%) are Polygons.** Some mappers tag a village as a
node, others trace its boundary — both are valid OSM. Since `villages` is declared
Point-only, the naive clean rule "keep only Points" would **silently discard 44 real
villages**. They must be *converted*, using **`representative_point()` not `centroid()`**:
for a concave shape the centroid can fall outside the polygon, placing the village
somewhere it is not. `representative_point()` is guaranteed to lie inside.

Note that the small test bbox returned only Points — the polygon-tagged villages appear
only over the wider area. Unrepresentative test data is a reason to re-check at full scale,
not a reason to skip the small test.

### Network reality: Overpass is a free public API

During this fetch, three requests failed in a row with different errors —
`ConnectionRefusedError [Errno 111]`, then `Temporary failure in name resolution
[Errno -3]` — on hosts that were reachable when tested seconds later. Not rate limiting
(osmnx self-throttles via `overpass_rate_limit = True`, and a rate limit returns HTTP 429
or 504, never a refused connection), and not a misconfiguration.

Two things follow, both worth stating in the report's limitations section:

- **The data source has no availability guarantee.** Reproducibility depends on a free
  public service being up.
- **`cache/` is the mitigation.** Once a layer is cached, the pipeline no longer depends on
  Overpass at all.

The practical fix is to retry *at the shell*, not in the code — a loop that re-runs any
layer whose output file is missing. That keeps the retry logic out of the codebase while
still handling the flakiness:

```bash
for layer in farmland forests protected_areas transport; do
  for attempt in 1 2 3 4; do
    if [ -f "data/raw/osm_$layer.geojson" ]; then break; fi
    .venv/bin/python -c "
from forestgeo.fetch_osm import fetch_layer
fetch_layer('$layer')
" 2>&1 | tail -3
    sleep 10
  done
done
```

### Verify — small first, then full

Never run the full region first. Test on a tiny bbox so a mistake costs seconds:

```bash
.venv/bin/python -c "
from forestgeo.fetch_osm import fetch_layer
g = fetch_layer('villages', bbox=(76.65, 11.35, 76.75, 11.45), save=False)
print(g.head(3)[['id','name','place']])
"
```

That is a ~11 km box around Ooty; expect a handful of `Point` villages. Then one real
layer for the whole region:

```bash
.venv/bin/python -c "
from forestgeo.fetch_osm import fetch_layer
fetch_layer('villages')
"
ls -la data/raw/
```

---

## §6 `forestgeo/fetch_gbif.py`

**Purpose.** Fetch the `sightings` collection — wildlife occurrence records. No API key.

**Background.** GBIF is an *aggregator*, not one dataset: it pools iNaturalist
observations, eBird checklists, museum specimens and national surveys. "Sightings" is
therefore heterogeneous by nature, which is why `basisOfRecord` and
`coordinateUncertaintyInMeters` matter so much.

### A design decision made from real counts

Before writing the fetcher, the record counts inside the study bbox were measured:

| query | records |
|---|---|
| Mammals (`classKey=359`) | **2,670** |
| Birds (`classKey=212`) | **828,034** |

`03_DATA_ACQUISITION.md` originally said "birds, cap at 15,000". That cap would be an
**arbitrary 1.8% slice** of 828k records returned in no defined order — not a random
sample. Worse, bird record density in GBIF reflects *where birdwatchers go*, because eBird
checklists dominate, so any derived statistic (such as "% of sightings within 500 m of a
road") would measure observer behaviour rather than ecology.

**Decision: mammals only.** Complete, unbiased, and a better fit for the project's story —
elephants, gaur and tigers are what actually conflict with fire, roads and settlements.
The exclusion of birds is stated in the report as a methodological choice.

Verified class keys via `/species/match`: `Mammalia=359`, `Aves=212`. **`Reptilia` and
`Amphibia` return no `classKey` at all**, so the commonly-cited `Reptilia: 358` should not
be trusted. Also tested: `iucnRedListCategory` as a search filter returns 0 results — it is
not supported that way, so threatened-species filtering is not available here.

### Block 1 — imports and constants

```python
"""Fetch wildlife occurrence records from GBIF (aggregates iNaturalist, eBird, museums)."""

import time

import pandas as pd
import requests

from forestgeo.config import BBOX, RAW_DIR

API = "https://api.gbif.org/v1/occurrence/search"
PAGE = 300          # GBIF's maximum limit per request

CLASSES = {"Mammalia": 359, "Aves": 212}   # verified via /species/match

KEEP = ["key", "species", "scientificName", "class", "order", "family",
        "decimalLatitude", "decimalLongitude", "eventDate", "year",
        "coordinateUncertaintyInMeters", "basisOfRecord", "datasetKey",
        "datasetName", "iucnRedListCategory"]
```

**`PAGE = 300`** is GBIF's hard maximum for `limit`. Asking for more does not raise a
useful error, it simply caps you — so hardcoding the real maximum minimises request count.

**`KEEP`** — a GBIF record carries ~100 fields. Needed here: `key` (unique ID, for
deduplication), the two coordinate fields, `coordinateUncertaintyInMeters` (to discard
vague records in cleaning), `class`/`order`/`family` (grouping), and `eventDate`. The rest
is noise.

### Block 2 — the bounding box as WKT

```python
def bbox_wkt(bbox=BBOX) -> str:
    """GBIF needs a counter-clockwise WKT ring."""
    w, s, e, n = bbox
    return f"POLYGON(({w} {s},{e} {s},{e} {n},{w} {n},{w} {s}))"
```

**The winding order is a real trap.** GBIF requires the ring to be **counter-clockwise**:
bottom-left → bottom-right → top-right → top-left → close. Reverse it and GBIF interprets
the ring as *the whole globe minus your box*, returning millions of records from
everywhere else — with no error.

The final point repeats the first because a WKT ring must be explicitly closed. Inside WKT
the order is `longitude latitude`, space-separated — the same lon-first rule, different
syntax.

### Block 3 — paginating one class

```python
def fetch_class(class_key: int, max_records: int = 20_000) -> pd.DataFrame:
    """Page through all occurrences of one taxonomic class inside the bbox."""
    params = {
        "geometry": bbox_wkt(),
        "classKey": class_key,
        "hasCoordinate": "true",
        "hasGeospatialIssue": "false",
        "occurrenceStatus": "PRESENT",
        "year": "2015,2025",
        "limit": PAGE,
    }
    rows, offset = [], 0
    while offset < max_records:
        page = requests.get(API, params={**params, "offset": offset}, timeout=90).json()
        rows += [{k: rec.get(k) for k in KEEP} for rec in page["results"]]
        print(f"  offset {offset:>6} -> {len(rows):>6} rows (of {page['count']:,} matching)")
        if page["endOfRecords"] or not page["results"]:
            break
        offset += PAGE
        time.sleep(0.2)
    return pd.DataFrame(rows, columns=KEEP)
```

| Parameter | Why it is there |
|---|---|
| `hasCoordinate=true` | many records carry only a place name — useless for spatial queries |
| `hasGeospatialIssue=false` | GBIF flags records whose coordinates are suspect (0,0; country mismatch; swapped lat/lon). Free quality control |
| `occurrenceStatus=PRESENT` | GBIF also stores *absence* records ("we looked and found nothing"). Including them would invent sightings |
| `year=2015,2025` | an inclusive range; keeps data recent enough to compare with current roads and settlements |

**`rec.get(k)` rather than `rec[k]`** — GBIF omits absent fields entirely instead of
sending null, so bracket access would raise `KeyError`. `.get()` yields `None`.

**Two independent stop conditions.** `endOfRecords` is GBIF saying there is no more data —
the normal exit. `max_records` is your own safety cap, which matters because the search API
refuses offsets beyond **100,000**; without a cap, a large class would page until the API
errored.

**`pd.DataFrame(rows, columns=KEEP)`** — passing `columns` explicitly means a zero-row
fetch still returns a correctly shaped DataFrame, so downstream code does not break.

### Block 4 — combining classes

```python
def fetch_gbif(classes=("Mammalia",), caps=None, save=True) -> pd.DataFrame:
    """Fetch the given classes and concatenate. Default: mammals only."""
    caps = caps or {}
    frames = [fetch_class(CLASSES[c], caps.get(c, 20_000)) for c in classes]
    out = pd.concat(frames, ignore_index=True).drop_duplicates(subset="key")
    print(f"GBIF total: {len(out)} unique records")
    if save:
        out.to_csv(RAW_DIR / "gbif_sightings.csv", index=False)
    return out
```

**`classes=("Mammalia",)`** — a tuple (note the trailing comma), so the default is
immutable. Mammals-only is the project decision, but birds remain one argument away:
`fetch_gbif(("Mammalia", "Aves"), caps={"Aves": 15_000})`.

**`caps=None` then `caps or {}`** — a mutable default such as `caps={}` is created once and
shared across every call in Python, a classic bug. `None` plus a fallback avoids it.

**`drop_duplicates(subset="key")`** — `key` is GBIF's unique occurrence ID; this prevents
double-counting when class filters overlap or a fetch is repeated.

### What the GBIF fetch revealed: positional accuracy is not random

2,670 mammal records fetched in 9 pages. The `coordinateUncertaintyInMeters` distribution is
**bimodal**, and that turned out to be the single most important data finding in the project.

```
missing uncertainty :  286  (10.7%)
<= 1000 m           : 1449  -> keep with nulls: 1735 (65.0%)
>  1000 m           :  935  (35.0%)

percentiles (m):  25% = 30   50% = 100   75% = 31,126   90% = 31,137   95% = 31,148
```

A median of 100 m but a 75th percentile of 31 km is not measurement error — it is a fixed
mechanism. **iNaturalist obscures the locations of threatened species** to roughly a 0.2°
box to prevent poaching.

**The obscured records are precisely the flagship species:**

| species | ≤1 km | null | coarse | total | IUCN |
|---|---|---|---|---|---|
| *Bos frontalis* (gaur) | **70** | 18 | 152 | 240 | VU |
| *Rusa unicolor* (sambar) | 15 | 6 | 60 | 81 | VU |
| *Elephas maximus* (elephant) | 6 | 19 | 170 | 195 | EN |
| *Cuon alpinus* (dhole) | 5 | 2 | 33 | 40 | EN |
| *Melursus ursinus* (sloth bear) | 5 | 1 | 23 | 29 | VU |
| *Panthera pardus* (leopard) | 2 | 2 | 16 | 20 | VU |
| *Panthera tigris* (tiger) | **1** | 0 | 48 | 49 | EN |

Meanwhile the precise records are 1,037 **Least Concern** animals — palm squirrels,
macaques, chital. So applying `GBIF_MAX_UNCERTAINTY_M = 1000` naively keeps 65% of records
but removes **100% of tigers and leopards and nearly all elephants**, leaving a collection
useless for a human–wildlife conflict story.

**The obscuring cannot be reversed.** The 659 obscured records have **659 distinct
coordinate pairs**, with irregular spacing between sorted unique latitudes (0.0034°,
0.0091°, 0.0128°, …). Snapping to a grid would instead produce ~20 repeated coordinates on
a regular lattice. Each published point is an independent random draw inside its obscuring
cell, so the true location is destroyed rather than merely coarsened — there is nothing to
invert, and the mechanism exists to protect tigers and elephants from poaching.

### Data provenance matters as much as accuracy

| dataset | records | precision |
|---|---|---|
| Mammals of the Western Ghats (Nature Conservation Foundation) | 507 | mostly precise — systematic research survey |
| **Global Roadkill Data** | 479 | all precise, **but road-biased by construction** |
| iNaturalist research-grade | 1,456 | 393 precise / 893 coarse / 170 null |
| India Biodiversity Portal | 105 | precise |
| Observation.org | 49 | precise |
| IISER Squirrels of South Asia | 32 | precise |

**The roadkill dataset is a trap for Q2.** 479 of the 1,449 precise records (33%) come from
a dataset *defined* by animals found on roads. Including them in "% of sightings within
500 m of a road" makes the statistic circular — the answer approaches 100% by construction,
measuring the dataset's definition rather than animal behaviour.

### The resulting three-tier policy

1. **Load all 2,670 records**, keeping `uncertainty_m` and `dataset_name` as queryable fields.
2. **Tier them**: `precise` (≤1 km), `unknown` (null), `coarse` (>1 km). Distance-based
   queries use `precise` only, because a 500 m road buffer cannot be tested against a point
   that may be 31 km off.
3. **Exclude Global Roadkill Data from Q2**, and report the statistic both with and without
   it — the contrast is itself a finding about sampling bias.
4. **Give the roadkill data its own analysis**: where wildlife is actually killed, by road
   class, inside versus outside protected areas. A stronger question than the original Q2,
   with data purpose-built for it.
5. **Keep coarse records** for species inventory and a map layer labelled "location
   obscured", excluded from every distance calculation.

This preserves the flagship-species story honestly and converts a data limitation into two
better research questions.

**One more cleaning note:** `eventDate` arrives in mixed formats (`2025-01-04T16:20` and
`2025-01-11T11:41:20`), so parsing needs `format='mixed'`. All 2,670 parse, spanning
2015–2025.

### Interview answers — `fetch_gbif.py`

**"Why did you exclude birds when 828,000 records were available?"**
Because volume is not quality. Bird records in GBIF are dominated by eBird checklists, so
their spatial density reflects where birdwatchers go rather than where habitat is. Any
ratio computed from them — such as the share of sightings within 500 m of a road — would
measure observer effort, not ecology. A 15,000-record cap would also be an arbitrary 1.8%
slice in no defined order, not a random sample. Mammals give 2,670 complete records and
match the project's question, since large mammals are what actually conflict with fire,
roads and settlements.

**"What is GBIF, and is it a single dataset?"**
It is an aggregator that pools many publishers — iNaturalist, eBird, museum collections,
national surveys. That is why the records are filtered on `basisOfRecord` and
`coordinateUncertaintyInMeters`: provenance and positional accuracy vary enormously
between publishers, so the data must be qualified before it is used spatially.

**"How did you ensure the occurrence data is spatially trustworthy?"**
Four filters at fetch time — `hasCoordinate` (must have coordinates),
`hasGeospatialIssue=false` (GBIF's own flag for suspect coordinates such as 0,0 or a
country mismatch), `occurrenceStatus=PRESENT` (excludes absence records), and a recent year
range — plus a cleaning-stage filter discarding records whose stated
`coordinateUncertaintyInMeters` exceeds 1 km, since a record accurate to ±5 km cannot be
tested against a 500 m road buffer.

**"Why does the bounding box have to be counter-clockwise?"**
GBIF uses the ring's winding order to decide which side is the interior. A clockwise ring
describes the complement — the whole globe except the box — and returns records from
everywhere, with no error raised. It is a silent failure, so the ring order is asserted in
code with a comment rather than left to chance.

**"How does pagination work, and what are its limits?"**
`limit` is capped at 300 per request, and pages are walked with `offset` until GBIF sets
`endOfRecords`. The search API refuses offsets beyond 100,000, so a hard cap guards against
paging into an error on a large taxon. For genuinely large downloads GBIF provides a
separate download API that returns a citable DOI.

### Verify

```bash
.venv/bin/python -c "
from forestgeo.fetch_gbif import fetch_gbif
df = fetch_gbif()
print(df[['species','class','eventDate','coordinateUncertaintyInMeters']].head())
print()
print('species:', df.species.nunique(), '| top 5:')
print(df.species.value_counts().head())
"
```

Expect ~2,670 rows arriving in pages of 300 (about 9 requests) and recognisable Nilgiris
wildlife at the top of the species counts.

---

## §7 `forestgeo/fetch_firms.py`

**Purpose.** Fetch the `fire_hotspots` collection — satellite fire detections. Requires a
free `FIRMS_MAP_KEY` (email only, instant) from
https://firms.modaps.eosdis.nasa.gov/api/map_key/

**Background.** FIRMS is NASA's Fire Information for Resource Management System. VIIRS is
the sensor, flying on both Suomi-NPP and NOAA-20, with 375 m pixels. Critically, a
"hotspot" is a **thermal anomaly detection, not a confirmed fire** — the satellite is
reporting that a pixel was unusually hot. Industrial heat sources and sun glint produce
false positives. That distinction belongs in the report.

### Block 1 — endpoints and sources

```python
"""Fetch NASA FIRMS VIIRS active-fire hotspots. Requires FIRMS_MAP_KEY in .env."""

import datetime as dt
import io
import time

import pandas as pd
import requests

from forestgeo.config import BBOX, FIRE_SEASON, FIRMS_MAP_KEY, RAW_DIR

BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
STATUS = "https://firms.modaps.eosdis.nasa.gov/mapserver/mapkey_status/"
AVAILABILITY = "https://firms.modaps.eosdis.nasa.gov/api/data_availability/csv"

SOURCES = ("VIIRS_SNPP_SP", "VIIRS_NOAA20_SP")
MAX_DAYS = 5          # the area API serves at most 5 days per request
```

**The `_SP` suffix is the most important detail in this file.**

| suffix | meaning | covers |
|---|---|---|
| `_NRT` | Near Real-Time — fast, less corrected | roughly the **last 2 months only** |
| `_SP` | Standard Processing — science quality | the **historical archive** |

`FIRE_SEASON` is Jan–May 2024, so an `_NRT` source would return **nothing**, with no error
explaining why — a classic silent failure. Historical work requires `_SP`.

**Why two satellites:** Suomi-NPP and NOAA-20 both carry VIIRS and pass at different local
times, so each detects fires the other misses. Using both roughly doubles detections, at
the cost of needing deduplication.

### Block 2 — the key, and two pre-flight checks

```python
def _require_key() -> str:
    if not FIRMS_MAP_KEY:
        raise RuntimeError(
            "FIRMS_MAP_KEY is not set. Request one (email only, instant) at "
            "https://firms.modaps.eosdis.nasa.gov/api/map_key/ and add it to .env"
        )
    return FIRMS_MAP_KEY


def key_status() -> str:
    """Confirm the key works and see how much of the rate limit is used."""
    r = requests.get(STATUS, params={"MAP_KEY": _require_key()}, timeout=60)
    r.raise_for_status()
    return r.text.strip()


def data_availability() -> pd.DataFrame:
    """Which date range each FIRMS source actually covers."""
    r = requests.get(f"{AVAILABILITY}/{_require_key()}/all", timeout=60)
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text))
```

`_require_key()` fails with an actionable message instead of sending the literal string
`"None"` to NASA and getting back something cryptic. It returns the key but **never prints
or logs it**.

`data_availability()` reports the true date coverage per source, so `FIRE_SEASON` can be
*verified* rather than assumed — catching a mismatch before 62 wasted requests.

### Block 3 — one chunk, and the trap

```python
def _fetch_chunk(source: str, area: str, span: int, day: dt.date, key: str) -> pd.DataFrame:
    url = f"{BASE}/{key}/{source}/{area}/{span}/{day:%Y-%m-%d}"
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    text = r.text.lstrip()
    # FIRMS reports errors as plain text with HTTP 200 — so status code is not enough.
    if not text.lower().startswith("latitude"):
        raise RuntimeError(f"FIRMS returned: {text[:200]!r}")
    return pd.read_csv(io.StringIO(text))
```

**URL format:** `/{KEY}/{SOURCE}/{west,south,east,north}/{DAYS}/{START_DATE}`, returning
`START_DATE` through `START_DATE + DAYS - 1`. The area order matches `BBOX` exactly.

**The trap:** FIRMS returns **errors as plain text with HTTP 200**. An invalid key or bad
date yields a cheerful `200 OK` whose body is `"Invalid MAP_KEY"`, so `raise_for_status()`
passes and `pd.read_csv` then fails obscurely or returns a row of nonsense. Checking that
the body begins with `latitude` — the real CSV header — is the only reliable test.

`io.StringIO` wraps the response text in a file-like object for `pd.read_csv` without
touching disk.

### Block 4 — walking the season in chunks

```python
def fetch_firms(sources=SOURCES, season=FIRE_SEASON, bbox=BBOX, save=True) -> pd.DataFrame:
    """All hotspots in bbox for the season, across sources. Raw CSV columns kept."""
    key = _require_key()
    area = ",".join(str(v) for v in bbox)          # west,south,east,north
    start, end = (dt.date.fromisoformat(d) for d in season)

    frames = []
    for source in sources:
        day, n = start, 0
        while day <= end:
            span = min(MAX_DAYS, (end - day).days + 1)
            df = _fetch_chunk(source, area, span, day, key)
            if not df.empty:
                df["firms_source"] = source
                frames.append(df)
                n += len(df)
            day += dt.timedelta(days=span)
            time.sleep(1)
        print(f"{source}: {n} hotspots {start}..{end}")

    out = (pd.concat(frames, ignore_index=True)
             .drop_duplicates(subset=["latitude", "longitude", "acq_date",
                                      "acq_time", "satellite"])
           ) if frames else pd.DataFrame()
    print(f"FIRMS total: {len(out)} unique hotspots")
    if save:
        out.to_csv(RAW_DIR / "firms_viirs.csv", index=False)
    return out
```

**`span = min(MAX_DAYS, (end - day).days + 1)`** — 5-day chunks, except the last which is
whatever remains. The `+1` is because the range is inclusive at both ends; without it the
final day of the season is silently lost.

**`time.sleep(1)`** — the limit is 5000 transactions per 10 minutes and a multi-day request
counts as several. A 152-day season over two sources is ~62 requests, far below the cap, but
a one-second pause is free.

**Deduplication on five columns** — the same fire can be seen by both satellites, and
overlapping passes can report the same pixel twice. FIRMS data has **no record ID**, so
identity is position + timestamp + satellite.

**Raw column names are preserved** — `bright_ti4`, `frp`, `daynight` stay exactly as NASA
sends them. Renaming happens in cleaning, so `data/raw/` stays a faithful copy of the
source.

### The columns, and which matter

`latitude, longitude, bright_ti4, bright_ti5, scan, track, acq_date, acq_time, satellite,
instrument, confidence, version, frp, daynight`

- **`acq_time` is HHMM as an integer, in UTC** — `745` means 07:45. Zero-pad to 4 digits and
  combine with `acq_date` to build a real timestamp in cleaning.
- **`confidence` is `l`/`n`/`h`** for VIIRS (low/nominal/high). MODIS uses 0–100 instead —
  do not mix the two scales. Low-confidence detections are largely noise.
- **`frp`** is Fire Radiative Power in megawatts, the intensity proxy used to rank hotspots
  for Q1.

### Interview answers — `fetch_firms.py`

**"What exactly is a fire hotspot in your data?"**
A thermal anomaly detected by the VIIRS sensor in a 375 m pixel — the satellite reporting
that the pixel was abnormally hot during an overpass. It is not a confirmed fire, and not a
fire boundary. Industrial heat and sun glint cause false positives, and a fire burning
between overpasses or under cloud is missed entirely. So the data gives *evidence of
burning*, with both false positives and false negatives, which is why hotspots are buffered
rather than treated as exact points.

**"Why `_SP` rather than `_NRT`?"**
Near Real-Time products cover only about the last two months and receive less correction.
The study period is Jan–May 2024, so only Standard Processing — the science-quality
historical archive — contains it. Querying an NRT source for 2024 returns an empty result
with no explanatory error, which is exactly the kind of silent failure worth guarding
against; `data_availability()` verifies coverage before fetching.

**"Why query two satellites?"**
Suomi-NPP and NOAA-20 both carry VIIRS but pass at different local times, so each detects
fires the other misses — using both substantially improves detection. The cost is duplicate
detections of the same fire, removed by deduplicating on position, timestamp and satellite,
since FIRMS records carry no unique ID.

**"How do you handle the API's rate limits and error reporting?"**
The season is fetched in 5-day chunks because the area API serves at most 5 days per
request, with a one-second pause between requests against a limit of 5000 transactions per
10 minutes. More importantly, FIRMS reports errors as plain text with HTTP 200, so the
status code alone is not a success signal — each response body is checked to begin with the
real CSV header before being parsed.

**"Why buffer hotspots by 1 km instead of using the points directly?"**
The sensor's pixel is 375 m and the reported coordinate is the pixel centre, so the true
burning location is uncertain at roughly that scale. A 1 km buffer — about three pixel
widths — represents that uncertainty honestly and converts a set of points into an area
that can be unioned into a burn-risk footprint and queried with `$geoWithin`.

### Verify — check the key before fetching anything

```bash
.venv/bin/python -c "
from forestgeo.fetch_firms import key_status, data_availability
print(key_status()[:200])
av = data_availability()
print(av[av.data_id.str.contains('VIIRS', case=False, na=False)].to_string(index=False))
"
```

This confirms the key works and shows real date coverage per source — so a `FIRE_SEASON`
mismatch is found *before* 62 requests. Then one chunk in peak season:

```bash
.venv/bin/python -c "
from forestgeo.fetch_firms import fetch_firms
df = fetch_firms(season=('2024-03-01','2024-03-05'))
print(df[['latitude','longitude','acq_date','acq_time','confidence','frp']].head())
"
```

---

## §8 `forestgeo/geo.py` — the geometry engine

**Purpose.** Every geometry in the project passes through this file. It validates,
repairs, reprojects, buffers, measures and clips. If it is wrong, everything downstream
is wrong in ways that produce no error message.

### Vocabulary first

| term | meaning |
|---|---|
| **geometry** | a shape: a Point, a LineString (a path), or a Polygon (an area) |
| **valid** | a geometry that obeys the rules: a polygon's boundary must not cross itself, rings must be closed, interior rings must be inside the exterior |
| **CRS** | Coordinate Reference System — the rulebook mapping numbers to places on Earth |
| **WGS84** | World Geodetic System 1984, the global lat/long system GPS uses. EPSG code **4326** |
| **UTM** | Universal Transverse Mercator — the globe sliced into 60 north-south zones, each flattened onto a grid measured in metres. Zone 43N is **EPSG:32643** |
| **EPSG** | European Petroleum Survey Group — the registry that gives every CRS a number |
| **reproject** | convert coordinates from one CRS to another |
| **buffer** | grow (or shrink) a shape by a fixed distance in every direction |
| **simplify** | remove vertices that barely change a shape's outline |
| **clip** | cut a geometry down to the part inside another shape |

### Block 1 — the two transformers

```python
_to_m = Transformer.from_crs(CRS_WGS84, CRS_METRIC, always_xy=True).transform
_to_ll = Transformer.from_crs(CRS_METRIC, CRS_WGS84, always_xy=True).transform
```

Built **once at import**, not per call. Constructing a pyproj `Transformer` is
expensive — it loads a projection definition — and this project reprojects tens of
thousands of geometries, so rebuilding it each time would dominate the runtime.

`.transform` grabs the bound method itself, so `transform(_to_m, geom)` can hand it
straight to Shapely.

**`always_xy=True`** — the single most important argument in the project. Without it,
pyproj honours each CRS's *declared* axis order, and EPSG:4326 officially declares
**latitude first**. A `(76.65, 11.40)` pair would be read as latitude 76.65, longitude
11.40 — a point in the Arctic Ocean. Nothing raises. Every query simply returns nothing.

### Block 2 — `flatten()`

```python
def flatten(g):
    if hasattr(g, "geoms"):
        for part in g.geoms:
            yield from flatten(part)
    else:
        yield g
```

Geometries nest. A **MultiPolygon** contains Polygons; a **GeometryCollection** can
contain anything, including other collections. `flatten` walks that tree and yields only
the single-part leaves.

`hasattr(g, "geoms")` is how you ask "is this a multi-part geometry?" without importing
and checking six classes. `yield from` recurses, so arbitrarily deep nesting works.
It is a **generator**: it produces parts lazily rather than building a list.

### Block 3 — `_keep_family()`

```python
def _keep_family(g, family):
    parts = [p for p in flatten(g) if p.geom_type == BASE[family] and not p.is_empty]
    if not parts:
        return None
    if family == "point":
        return parts[0]
    if family == "line":
        return parts[0] if len(parts) == 1 else MultiLineString(parts)
    merged = shapely.union_all(parts)
    return merged if not merged.is_empty else None
```

Each collection holds exactly one *family* of geometry — `villages` holds Points,
`transport` holds lines, `forests` holds areas. This function enforces that.

Why it is needed is subtle: **`make_valid()` can change a geometry's type**. Repairing a
self-intersecting polygon may yield a `GeometryCollection` containing a polygon *and* a
leftover line fragment. MongoDB would happily index that collection, and then a
`$geoWithin` query would behave strangely. Dropping the strays here prevents it.

The three branches differ because the families differ. A Point collapses to one point. A
line keeps all its parts (a river really can be several disconnected segments). Polygons
are **unioned**, because overlapping fragments of what was one shape should become one
shape again.

### Block 4 — `clean_geometry()`, the gatekeeper

```python
def clean_geometry(g, family):
    if g is None or g.is_empty:
        return None
    if not g.is_valid:
        g = shapely.make_valid(g)
    kept = _keep_family(g, family)
    if kept is None:
        return None
    snapped = shapely.set_precision(kept, GRID)
    snapped = shapely.remove_repeated_points(snapped)
    if snapped.is_empty:
        return None
    if not snapped.is_valid:
        snapped = shapely.make_valid(snapped)
    return _keep_family(snapped, family)
```

Five stages, each fixing a specific failure MongoDB would otherwise produce:

1. **`make_valid`** repairs self-intersections ("bow-ties"), unclosed rings and
   misordered holes. Without it MongoDB rejects the document at index time with
   *"Can't extract geo keys … Edges cross"*.
2. **`_keep_family`** drops type changes `make_valid` introduced.
3. **`set_precision(GRID)`** snaps every coordinate onto a 1e-6 degree lattice (~0.11 m).
   This simultaneously rounds to 6 decimals *and* eliminates vertices that differ only
   in floating-point noise — the cause of MongoDB's *"Duplicate vertices"* error.
4. **`remove_repeated_points`** removes consecutive identical points.
5. **`_keep_family` again** because snapping can collapse a sliver polygon into a line.

`None` is returned rather than an exception raised, so the caller can **count** what was
discarded. Those counts become the validation report — evidence, not silence.

### Block 5 — the metric operations

```python
def buffer_m(g, dist_m, **kwargs):
    return to_wgs84(to_metric(g).buffer(dist_m, **kwargs))
```

Every one follows the same sandwich: **to metres → do the work → back to degrees**. The
caller never has to think about projection, and it is impossible to accidentally buffer
in degrees.

`area_km2` divides by `1e6` because UTM units are metres, so areas come out in square
metres: 1 km² = 1,000,000 m².

### Block 6 — `clip_to_bbox()`

```python
def clip_to_bbox(g, bbox=BBOX):
    clipped = g.intersection(bbox_polygon(bbox))
    return None if clipped.is_empty else clipped
```

Small function, large consequence. **Overpass returns the complete geometry of any
feature that merely touches your bounding box.** Measured on this project's data:

| layer | unclipped | clipped | outside the region |
|---|---|---|---|
| forests | 6,078 km² | 3,521 km² | **42%** |
| protected_areas | 2,959 km² | 1,551 km² | **48%** |

Without clipping, the project would report 93% forest cover instead of 54%.

### Block 7 — `as_point()`

```python
def as_point(g):
    if g.geom_type == "Point":
        return g
    return g.representative_point()
```

**`representative_point()`, not `centroid()`.** The centroid is the centre of mass, and
for a concave shape it can fall **outside** the polygon — a village mapped as a C-shaped
boundary around a hillside would be placed in the gap. `representative_point()` is
guaranteed to lie inside.

This matters concretely: **44 of 421 villages (10.5%)** arrived as polygons. Discarding
them would have lost a tenth of the settlement data silently.

### Interview answers — `geo.py`

**"Why does every geometry go through one function?"**
Because MongoDB rejects invalid geometry at index time, and because a single
choke-point makes the rules auditable: one place decides what valid means, one place
counts what was discarded, and the validation report is generated from those counts
rather than asserted.

**"What does `make_valid` actually fix?"**
Self-intersecting boundaries (a polygon crossing itself), unclosed rings, and holes that
are not properly contained. OSM polygons are drawn by hand so these occur naturally.
MongoDB's error is `Can't extract geo keys ... Edges cross`, raised when the index tries
to compute cell coverings for the shape.

**"Why `representative_point()` instead of `centroid()`?"**
The centroid of a concave polygon can lie outside it. For a village boundary wrapped
around a hill, the centroid may land on the hill, not in the village.
`representative_point()` trades mathematical centrality for the guarantee that the point
lies inside the shape — which is what "where is this village?" actually requires.

**"Why snap coordinates to a grid?"**
Two reasons in one operation. It rounds to 6 decimal places (~0.11 m), which is finer
than the data's own accuracy and keeps documents small. And it merges vertices that
differ only by floating-point noise, which is what triggers MongoDB's duplicate-vertex
rejection.

**"You found zero invalid geometries. Was the validation pointless?"**
No, and the honest framing matters. Zero of 46,779 raw features needed repair in this
extract, which is a finding worth reporting rather than hiding. The guard still earns
its place: MongoDB rejects invalid input at index time, so an unvalidated pipeline is
one bad OSM edit away from failing; and the union phase *constructs new geometry*, where
invalid output is a real possibility. The unit tests prove the repair path works even
though production data did not exercise it.

---

## §9 `forestgeo/clean.py` — where data decisions become code

**Purpose.** Convert raw downloads into validated, MongoDB-ready layers, and *count*
everything repaired or discarded. Those counts are the project's evidence that the data
was handled honestly.

### Block 1 — `FIELDS` and `DATE_FIELDS`

```python
FIELDS = {
    "villages": ["name", "place"],
    "sightings": ["species", ..., "precision", "is_roadkill", ...],
    ...
}
DATE_FIELDS = {"fire_hotspots": ["acq_datetime"], "sightings": ["event_date"]}
```

`FIELDS` is the contract for each collection: exactly these attributes reach MongoDB.
Raw OSM has hundreds of tag columns, nearly all empty; declaring the keepers makes the
documents small and the schema predictable.

`DATE_FIELDS` exists because of a format limitation. Processed layers are written as
**GeoJSON**, and the GeoJSON specification has **no date type** — a timestamp becomes a
string. So these columns are re-parsed back into real datetimes when the file is read.
They must become BSON `Date` values in MongoDB, otherwise the fire timeline would be
sorting text, where `"2024-10-01" < "2024-9-01"` is true.

### Block 2 — `clean_geometries()`, the audited loop

```python
for idx, g in gdf.geometry.items():
    if g is None or g.is_empty:
        stats["dropped_empty"] += 1; continue
    was_invalid = not g.is_valid
    if family == "point":
        g = geo.as_point(g)
    cleaned = geo.clean_geometry(g, family)
    if cleaned is None:
        stats["dropped_family"] += 1; continue
    if was_invalid:
        stats["fixed"] += 1
    ...
```

The loop is deliberately explicit rather than vectorised. Every exit path increments a
*named* counter, so the validation report can say **why** a feature disappeared:

| counter | meaning |
|---|---|
| `fixed` | geometry was invalid and `make_valid` repaired it |
| `dropped_empty` | null or empty geometry in the source |
| `dropped_family` | wrong geometry type for this collection |
| `dropped_bbox` | fell entirely outside the study region |
| `dropped_duplicate` | same identifier seen twice |
| `dropped_attr` | failed an attribute rule (low confidence, sliver, …) |

"We cleaned the data" is a claim. "37,666 in, 37,665 out, one dropped as the wrong
geometry family" is a result.

Note the order: **convert to point → clean → simplify → clip → clean again**. Clipping
comes late because it can change a geometry's type (a polygon sliced by the bbox edge
can become a MultiPolygon, a line can split), which is why the final `clean_geometry`
call exists.

### Block 3 — size-aware simplification

```python
if simplify and geo.area_km2(cleaned) > MIN_SIMPLIFY_AREA_KM2:
    cleaned = geo.clean_geometry(geo.simplify_m(cleaned, SIMPLIFY_TOLERANCE_M), family)
```

This condition was added after measuring real damage. Simplifying at a 10 m tolerance
applies the same 10 m to a 3,000 km² forest and to a 15 m farm pond — destroying the
pond. The first run lost **358 of 1,026 water bodies**; only 219 were genuinely tiny.
Restricting simplification to features above 1 hectare recovered **243 real ponds**
(668 → 911).

The general lesson: a tolerance is only meaningful relative to the size of the thing it
is applied to.

### Block 4 — deduplicating on the OSM id

```python
if "id" in gdf.columns:
    gdf = gdf.drop_duplicates(subset="id")
```

One line, found by noticing that Bandipur and Mudumalai each appeared **twice** in the
protected-area results — with identical ids and identical areas, so every sighting
inside them was double-counted.

Cause: `LAYERS["protected_areas"]` asks for `boundary=*` **and**
`leisure=nature_reserve`. osmnx issues a query per tag key and concatenates the results,
so an element matching more than one key comes back more than once. Deduplicating on the
OSM id in the shared reader fixed every layer at once — it also removed duplicates from
transport (37,814 → 37,666), rivers, forests (167 → 132), water and farmland.

**The damage was larger than it looked.** Q3 double-counted sightings for the duplicated
reserves, which is what exposed the bug. But Q4 was worse and quieter: it summarises
crossings with `pivot_table(..., aggfunc="sum")`, so the two identical Mudumalai rows were
*added together* and the reported figure of 212 crossing roads was exactly double the true
104. A duplicate row does not announce itself — it produces a plausible number. The only
reason it surfaced was re-running the query after the fix and noticing the value halve.

### Block 5 — the fire-hotspot timestamp

```python
df["acq_datetime"] = pd.to_datetime(
    df["acq_date"].astype(str) + " " + df["acq_time"].astype(int).astype(str).str.zfill(4),
    format="%Y-%m-%d %H%M", utc=True, errors="coerce")
```

FIRMS stores acquisition time as **HHMM in an integer column**: `745` means 07:45 UTC.
`zfill(4)` pads it back to `0745`; without the padding, `%H%M` would read `745` as
hour 74. `utc=True` makes the result timezone-aware, so the timeline is unambiguous.

Then low-confidence detections are dropped — VIIRS grades each as `l`/`n`/`h`, and `l`
is largely noise. That removed **201 of 1,765** hotspots.

### Block 6 — the three-tier sightings policy

```python
df["precision"] = "coarse"
df.loc[unc <= GBIF_MAX_UNCERTAINTY_M, "precision"] = "precise"
df.loc[unc.isna(), "precision"] = "unknown"
df["is_roadkill"] = df["dataset_name"].fillna("").str.startswith(ROADKILL_DATASET)
```

This is the most consequential decision in the project, and it is deliberately **not** a
filter.

The naive rule — "discard records less accurate than 1 km" — keeps 65% of records but
removes **100% of tigers, 100% of leopards and nearly all elephants**, because
iNaturalist *deliberately obscures* threatened-species locations to roughly 31 km to
prevent poaching. The surviving collection would be squirrels and macaques.

So nothing is discarded. Every record is **tagged**, and each query selects the tier it
can legitimately use:

- distance questions (*within 500 m of a road?*) use `precision = "precise"` only;
- the map shows coarse records in a separate layer labelled "location obscured";
- species inventory uses everything.

`is_roadkill` exists for a related reason: 479 precise records come from **Global
Roadkill Data**, a dataset *defined* by animals found on roads. Including it in "% of
sightings near a road" would measure the dataset's definition rather than animal
behaviour. Flagging rather than deleting lets the query report the figure **both ways** —
88.7% excluding it, 92.4% including it — which turns a confound into a finding.

### Interview answers — `clean.py`

**"How do you know your cleaning did not quietly destroy data?"**
Because every discard is counted by reason and published in
`outputs/validation_report.csv`. That is also how a real bug was caught: simplification
at a fixed 10 m tolerance was destroying small water bodies, visible as 358 dropped
features where only 219 were genuinely below the size floor. Making simplification
size-aware recovered 243 real ponds.

**"Why keep wildlife records you admit could be 31 km wrong?"**
Because the inaccuracy is not random error, it is deliberate protection applied to
exactly the species that matter most — elephant, tiger, leopard. Filtering them out
would silently bias the collection toward common, unthreatened animals. Tagging each
record by precision lets every query use the subset it is entitled to: distance
analysis uses only the precise tier, while species inventory and the map can honestly
show the rest, labelled.

**"Why is the roadkill dataset flagged rather than removed?"**
Removing it would hide the effect. Flagging allows the headline statistic to be reported
with and without it — 88.7% versus 92.4% — which demonstrates the bias quantitatively
instead of simply asserting it, and leaves the roadkill records available for the
analysis they are genuinely suited to.

**"What is the difference between validating and cleaning?"**
Validating asks whether a geometry obeys the rules; cleaning repairs what can be
repaired and discards what cannot. This project does both in one pass and records the
outcome of each, because a pipeline that silently drops rows is indistinguishable from
one that works.

---

## §10 `forestgeo/load.py` — Python objects into BSON

**Purpose.** Convert cleaned GeoDataFrames into MongoDB documents, create the indexes,
and insert without letting one bad record abort the batch.

### Vocabulary

| term | meaning |
|---|---|
| **BSON** | Binary JSON — MongoDB's storage format. Adds types JSON lacks: `Date`, `ObjectId`, 32/64-bit integers |
| **document** | one record, like a row but schema-free |
| **collection** | a group of documents, like a table |
| **index** | a side structure that lets the server find matching documents without reading them all |
| **2dsphere** | a geospatial index that treats coordinates as points on a sphere |
| **bulk write** | inserting many documents in one request |

### Block 1 — `_py()`, the type translator

```python
if isinstance(v, np.integer):  return int(v)
if isinstance(v, np.floating):
    f = float(v); return None if math.isnan(f) else f
if isinstance(v, pd.Timestamp):
    return v.tz_convert("UTC").to_pydatetime() if v.tzinfo else v.to_pydatetime()
```

pandas and NumPy use their own numeric types — `np.int64`, `np.float64` — and **PyMongo
cannot serialise them**. It raises `InvalidDocument: cannot encode object`. Every value
must become a plain Python type first.

The `NaN` handling matters more than it looks. **NaN is a valid float**, so it would be
stored as a *number* rather than as missing data, and `{"frp": {"$ne": None}}` would then
match it. Converting NaN to `None` makes it a genuine BSON null.

Timestamps are converted to UTC then made naive, because BSON stores dates as
milliseconds since the Unix epoch with no timezone attached. Converting first means the
instant is preserved.

### Block 2 — index before insert

```python
coll.drop()
coll.create_index([("geometry", "2dsphere")], name="geometry_2dsphere")
inserted = len(coll.insert_many(docs, ordered=False).inserted_ids)
```

The order is deliberate and is the opposite of what feels natural.

**Index first.** With the index already in place, MongoDB validates each document's
geometry *as it is inserted* and rejects the individual bad ones. Insert first and you
can load 46,000 documents successfully, then have `create_index` fail on the whole
collection because one polygon has crossing edges — leaving you with a loaded but
unindexed collection and no idea which document is at fault.

**`ordered=False`.** By default a bulk insert stops at the first error. Unordered means
MongoDB attempts every document and reports the failures at the end, so one bad record
costs one record rather than the rest of the batch.

**`coll.drop()`.** Idempotency: re-running the loader replaces the collection instead of
duplicating it. Dropping also removes the indexes, which is why they are recreated
immediately after.

### Block 3 — recording rejections

```python
except BulkWriteError as exc:
    inserted = exc.details.get("nInserted", 0)
    for err in exc.details.get("writeErrors", []):
        ...write source_id, geometry type and the error message to a .jsonl file
```

A `BulkWriteError` after an unordered insert is **partial success**, not failure —
`nInserted` says how many got through. Each failure is written to
`outputs/rejected_<collection>.jsonl` with the identifier and MongoDB's own message, so
a rejection is diagnosable rather than a number.

**JSONL** (JSON Lines) is one JSON object per line: appendable, and readable
line-by-line without parsing the whole file.

In this project the count was **0 rejected out of 46,208** — which is the expected result
when `clean.py` has done its job, and is worth stating as a verification of it.

### Block 4 — `geometry_types()` and the aggregation pipeline

```python
db[name].aggregate([
    {"$group": {"_id": "$geometry.type", "n": {"$sum": 1}}},
    {"$sort": {"n": -1}},
])
```

An **aggregation pipeline** is a list of stages, each transforming the stream of
documents it receives — MongoDB's equivalent of chained SQL clauses.

`$group` collapses documents sharing a key (`_id`) while accumulating values, exactly
like SQL's `GROUP BY`. The `$` prefix in `"$geometry.type"` means *the value of this
field*, and dotted notation reaches into nested documents.

This is what proves the project uses all three GeoJSON vector types:

```
villages   Point:421
transport  LineString:37,498 | MultiLineString:167
forests    Polygon:113  | MultiPolygon:6
```

### Interview answers — `load.py`

**"Why create the index before inserting rather than after?"**
So that invalid geometry is rejected per document instead of failing the whole index
build. With the index present, MongoDB validates each document on insert and
`ordered=False` lets the rest proceed; the failures are logged individually with their
identifiers. Building the index afterwards turns one bad polygon into a collection-wide
failure with no indication of which record caused it.

**"What does `ordered=False` change?"**
An ordered bulk insert stops at the first error, so a single bad document anywhere
aborts the remainder. Unordered attempts every document and reports all errors at the
end, which is what makes partial success possible and recoverable.

**"Why convert NumPy types manually?"**
PyMongo cannot encode `np.int64` or `np.float64` and raises `InvalidDocument`. More
subtly, NaN is a valid float and would be stored as a number rather than as missing
data, so queries testing for null would not match it. Converting NaN to `None` makes
absence explicit in the database.

**"How do you prove the database holds all three geometry types?"**
An aggregation pipeline grouping on `$geometry.type` per collection, which is run by the
loader and saved to `outputs/load_summary.csv`. It reports Point, LineString /
MultiLineString and Polygon / MultiPolygon with counts, taken from the database itself
rather than from the source files.

---

## §11 `forestgeo/queries.py` — the four spatial operations

**Purpose.** The heart of the project: four questions that only a spatial database can
answer.

### The operators, precisely

| operator | meaning | needs an index? | countable? | reference shape |
|---|---|---|---|---|
| `$nearSphere` | nearest first, sorted by distance | **yes, mandatory** | no | **Point only** |
| `$geoNear` | same, but returns the distance | **yes, mandatory** | n/a (pipeline) | **Point only** |
| `$geoWithin` | entirely inside | no (scans without) | yes | any shape |
| `$geoIntersects` | touches, crosses or is inside | no (scans without) | yes | any shape |

Four facts behind that table, each a common exam question:

1. **`$nearSphere` fails without an index.** Not slower — it refuses:
   `unable to find index for $geoNear query`. `$geoWithin` and `$geoIntersects` fall
   back to a collection scan instead.
2. **`$nearSphere` cannot be used in `count_documents()`.** Counting has no ordering, so
   a sorting operator is rejected. Use `$geoWithin` + `$centerSphere` to count within a
   radius.
3. **Units differ.** `$maxDistance` and `$geoNear` distances are **metres** when the
   reference is GeoJSON. `$centerSphere` takes its radius in **radians** — kilometres
   divided by the Earth's radius, 6378.1.
4. **`$geoWithin` vs `$geoIntersects`** is the difference between *contained* and
   *touching*. A road entering a reserve and leaving again is not entirely inside it, so
   `$geoWithin` misses it and `$geoIntersects` finds it. For lines against polygons,
   `$geoIntersects` is almost always the correct choice.

### Q1 — villages near the most intense fires

```python
near = db.villages.aggregate([
    {"$geoNear": {
        "near": point(lon, lat),
        "distanceField": "distance_m",
        "maxDistance": max_m,
        "spherical": True,
    }},
])
```

**`$geoNear` rather than `$nearSphere`** because `distanceField` writes the computed
distance into each returned document. `find()` with `$nearSphere` returns results in
distance order but never tells you the distances — and the report needs the numbers.

**`$geoNear` must be the first stage of a pipeline.** It is the stage that uses the
index to produce a sorted stream; later stages consume that stream.

**`spherical: True`** tells MongoDB to compute great-circle distances on the sphere
rather than planar distances. Required for 2dsphere indexes.

**FRP** (Fire Radiative Power, megawatts) is the intensity proxy, so sorting hotspots by
FRP descending and taking the top 20 gives the season's most severe detections.

### Q2 — sightings near roads, and the two filters that make it honest

```python
query = {}
if precision:        query["precision"] = precision      # "precise" only
if exclude_roadkill: query["is_roadkill"] = False
```

The spatial part is routine. The **methodology** is the interesting part:

- A record that may be 31 km off cannot be tested against a 500 m buffer, so only the
  `precise` tier is used.
- The roadkill dataset is excluded because it is *defined* by road proximity; including
  it makes the statistic circular.

Result: **88.7%** of 962 precise non-roadkill sightings lie within 500 m of a road;
**92.4%** if the roadkill records are included. Reporting both quantifies the bias.

A caution worth stating plainly in the report: 88.7% does **not** mean wildlife prefers
roads. It largely reflects **observer bias** — people record animals where people are,
and people are on roads. Median distances of 8–60 m make that obvious. The honest claim
is about where *observations* occur, not where *animals* live.

### Q3 — `$geoWithin` counts per protected area

```python
inside = {"geometry": {"$geoWithin": {"$geometry": pa["geometry"]}}}
n_sight = db.sightings.count_documents(inside)
```

The polygon comes straight from another document in the database — `pa["geometry"]` is
already GeoJSON, so it can be used directly as a query shape. No conversion needed.

Densities are computed as counts per km², because raw counts favour large reserves.
That reveals the project's clearest finding: **Sathyamangalam Tiger Reserve has the most
fire detections (52) but the fewest sightings (14)**, while **Mudumalai has 533
sightings** at 1.589 per km².

### Q4 — `$geoIntersects` for crossings

```python
crosses = {"geometry": {"$geoIntersects": {"$geometry": pa["geometry"]}}}
n = db.transport.count_documents({**crosses, "kind": kind})
```

`{**crosses, "kind": kind}` merges two dictionaries, combining a spatial predicate with
an ordinary field filter. MongoDB ANDs them, so this asks "lines of this kind that cross
this reserve" and uses both the 2dsphere and the `kind` index.

### `count_within_km()` — the `$centerSphere` unit trap

```python
def count_within_km(db, collection, lon, lat, km):
    return db[collection].count_documents({
        "geometry": {"$geoWithin": {"$centerSphere": [[lon, lat], km_to_radians(km)]}}
    })
```

This exists because `$nearSphere` cannot be counted. `$centerSphere` takes
`[[lon, lat], radius_in_radians]`, and a **radian** is the angle subtended at the
Earth's centre — so dividing kilometres by the Earth's radius (6378.1 km) converts.
Passing metres here would ask for a radius of thousands of radians, i.e. the entire
planet, many times over. No error would be raised.

### Interview answers — `queries.py`

**"When would you use `$geoWithin` rather than `$geoIntersects`?"**
`$geoWithin` when containment is the question — is this point inside the reserve?
`$geoIntersects` when any contact counts, which is the right test for linear features: a
road that crosses a reserve and exits is not contained by it, so `$geoWithin` would
report zero crossings.

**"Why does `$nearSphere` require an index when `$geoWithin` does not?"**
`$nearSphere` returns results ordered by distance. Producing that order without an index
would mean computing the distance to every document and sorting them, so MongoDB refuses
rather than silently performing an expensive operation. `$geoWithin` is a filter with no
ordering requirement, so it can be evaluated by scanning.

**"Why `$geoNear` instead of `$nearSphere` in Q1?"**
`$geoNear` has a `distanceField` option that writes the computed distance into each
result. `find()` with `$nearSphere` returns documents in distance order but does not
expose the distances, and the analysis needs the actual metres.

**"Your result says 88.7% of sightings are within 500 m of a road. Does wildlife prefer
roads?"**
No — that figure describes observations, not animals. Records are overwhelmingly
collected by people, and people travel on roads, so the distribution of *sightings* is
road-biased regardless of where animals are. The median distance of 8–60 m makes the
effect obvious. It is reported as a statement about sampling, and it is why the roadkill
dataset was excluded as well: that would have compounded the same bias.

---

## §12 `forestgeo/unions.py` — the part MongoDB cannot do

**Purpose.** Build new geometry by merging existing geometry, then store it back in
MongoDB so it can be queried.

### Why this file is the centre of the project

MongoDB can *test* spatial relationships. It cannot *construct* geometry — there is no
union, no intersection, no buffer that produces a new shape. So:

```
MongoDB points -> Shapely (buffer, union, intersect) -> MongoDB polygons -> $geoWithin
```

That round trip is the project's main technical argument: use each tool for what it is
good at, and keep the result queryable.

### Block 1 — morphological closing, the habitat block

```python
metric = [geo.to_metric(g) for g in forests]
grown  = [g.buffer(HABITAT_GAP_CLOSE_M) for g in metric]   # +50 m
merged = shapely.union_all(grown)
closed = merged.buffer(-HABITAT_GAP_CLOSE_M)               # -50 m
```

The buffer-out-then-in sequence is a **morphological closing**, borrowed from image
processing.

The problem: two forest patches separated by a 30 m gap — a track, or just a seam
between two mappers' work — are not ecologically separate, but as polygons they are
disjoint and `union_all` would keep them apart.

The fix: grow both by 50 m so they overlap and merge, then shrink the merged shape by
50 m to restore the original outline. The gap is sealed; the exterior is unchanged.

`shapely.union_all()` is the actual union — it dissolves a list of geometries into one,
and is far faster than repeatedly calling `a.union(b)` because it builds the result in a
single pass.

Then fragments below `MIN_HABITAT_BLOCK_KM2` (1 km²) are dropped: an isolated half-
hectare of trees is not a habitat block.

**Result: 119 forest polygons → 23 blocks, 3,520 km².**

### Block 2 — the burn-risk footprint

```python
circles = [geo.to_metric(g).buffer(HOTSPOT_BUFFER_M) for g in hotspots]
merged = shapely.union_all(circles).simplify(SIMPLIFY_M, preserve_topology=True)
```

Each hotspot becomes a 1 km circle and the overlapping circles merge into continuous
areas.

**Why buffer at all?** A hotspot is the *centre of a 375 m VIIRS pixel*, not an ignition
point. Treating it as exact would overstate precision. A 1 km buffer — about three pixel
widths — represents that uncertainty honestly, and converts a cloud of points into the
area plausibly affected.

**`preserve_topology=True`** makes `simplify` refuse to produce an invalid result.
Without it, aggressive simplification can turn a polygon's boundary into a
self-intersecting loop.

**Result: 1,564 points → 113 parts, 1,051 km².**

### Block 3 — intersection, the critical zone

```python
inter = geo.to_metric(burn[0]).intersection(geo.to_metric(hab[0]))
```

Where the burn footprint overlaps the 2 km habitat buffer: areas that both burned *and*
sit within reach of continuous forest. **862 km², 97 parts.**

This is the cross-theme geometry — fire and habitat combined into one shape, which
MongoDB can then query against villages, roads and wildlife.

### Block 4 — storing it

```python
doc = {"zone_type": zone_type, "params": params, "input_count": input_count,
       "n_parts": len(parts), "area_km2": ..., "geometry": mapping(geom),
       "created_at": ...}
size_mb = len(str(doc["geometry"])) / 1e6
if size_mb > MAX_DOC_MB:
    raise ValueError(...)
```

**`params` and `input_count` make the result reproducible.** A polygon in a database with
no record of how it was made is not evidence. Storing `{"buffer_m": 1000,
"simplify_m": 20}` alongside it means the geometry can be regenerated and defended.

**The size guard exists because BSON documents are capped at 16 MB.** A union of 1,564
buffered circles can carry a lot of vertices; the check fails loudly with a clear
instruction rather than letting PyMongo raise an opaque error. Actual sizes came out at
0.02–0.14 MB, comfortably clear.

`delete_many({"zone_type": ...})` before inserting keeps the script idempotent.

### Proof it worked

Once stored, the computed geometry is queried with ordinary operators — which is the
entire point:

```
villages        $geoWithin burn_risk_footprint  -> 111
sightings       $geoWithin burn_risk_footprint  -> 375
protected_areas $geoIntersects habitat_block    -> 9
tracks          $geoIntersects habitat_block    -> 337
villages        $geoWithin critical_zone        -> 79
```

### Interview answers — `unions.py`

**"Why not do the union in MongoDB?"**
MongoDB has no union operator. Its geospatial support is for *querying* relationships
between existing shapes, not for constructing new ones — there is no union,
intersection or buffer that returns geometry. So the construction is done in Shapely, in
a metric CRS so the distances are meaningful, and the result is written back into a
collection where MongoDB's operators can query it normally.

**"What is the buffer-out, buffer-in trick for?"**
It is a morphological closing. Forest patches separated by a narrow gap — a track, or a
seam between mappers — are ecologically continuous but geometrically disjoint. Growing
every polygon by 50 m makes neighbours overlap so the union merges them; shrinking the
merged result by the same 50 m restores the original outer boundary with the internal
gaps sealed.

**"Why buffer fire hotspots instead of using the points?"**
Because a hotspot is the centre of a 375 m sensor pixel, not a located fire. Using the
raw point would claim a precision the instrument does not have. A 1 km buffer, roughly
three pixel widths, represents that uncertainty and converts isolated detections into a
continuous area that can be unioned and queried.

**"How do you know the stored union is correct?"**
Two ways. The parameters and input counts are stored with the geometry, so it can be
regenerated. And the intersection was validated against MongoDB independently: counting
villages inside the Shapely-computed critical zone gives 79, and asking MongoDB for
villages inside *both* source zones with two `$geoWithin` predicates also gives 79.

---

## §13 `forestgeo/cross_theme.py` — combining every theme into one answer

**Purpose.** Answer the project's actual question: *which villages are most exposed, and
to what combination of pressures?* This is the file where four separate collections
finally produce one ranked list.

### Block 1 — the three measurements per village

```python
circle = {"$geoWithin": {"$centerSphere": [[lon, lat], radius_rad]}}
n_hot   = db.fire_hotspots.count_documents({"geometry": circle})
nearest = db.fire_hotspots.aggregate([
    {"$geoNear": {"near": point(lon, lat), "distanceField": "distance_m",
                  "spherical": True}},
    {"$limit": 1},
])
in_burn = db.villages.count_documents(
    {"_id": v["_id"], "geometry": {"$geoWithin": {"$geometry": burn["geometry"]}}}) > 0
```

Three different operators, each chosen because the others cannot do the job:

- **Counting within a radius** uses `$geoWithin` + `$centerSphere`, because
  `$nearSphere` is forbidden inside `count_documents()`.
- **Distance to the nearest** uses `$geoNear`, because it is the only form that returns
  the distance.
- **Inside a computed zone** uses `$geoWithin` against the Shapely-built polygon from
  §12 — a query against geometry the database did not create.

The `in_burn` test is a small idiom worth noting: rather than fetching the zone and
testing in Python, it asks MongoDB whether *this specific village* (`_id`) also matches
the spatial predicate. The spatial reasoning stays in the database.

### Block 2 — the risk score, and why its first version was wrong

```python
WEIGHTS = {"in_critical_zone": 35, "in_burn_footprint": 25,
           "hotspot_density": 25, "proximity": 15}
```

Weights are explicit constants, not buried arithmetic, so they can be challenged and
changed. Each component is normalised to 0–1, so the total is 0–100.

The first implementation capped hotspot counts at 40 and scaled linearly:

```python
density = df.n_hotspots_5km.clip(upper=40) / 40          # WRONG
```

Measuring the output exposed the flaw. Hotspot counts per village are heavily
**right-skewed** — median 8, mean 25, maximum 239 — so **68 of 421 villages exceeded the
cap** and all scored identically on density. The top 15 villages scored 98.6–99.8, which
is not a ranking.

The fix is the standard treatment for skewed count data:

```python
peak = max(int(df.n_hotspots_5km.max()), 1)
density = np.log1p(df.n_hotspots_5km) / np.log1p(peak)
```

**`log1p(x)` is log(1 + x)**, used instead of plain `log` so that a village with zero
hotspots maps to 0 rather than negative infinity. The compression spreads the top end:
10 → 0.44, 40 → 0.68, 100 → 0.84, 239 → 1.00.

Scores above 95 fell from 41 villages to 16, and the ranking now tracks exposure.

The `proximity` component inverts distance, so 1 means a hotspot at the village and 0
means the nearest is at the search radius:

```python
prox = (1 - (df.nearest_hotspot_m.fillna(radius_m) / radius_m)).clip(lower=0)
```

### Block 3 — validating Shapely against MongoDB

```python
via_shapely = db.villages.count_documents(
    {"geometry": {"$geoWithin": {"$geometry": crit["geometry"]}}})
via_mongo = db.villages.count_documents({"$and": [
    {"geometry": {"$geoWithin": {"$geometry": burn["geometry"]}}},
    {"geometry": {"$geoWithin": {"$geometry": hab["geometry"]}}},
]})
```

Two routes to the same answer. The critical zone was built in Shapely as *burn footprint
∩ habitat buffer*, so a village inside it must also be inside **both** source zones.
`$and` combines the two predicates and MongoDB evaluates them independently.

**Both return 79.** That agreement is a genuine cross-check: it validates the Shapely
intersection against the database's own spatial reasoning, using two different engines
and two different representations.

### The result

| | |
|---|---|
| villages scored | 421 |
| in the burn footprint | 111 |
| in the critical zone | 79 |
| highest-risk village | Thoraihatty — 239 hotspots within 5 km, nearest 372 m |

Inside the critical zone: 79 villages, 1,460 hotspots, 125 precise sightings, 1,959
roads, 256 tracks, 4 railway segments and 75 farmland parcels.

### Interview answers — `cross_theme.py`

**"How is the risk score constructed, and can you defend the weights?"**
Four normalised components combined linearly: membership of the critical zone (35),
membership of the burn footprint (25), hotspot density within 5 km (25) and proximity to
the nearest hotspot (15). The weights are explicit constants, so they are a stated
assumption rather than a hidden one, and the whole table can be regenerated with
different weights to test sensitivity.

**"Why a logarithm in the density term?"**
Because the counts are heavily right-skewed: median 8, maximum 239. The original linear
scale with a cap at 40 put 68 of 421 villages at the same maximum, so the score stopped
discriminating — the top 15 all scored above 98.6. `log1p` compresses the long tail and
restores ordering across the top end. `log1p` rather than `log` so that zero hotspots
maps to zero instead of negative infinity.

**"How do you know the Shapely intersection is correct?"**
It was checked against MongoDB independently. Counting villages inside the
Shapely-computed critical zone gives 79; asking MongoDB for villages inside both source
zones using two `$geoWithin` predicates combined with `$and` also gives 79. Two
different engines, two different representations, the same answer.

**"Why is counting done with `$centerSphere` rather than `$nearSphere`?"**
`$nearSphere` sorts by distance and cannot be used inside `count_documents()` — counting
has no ordering, so MongoDB rejects it. `$geoWithin` with `$centerSphere` expresses the
same circular region as a filter. Its radius is in radians, so kilometres are divided by
6378.1.

---

## §14 `forestgeo/benchmark.py` — measuring the index

**Purpose.** Demonstrate, with numbers, what the 2dsphere index is worth — and under
what conditions it is worth nothing.

### Vocabulary from `explain()`

| term | meaning |
|---|---|
| **COLLSCAN** | collection scan — every document read and tested |
| **IXSCAN** | index scan — only matching index entries read |
| **FETCH** | retrieve the full document for an index entry |
| **nReturned** | documents the query returned |
| **totalDocsExamined** | documents the server had to read — the real cost |
| **totalKeysExamined** | index entries read |
| **executionTimeMillis** | time spent *inside the server* |
| **selectivity** | the fraction of the collection a query returns |

### Block 1 — why server-side timing

```python
plan = cur.explain()
stats = plan.get("executionStats", {})
```

Timing a query from Python measures network round-trip, BSON decoding and Python object
construction as well as the query. On Atlas the network alone can exceed the query time.
`executionTimeMillis` is measured inside the server, so it isolates the database's work.

### Block 2 — forcing a collection scan

```python
cur = cur.hint([("$natural", 1)])
```

**`$natural` means "read documents in storage order"**, which forces a COLLSCAN without
touching the indexes. The alternative — dropping the index, measuring, rebuilding — would
be far slower and would change the collection between measurements, making the two runs
incomparable.

### Block 3 — unwrapping the plan tree

```python
while stage.get("stage") in ("FETCH", "SHARDING_FILTER", "LIMIT", "SKIP") \
        and "inputStage" in stage:
    stage = stage["inputStage"]
```

Execution plans are **trees**: a `FETCH` stage wraps the `IXSCAN` that feeds it. Reading
the top stage alone would report `FETCH` and hide whether an index was used, so the loop
descends to the access method underneath.

### Block 4 — the finding, and the mistake that produced it

The first version tested only one query — a quarter of the bounding box, returning ~25%
of the collection. The index barely won: 158 ms versus 197 ms, and on one real query the
index was *slower* (speed-up 0.8).

That was not a bug, it was **low selectivity**, and it is the most interesting result in
the phase. So the benchmark now runs two selectivities:

| at 250,000 documents | indexed | COLLSCAN | advantage |
|---|---|---|---|
| **selective (~0.2%)** | **1 ms**, 748 examined | 180 ms, 250,000 examined | **180× / 334×** |
| **broad (~25%)** | 154 ms, 84,972 examined | 197 ms, 250,000 examined | 1.3× |

The indexed selective query stays essentially flat (0, 0, 0, 1 ms) as the collection
grows 25×, while the scan grows linearly (7 → 35 → 72 → 180 ms).

**Why the broad query gains so little:** the index must read a quarter of the entries
*and then fetch* a quarter of the documents, while the scan reads each document once
with no index lookups. Past roughly a third selectivity, scanning wins outright — which
is why query planners sometimes ignore an index on purpose.

### Block 5 — honest plotting

```python
grp[field].clip(lower=0.1)
...
fig.text(..., "Values of 0 ms are plotted at 0.1 ms because a log axis cannot show zero.")
```

A logarithmic axis cannot represent zero, and the indexed selective query genuinely
measures 0 ms at smaller sizes. Clipping keeps the line visible; the caption says so,
rather than implying sub-millisecond precision that was not measured.

Also note `random.Random(42)` — a **fixed seed** means the synthetic points are identical
on every run, so the benchmark is reproducible.

### Running the same benchmark on Atlas — the clearest result in the project

The real-collection comparison was re-run against a MongoDB Atlas M0 cluster in Mumbai.
Two things emerged that a local-only run could never have shown.

**1. `totalDocsExamined` is identical on both engines.**

| query | docs examined, local | docs examined, Atlas |
|---|---|---|
| `sightings $geoWithin` protected area | 744 | 744 |
| `fire_hotspots $geoWithin` protected area | 29 | 29 |
| `transport $geoIntersects` protected area | 277 | 277 |
| `villages $geoWithin` burn footprint | 414 | 414 |

Same data, same query plan, same work — on different hardware in a different country.
That is why the report leads with documents examined rather than milliseconds: it is
deterministic and hardware-independent, whereas timing is neither.

**2. Wall-clock timing on Atlas is useless, and the numbers prove it.**

Measuring the same query from Python with a stopwatch, versus `executionTimeMillis`:

| mode | server time | wall-clock | network overhead |
|---|---|---|---|
| indexed | **0 ms** | 97.3 ms | 97.3 ms |
| COLLSCAN | **5 ms** | 98.1 ms | 93.1 ms |

A stopwatch reports **97.3 ms versus 98.1 ms** — a difference well inside the noise, from
which the honest conclusion would be "the index makes no difference". It is wrong. The
round trip to Mumbai is roughly 95 ms, and it swamps a 5 ms query completely.

`explain("executionStats")` measures inside the server and reports 0 ms against 5 ms —
the real result. This is the concrete justification for the project rule that benchmarks
must use server-side timing rather than wall-clock alone.

The `transport $geoIntersects` case is the clearest on Atlas: **24 ms indexed versus
763 ms scanned, a 32× gain** across 37,665 LineStrings — closely matching the 29.7×
measured locally, because the underlying work is the same.

The 250,000-point synthetic scale test was **not** re-run on Atlas. Pushing a quarter of
a million documents over the network into a shared, throttled free tier would measure the
upload, not the index. It is stated in the report as a locally-measured result, which is
the appropriate place for a controlled scale experiment.

### Interview answers — `benchmark.py`

**"Why use `explain()` instead of timing the query in Python?"**
Because a Python-side timer measures network latency, BSON decoding and object
construction alongside the query. `explain("executionStats").executionTimeMillis` is
measured inside the server and isolates the database's own work — which matters even
more on Atlas, where the round trip can exceed the query.

**"How did you force a collection scan without dropping the index?"**
`.hint({"$natural": 1})`, which instructs MongoDB to read documents in storage order,
bypassing all indexes. Dropping and rebuilding a 2dsphere index would take far longer and
would alter the collection between measurements, so the two runs would not be comparable.

**"Your index was only 1.3× faster on one test. Does that undermine the argument?"**
No — it is the finding. Index value depends on selectivity. The 1.3× case returns 25% of
the collection, so the index reads a quarter of the entries and then fetches a quarter of
the documents, while the scan reads everything once with no lookups. On a selective
query returning 0.2%, the same index is 180× faster and examines 334× fewer documents.
The correct conclusion is that indexes accelerate selective queries, which is why query
planners sometimes choose a scan deliberately.

**"Which number matters more, time or documents examined?"**
`totalDocsExamined`, because it is hardware-independent and deterministic — it came out
identical on a local server and on an Atlas cluster in Mumbai. Timing varies with cache
state, memory, competing load and, on Atlas, network latency.

**"You ran this on Atlas as well. What changed?"**
The query plans and documents examined were identical; only the timings moved. The
instructive part was the wall-clock comparison: measured from Python, the indexed query
took 97.3 ms and the collection scan 98.1 ms, which would suggest the index is worthless.
It is an artefact — about 95 ms of that is the round trip to Mumbai. Server-side
`executionTimeMillis` reports 0 ms against 5 ms, the real difference. It is the clearest
demonstration in the project of why benchmarks must be measured inside the server.

---

## §15 `forestgeo/mapviz.py` — the interactive map

**Purpose.** One self-contained HTML file showing every layer, with villages coloured by
risk and an animated fire timeline.

**Folium** wraps **Leaflet.js**, the standard open-source web mapping library, so the
output needs no server — the file opens directly in a browser.

### The coordinate exception

```python
centre = [(south + north) / 2, (west + east) / 2]   # FOLIUM: [lat, lon]
```

**This is the only place in the project where latitude comes first.** GeoJSON and
MongoDB use `[longitude, latitude]`; Folium's `location=` and `fit_bounds()` take
`[latitude, longitude]`. Every flip in this file is commented, because mixing them
produces a map centred in the wrong hemisphere with no error.

Note that `folium.GeoJson()` does **not** flip — it consumes GeoJSON directly, so
geometry read from MongoDB is passed through untouched. Only explicitly positioned
elements (markers, map centre, bounds) use the reversed order.

### Layer design

Each theme is a `FeatureGroup`, which becomes one checkbox in the layer control. Most
default to `show=False` so the map opens readable rather than as an unreadable stack;
protected areas, the critical zone and villages start visible.

### Two decisions that are about honesty, not aesthetics

**Obscured sightings get their own layer.**

```python
coarse = folium.FeatureGroup(name="sightings (location obscured, +/-31 km)", show=False)
```

Drawing a displaced elephant record as an ordinary point would imply a precision the
data does not have. A separate, labelled, off-by-default layer shows the records without
making a false claim.

**Only main road classes are drawn.**

```python
MAP_ROAD_CLASSES = ["motorway", "trunk", "primary", "secondary", "tertiary"]
```

Residential and unclassified streets are **34,387 of 37,665 transport features (91%)**
and almost all of the file size — the map was 24 MB before, 10 MB after. They remain in
MongoDB and every query still uses the complete network; only the display is reduced.
That distinction belongs in the report: it is a rendering decision, not a data one.

### The fire timeline

```python
TimestampedGeoJson({...}, period="P1D", duration="P2D", ...)
```

`TimestampedGeoJson` animates features along a time axis. Each feature needs a `time`
property as an **ISO 8601** string (`2024-03-25T08:08:00+00:00`), which is why
`acq_datetime` had to be a real date rather than text.

`period="P1D"` is **ISO 8601 duration notation** — P(eriod) 1 D(ay) — so the slider steps
one day at a time. `duration="P2D"` keeps each detection visible for two days, so the
animation shows fire activity rather than single-frame flickers.

Marker radius scales with FRP (`3 + min(frp, 100) / 12`), capped so one extreme fire
cannot produce a circle covering the region.

### Verified output

11 toggleable layers, time slider, legend, two working basemaps, **10.0 MB**:

```
protected areas (9) · forests (119) · water bodies (901) · farmland (811)
rivers (2057) · transport: road main classes (1799) / track (1242) / railway (237)
habitat block (1) · burn-risk footprint (1) · critical zone (1)
villages (421, coloured by risk) · sightings (precise, clustered) + obscured
fire hotspots (1564, animated daily)
```

The CartoDB basemap was removed because **CartoDB now requires an API key** — it would
have failed silently, showing blank tiles. OpenTopoMap replaced it, and its contour
shading suits a hill region better.

### Interview answers — `mapviz.py`

**"You said coordinates are always `[longitude, latitude]`, but the map uses
`[latitude, longitude]`. Which is it?"**
Storage and querying are always longitude-first, because that is what GeoJSON and
MongoDB require. Folium's `location=` and `fit_bounds()` are the single exception — they
follow the conventional spoken order. `folium.GeoJson()` does not flip, since it consumes
GeoJSON directly. Every flip is marked in the code, because confusing the two produces a
map in the wrong hemisphere with no error.

**"Why are obscured sightings on a separate layer?"**
Because drawing them as ordinary points would assert a precision the data does not have —
those locations are deliberately displaced by up to about 31 km. A separate, clearly
labelled layer, off by default, shows that the records exist without implying they are
located.

**"Why does the map show only main roads when the database has 37,665?"**
Residential and unclassified streets are 91% of the features and nearly all of the file
size, while contributing nothing to a regional fire and habitat narrative. Removing them
from the *display* took the file from 24 MB to 10 MB. Every query still uses the complete
network — it is a rendering decision, and it is stated as one.

---

## §16 The scripts

Each script is a thin wrapper: it orchestrates, prints and saves. All the logic lives in
`forestgeo/`, so the same functions can be reused, tested, or called from a notebook.

| script | phase | produces |
|---|---|---|
| `check_connection.py` | 0 | verifies CRS, reprojection, MongoDB, folders |
| `fetch_data.py` | 1 | `data/raw/*`, `outputs/data_inventory.csv` |
| `clean_validate.py` | 2 | `data/processed/*.geojson`, `outputs/validation_report.csv` |
| `load_mongo.py` | 3 | 9 MongoDB collections, `outputs/load_summary.csv` |
| `create_indexes.py` | 3b | `outputs/index_report.csv`, the no-index error text |
| `core_queries.py` | 4 | `outputs/q1…q4*.csv`, `outputs/notes.md` |
| `build_unions.py` | 5 | `derived_zones`, `outputs/derived_zones_summary.csv` |
| `cross_theme.py` | 6 | `outputs/q6_village_risk.csv` |
| `benchmark.py` | 7 | `outputs/benchmark.csv`, `benchmark.png`, `explain/*.json` |
| `build_map.py` | 8 | `outputs/forestgeo_map.html` |

Three conventions hold across all ten:

**Idempotent.** Every script can be re-run safely — collections are dropped and
reloaded, files replaced not appended. A pipeline you are afraid to re-run is a pipeline
you cannot debug.

**Exit codes.** `main()` returns 0 for success, non-zero for failure, and
`raise SystemExit(main())` makes that the process exit code, so steps can be chained
with `&&` and a failure stops the chain.

**Everything is saved.** Each result is written to `outputs/` as CSV, JSON or HTML, so
the report cites files rather than remembered numbers.

---

## §17 Results

Run on 2026-10-04, local MongoDB 8.0.32, Python 3.14.

### Data

| collection | geometry | raw | clean | note |
|---|---|---|---|---|
| villages | Point | 421 | 421 | 44 arrived as polygons → representative points |
| transport | LineString | 37,666 | 37,665 | 13,830 km |
| rivers | LineString | 2,057 | 2,057 | 2,769 km |
| protected_areas | Polygon | 13 | **9** | 4 dropped: duplicates + sub-0.1 km² artefacts |
| forests | Polygon | 132 | 119 | 3,521 km² clipped (54% of region) |
| water_bodies | Polygon | 1,024 | 901 | 123 slivers below 25 m² |
| farmland | Polygon | 812 | 811 | |
| fire_hotspots | Point | 1,765 | 1,564 | 201 low-confidence dropped |
| sightings | Point | 2,670 | 2,661 | 72 species; tiered by precision |
| **total** | | **46,779** | **46,208** | **0 invalid, 0 rejected by MongoDB** |

The reduction happens in two distinct steps, and the report should state both:

| stage | features | removed |
|---|---|---|
| raw files on disk | 46,779 | — |
| after deduplicating on the OSM `id` | 46,560 | 219 duplicates |
| valid output | 46,208 | 352 by cleaning |

The 219 duplicates are the ones a layer receives when its tag spec lists several keys and
Overpass returns the same element once per key. They never reach the database.

### Derived zones (Shapely → MongoDB)

| zone | inputs | parts | area |
|---|---|---|---|
| habitat_block | 119 forests | 23 | 3,520 km² |
| burn_risk_footprint | 1,564 hotspots | 113 | 1,051 km² |
| habitat_buffer | habitat_block + 2 km | 3 | 5,225 km² |
| critical_zone | intersection | 97 | 862 km² |

### Spatial queries

- **Q1** `$geoNear` — villages within 5 km of the 20 most intense hotspots.
- **Q2** `$geoNear` — **88.7%** of 962 precise non-roadkill sightings within 500 m of a
  road; **92.4%** including roadkill records. Interpreted as observer bias.
- **Q3** `$geoWithin` — Sathyamangalam Tiger Reserve: most fires (52), fewest sightings
  (14). Mudumalai: 533 sightings, 1.589/km².
- **Q4** `$geoIntersects` — Mudumalai crossed by 104 roads, 20 tracks, 20 rivers.
- **Q6** cross-theme — 79 of 421 villages in the critical zone; highest risk
  Thoraihatty (239 hotspots within 5 km, nearest 372 m).

### Index benchmark, 250,000 synthetic points

| selectivity | indexed | COLLSCAN | gain |
|---|---|---|---|
| ~0.2% | 1 ms, 748 docs | 180 ms, 250,000 docs | **180× / 334×** |
| ~25% | 154 ms, 84,972 docs | 197 ms, 250,000 docs | 1.3× |

`$nearSphere` without an index: `unable to find index for $geoNear query`.
`$geoWithin` without an index: works, by scanning.

---

## Glossary

### Spatial and geometry

| term | meaning |
|---|---|
| **GeoJSON** | the JSON format for geographic shapes. Coordinates are always `[longitude, latitude]` |
| **Point / LineString / Polygon** | the three vector geometry types: a location, a path, an area |
| **Multi\*** | several parts treated as one feature (MultiPolygon, MultiLineString) |
| **GeometryCollection** | a mixed bag of geometry types in one object |
| **vertex** | a corner point defining a line or polygon |
| **ring** | a closed loop of vertices forming a polygon boundary; the first and last point are identical |
| **valid geometry** | one obeying the rules: no self-intersecting boundary, closed rings, holes inside the exterior |
| **bow-tie** | a polygon whose boundary crosses itself — the classic invalid shape |
| **WKT** | Well-Known Text — geometry as a string, e.g. `POLYGON((76.2 11.1, ...))`. Used by GBIF |
| **WKB** | Well-Known Binary — the same thing in binary |
| **bounding box / bbox** | the rectangle enclosing an area, as `(west, south, east, north)` |
| **buffer** | growing (or shrinking, if negative) a shape by a fixed distance |
| **morphological closing** | buffer out then in by the same amount, to seal narrow gaps |
| **union** | merging shapes into one |
| **intersection** | the overlap between shapes |
| **clip** | cutting geometry down to the part inside another shape |
| **simplify** | removing vertices that barely change the outline |
| **topology** | how parts of a shape connect; `preserve_topology=True` stops simplification creating invalid output |
| **centroid** | centre of mass — can fall *outside* a concave shape |
| **representative point** | a point guaranteed to lie *inside* a shape |

### Coordinate systems

| term | meaning |
|---|---|
| **CRS** | Coordinate Reference System — the rulebook mapping numbers to places |
| **EPSG** | European Petroleum Survey Group — the registry numbering every CRS |
| **WGS84 / EPSG:4326** | World Geodetic System 1984 — global latitude/longitude in degrees, used by GPS |
| **UTM** | Universal Transverse Mercator — the globe cut into 60 zones, each projected onto a flat metre grid |
| **EPSG:32643** | UTM zone 43N — the metre-based CRS covering the Nilgiris |
| **projection** | flattening the curved Earth onto a plane; always distorts something |
| **reprojection** | converting coordinates between CRSs |
| **great-circle distance** | the shortest distance across a sphere's surface |
| **radian** | an angle unit; `$centerSphere` wants a radius in radians = km / 6378.1 |
| **always_xy** | the pyproj flag forcing (longitude, latitude) order instead of each CRS's declared order |

### MongoDB

| term | meaning |
|---|---|
| **document** | one record, a JSON-like object. The equivalent of a row |
| **collection** | a group of documents. The equivalent of a table |
| **BSON** | Binary JSON — MongoDB's storage format, adding `Date`, `ObjectId` and integer types |
| **`_id`** | the automatic primary key, always indexed |
| **index** | a structure letting the server find documents without reading them all |
| **2dsphere** | a geospatial index treating coordinates as points on a sphere |
| **`$nearSphere`** | nearest-first, sorted. Requires an index; Point reference only; not countable |
| **`$geoNear`** | the aggregation form, which also returns the distance. Must be the first pipeline stage |
| **`$geoWithin`** | entirely inside a shape. No index required |
| **`$geoIntersects`** | touches, crosses or is inside. No index required |
| **`$centerSphere`** | a circle defined as `[[lon, lat], radius_in_radians]` |
| **`$maxDistance`** | distance limit in **metres** for GeoJSON references |
| **aggregation pipeline** | a list of stages, each transforming a stream of documents |
| **`$group`** | the pipeline stage that collapses documents by a key, like SQL `GROUP BY` |
| **`explain()`** | returns the query plan and execution statistics instead of results |
| **COLLSCAN** | collection scan — every document read |
| **IXSCAN** | index scan — only matching index entries read |
| **FETCH** | retrieving the full document behind an index entry |
| **`$natural`** | storage order; `.hint({"$natural": 1})` forces a COLLSCAN |
| **selectivity** | the fraction of a collection a query returns. Determines whether an index helps |
| **`ordered=False`** | bulk insert that continues past failures instead of stopping |
| **idempotent** | safe to run repeatedly with the same result |

### Data sources

| term | meaning |
|---|---|
| **OSM** | OpenStreetMap — a crowd-sourced world map, data licensed ODbL |
| **Overpass** | the read-only API for querying OSM data live |
| **tag** | OSM's free-form `key=value` attribute, e.g. `landuse=forest` |
| **node / way / relation** | OSM's three element types: a point, a line or area, a group |
| **osmnx** | the Python library that builds Overpass queries and returns GeoDataFrames |
| **FIRMS** | Fire Information for Resource Management System — NASA's fire detection service |
| **VIIRS** | Visible Infrared Imaging Radiometer Suite — the satellite sensor, 375 m pixels |
| **Suomi-NPP / NOAA-20** | the two satellites carrying VIIRS, passing at different times |
| **hotspot** | a thermal anomaly detection — *not* a confirmed fire |
| **FRP** | Fire Radiative Power, in megawatts — a proxy for fire intensity |
| **NRT vs SP** | Near Real-Time (last ~2 months) vs Standard Processing (science-quality archive) |
| **MAP_KEY** | the free FIRMS API key, obtained with an email address |
| **GBIF** | Global Biodiversity Information Facility — aggregates wildlife occurrence records |
| **occurrence** | one record of one organism at one place and time |
| **basisOfRecord** | how a record was made: human observation, preserved specimen, … |
| **coordinateUncertaintyInMeters** | the stated accuracy radius of a record's location |
| **obscured coordinates** | deliberately degraded locations (~31 km) protecting threatened species |
| **IUCN categories** | conservation status: LC least concern, NT near threatened, VU vulnerable, EN endangered, CR critically endangered |

### Python and tooling

| term | meaning |
|---|---|
| **Shapely** | the geometry library — shapes and operations, no CRS awareness |
| **pyproj** | the reprojection library, wrapping PROJ |
| **GeoPandas** | pandas with a geometry column and a CRS |
| **GeoDataFrame** | a pandas DataFrame whose `geometry` column holds Shapely objects |
| **PyMongo** | the official MongoDB driver for Python |
| **Folium** | Python bindings for Leaflet.js, producing standalone HTML maps |
| **venv** | an isolated Python environment holding this project's packages |
| **editable install** | `pip install -e .` — links the package instead of copying it, so edits take effect immediately |
| **JSONL** | JSON Lines — one JSON object per line, appendable |
| **ISO 8601** | the date standard: `2024-03-25T08:08:00+00:00`; durations like `P1D` mean one day |
| **log1p** | log(1 + x) — handles zero, used for skewed count data |
| **right-skewed** | a distribution with a long high tail, where the mean exceeds the median |

---

## In closing: what was built, and what it demonstrates

**ForestGeo Risk Analyser** takes four unrelated open datasets — satellite fire
detections, a crowd-sourced road and settlement map, protected-area boundaries, and
wildlife occurrence records — and turns them into a single spatial database that can
answer one question: *which villages sit where fire pressure and wildlife habitat
overlap?*

The answer is **79 of 421**, and every step from raw download to that number is
reproducible by re-running ten scripts.

What the project demonstrates technically:

1. **All three GeoJSON vector types**, stored and indexed — Points (villages, hotspots,
   sightings), LineStrings (roads, rivers), Polygons (forests, reserves, water).
2. **Validation before storage.** 46,779 raw features reduced to 46,208 valid ones, with
   every discard counted by reason, and **zero** rejected by MongoDB at insert.
3. **All four spatial operators**, each used where it is correct — `$geoIntersects` for
   lines crossing areas, `$geoWithin` + `$centerSphere` for counting in a radius,
   `$geoNear` where the distance itself is needed.
4. **The limits of the database, handled honestly.** MongoDB cannot build geometry, so
   the union and intersection happen in Shapely and are written back — and then
   validated against MongoDB's own reasoning, which agreed exactly (79 = 79).
5. **Measured, not asserted, index performance.** 180× on a selective query; 1.3× on a
   broad one. The second number matters as much as the first.

What it demonstrates about handling real data:

- Overpass returns features **unclipped**, so 42% of fetched forest area lay outside the
  study region. Clipping changed reported forest cover from 93% to 54%.
- A fixed simplification tolerance **destroyed 243 small water bodies** until it was made
  size-aware.
- The same OSM element arrived **twice** when a layer queried two tag keys, silently
  double-counting Bandipur's and Mudumalai's wildlife.
- **24.7% of wildlife records are deliberately obscured**, and they are exactly the
  flagship species. The obscuring is irreversible — 659 records, 659 distinct
  coordinates, no grid to invert — so the analysis was redesigned around it rather than
  filtering the species out.
- A **roadkill dataset** was 33% of precise records and would have made the
  road-proximity statistic circular.
- The first risk score **saturated**, scoring 68 villages identically, until the skewed
  count data was log-scaled.

None of those were visible in the plan. All of them were found by measuring the output
and checking whether the numbers made sense — which is the actual skill the project
teaches.

