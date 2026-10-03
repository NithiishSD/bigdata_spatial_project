# 05 — Troubleshooting: "I'm stuck" Guide

**First, the 5-step unstick routine**
1. Read the **last line** of the traceback — it's usually the real error.
2. Search this file for a keyword from it (Ctrl+F).
3. Shrink the problem: one document, one query, tiny bbox.
4. Look at the data: print one document, or open the GeoJSON in geojson.io / QGIS.
5. Ask for help with: *what you ran*, *the full error*, *what you expected*, and *one sample document*.

---

## A. Connection & setup

| Symptom | Cause | Fix |
|---|---|---|
| `ServerSelectionTimeoutError` | IP not allow-listed in Atlas | Atlas → Network Access → Add current IP. Mobile hotspots / college Wi-Fi change IPs. |
| `bad auth : authentication failed` | Wrong user/password, or special chars in password | Reset password (letters+digits only) or `urllib.parse.quote_plus(password)`. |
| `ConfigurationError: ... dnspython` / SRV errors | DNS can't resolve `mongodb+srv` | `pip install -U pymongo` (includes dnspython); try another network/DNS (8.8.8.8); or use the non-SRV "standard" connection string from Atlas. |
| `KeyError: 'MONGODB_URI'` | `.env` not loaded | `.env` must be in the project root; call `load_dotenv()` before `os.environ[...]`; run scripts from the project root. |
| `ModuleNotFoundError: forestgeo` | Package not installed in the venv | From the project root: `pip install -e .` (uses the provided `pyproject.toml`). Check the venv is active (`which python` → `.venv/bin/python`). |
| SSL: `CERTIFICATE_VERIFY_FAILED` | Old CA bundle | `pip install -U certifi` and `MongoClient(uri, tlsCAFile=certifi.where())`. |

## B. Data fetching

| Symptom | Cause | Fix |
|---|---|---|
| osmnx `InsufficientResponseError` / empty result | No features for those tags in bbox | Check tag spelling; test on a known feature; widen tags. |
| Overpass 429 / 504 timeout | Server busy or query too big | Wait 1–2 min; `ox.settings.requests_timeout=300`; fetch one layer at a time; tile the bbox. |
| `features_from_bbox() got an unexpected keyword` | osmnx 1.x vs 2.x signature | `print(ox.__version__)`; 2.x uses `bbox=(left, bottom, right, top)`. |
| FIRMS returns text like `Invalid MAP_KEY` / `Invalid area coordinate` | Wrong key or bbox format | Key status URL in `03_DATA_ACQUISITION.md`; area must be `west,south,east,north` with no spaces. |
| FIRMS returns only headers | No fires those days / wrong source for that date | SP sources lag a few months; NRT covers only recent ~2 months. Check the data-availability URL. Try `VIIRS_NOAA20_SP`. |
| GBIF returns 0 results | WKT ring clockwise or lat/lon swapped | Ring must be counter-clockwise: `W S, E S, E N, W N, W S`. |
| GBIF stops at 100k | Search API hard limit | Cap per class or use the download API. |

## C. Geometry & validation

| Symptom | Cause | Fix |
|---|---|---|
| Points plot in the ocean / Africa | `[lat, lon]` instead of `[lon, lat]` | GeoJSON/Mongo = `[lon, lat]`. Folium `location=` = `[lat, lon]`. |
| Buffers are enormous or egg-shaped | Buffering in degrees | Project to EPSG:32643 first (`to_metric`), buffer in metres, project back. |
| pyproj output has lat/lon swapped | Missing `always_xy=True` | Always create Transformers with `always_xy=True`. |
| `make_valid` returned `GeometryCollection` | Invalid polygon fixed into mixed parts | `_keep_family(..., "polygon")` from cookbook §1. |
| `TopologyException` during union | Invalid inputs | Clean every input with `clean_geometry` (or `buffer(0)`) before `union_all`. |
| Union is very slow | Thousands of complex polygons | Use vectorised `shapely.union_all(array)`; simplify inputs (5 m) first; it's a one-off step, cache the result. |

## D. MongoDB inserts & indexes

| Error text (partial) | Meaning | Fix |
|---|---|---|
| `Can't extract geo keys ... Loop is not valid` / `Edges N and M cross` | Self-intersecting polygon | `clean_geometry` (make_valid). |
| `Can't extract geo keys ... Duplicate vertices` | Ring touches itself / repeated vertex | `set_precision` + `remove_repeated_points`; make_valid. |
| `Can't extract geo keys ... longitude/latitude is out of bounds` | lat/lon swapped or projected coords (metres!) stored | You stored UTM coordinates — reproject to 4326 before `mapping()`. |
| `Loop must have at least 3 different vertices` | Degenerate sliver polygon | Drop geometries with `area_km2 < 1e-6` after cleaning. |
| `Index build failed ... Can't extract geo keys` | Creating index on a collection that already has bad docs | Create index **before** inserting; bad docs will be rejected individually and logged. |
| `cannot encode object: numpy.int64` / `Timestamp` | numpy/pandas types | `_py()` converter from cookbook §2. |
| `BSONObj size ... is invalid` / document too large (16 MB) | Giant polygon (e.g. habitat union) | Simplify in metres (20–50 m) and/or keep only parts ≥ 1 km². |
| `E11000 duplicate key` | Re-running without drop, unique index | Scripts should `drop()` or `delete_many({})` first. |

## E. Queries

| Symptom | Cause | Fix |
|---|---|---|
| `unable to find index for $geoNear query` | `$nearSphere`/`$geoNear` without a 2dsphere index | Create the index. (In the benchmark this error is the *expected* result.) |
| `$geoNear, $near, and $nearSphere are not allowed in this context` | Used `$nearSphere` in `count_documents` or `$match` | Use `$geoWithin: {$centerSphere: [[lon,lat], km/6378.1]}` for counts, or `$geoNear` as first pipeline stage. |
| `$geoNear is only valid as the first stage` | Stage order | Put `$geoNear` first. |
| `There is more than one 2dsphere index ... ambiguous` | Multiple geo indexes | Pass `"key": "geometry"` in `$geoNear`. |
| `$nearSphere` expects Point | Passed a LineString/Polygon | Reference must be a Point; iterate over points instead (cookbook Q2). |
| `$geoWithin` returns 0 for roads in a PA | Roads only partly inside | Use `$geoIntersects`. |
| `$maxDistance` seems ignored/huge | Legacy coordinate pairs use radians | Use GeoJSON `{"$geometry": {...}}` form → metres. |
| Results look shifted | Polygon edge is a geodesic, not a straight map line | Only matters for very long edges; `shapely.segmentize(g, 0.01)` densifies. |
| `Big polygon` / query covers the whole world | Polygon larger than a hemisphere or ring orientation issue | Won't happen with local data; check for a bogus polygon spanning 0,0. |
| Query with derived zone is slow | Query geometry has 100k+ vertices | Simplify the derived zone more; store `n_vertices` to monitor. |

## F. Benchmark

| Symptom | Cause | Fix |
|---|---|---|
| Indexed and unindexed both ~0–2 ms | Collection too small | That's a valid finding for small data; run the synthetic scale test. |
| Wall-clock times vary wildly | Network latency to Atlas | Report server-side `executionTimeMillis` median of 5 runs; compare `docsExamined`. |
| `hint` error: bad hint | Wrong index name/spec | `[("$natural", 1)]` in `cursor.hint`, `{"$natural": 1}` in raw `explain` command. |
| `KeyError: 'inputStage'` while parsing plan | Plan shape differs by server version | Use the recursive `_stages()` helper and `winningPlan.get("queryPlan", winningPlan)`. |
| Atlas "quota exceeded" / slow bulk insert | M0 storage (512 MB) / ops limits | Stay ≤ 250k–500k tiny points; drop `bench_points` after. |

## G. Folium map

| Symptom | Cause | Fix |
|---|---|---|
| `TypeError: Object of type datetime/ObjectId is not JSON serializable` | Raw Mongo values in properties | Convert to `str` (see `to_fc` in cookbook §8); don't pass `_id`. |
| Markers in wrong place | Folium uses `[lat, lon]` | `folium.CircleMarker([lat, lon])`. |
| HTML is 100 MB / browser freezes | Too many vertices/features | Simplify for display, fewer road classes, `MarkerCluster` for points. |
| Timeline shows nothing | `time` property format | ISO string `YYYY-MM-DDTHH:MM:SS`; features sorted; `period="P1D"`. |
| Layer toggles missing | FeatureGroup not added or LayerControl added before layers | Add `LayerControl` **last**. |

---

## Still stuck? Template for a help request

```
Step/script: scripts/0X_....py (Phase N in ROADMAP)
What I ran:   <command>
Expected:     <what should happen>
Got:          <full traceback / wrong output>
Sample doc:   <db.coll.find_one() output, geometry trimmed>
Already tried: <what you tried>
```
