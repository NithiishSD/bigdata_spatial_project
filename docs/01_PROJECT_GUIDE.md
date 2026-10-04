# 01 — Project Guide: Concepts, Architecture & FAQ

Read this first. It explains **what** you are building, **why** each piece exists, and answers the
questions you will likely have halfway through.

---

## 1. The problem, in plain words

In a forested hill district, four things compete for the same land:

| Pressure | What it looks like in data |
|---|---|
| Wildfires | Satellite fire detections (points with a date/time) |
| Roads, railways, forest tracks | Lines cutting through forest and reserves |
| Settlements | Village points at the forest edge |
| Wildlife | Species sightings (points) inside and outside reserves |

Each comes from a different source in a different format. The project's claim is:
**put them in one spatial database, and spatial queries reveal where pressures coincide** — e.g.
"which villages are within 5 km of repeated fire detections *and* sit next to continuous habitat?"

## 2. What "done" looks like (deliverables)

1. A MongoDB Atlas database `forestgeo` with ~10 collections, all geometries valid and 2dsphere-indexed.
2. Python pipeline scripts (`scripts/00…09`) that rebuild everything from scratch.
3. Results for the four operations + one cross-theme query, saved as CSV/GeoJSON in `outputs/`.
4. An index performance comparison (table + chart + explain plans).
5. An interactive Folium map (`outputs/forestgeo_map.html`) with toggleable layers and a fire timeline.
6. A report and a 5-minute demo (see `06_REPORT_AND_DEMO.md`).

## 3. Architecture

```
            ┌──────────────── FETCH ────────────────┐
 OSM (Overpass/osmnx) ─┐                            │
 NASA FIRMS API ───────┼──► data/raw/*.geojson/.csv │
 GBIF API ─────────────┘                            │
            └───────────────────────────────────────┘
                              │
                              ▼
            ┌──────────── CLEAN & VALIDATE (Shapely) ─────────────┐
            │ clip to bbox · make_valid · fix geometry types ·     │
            │ drop duplicates · round coords · simplify big polys │
            └─────────────────────────────────────────────────────┘
                              │ data/processed/*.geojson
                              ▼
            ┌──────────── LOAD (PyMongo) ───────────┐
            │ GeoJSON docs → insert_many(ordered=False)
            │ create 2dsphere indexes                │
            └────────────────────────────────────────┘
                              │ MongoDB Atlas: db "forestgeo"
          ┌───────────────────┼─────────────────────────────┐
          ▼                   ▼                             ▼
  CORE QUERIES          UNION (Shapely)               BENCHMARK
  $nearSphere           forests → habitat_block       explain("executionStats")
  $geoWithin            hotspot buffers → burn_risk   indexed vs $natural scan
  $geoIntersects        store in derived_zones        synthetic scale test
          │                   │                             │
          └───────► CROSS-THEME QUERY ◄─┘                   │
                          │                                 │
                          ▼                                 ▼
                 outputs/*.csv, *.geojson       outputs/benchmark.csv, .png
                          │
                          ▼
                 FOLIUM MAP (layers + fire timeline) → outputs/forestgeo_map.html
```

**Why this shape?** Each stage writes files you can inspect. When something breaks you can tell
whether it's the data (open the GeoJSON in https://geojson.io or QGIS), the load, or the query.

## 4. Key concepts you need (short and practical)

### 4.1 GeoJSON
The JSON format MongoDB understands for geometry:
```json
{"type": "Point", "coordinates": [76.70, 11.41]}
{"type": "LineString", "coordinates": [[76.70, 11.41], [76.71, 11.42]]}
{"type": "Polygon", "coordinates": [[[76.7,11.4],[76.8,11.4],[76.8,11.5],[76.7,11.4]]]}
```
- **Order is `[lon, lat]`** (x, y). Swapping them is the #1 bug — your points end up in the ocean off Somalia.
- Polygon = list of rings; first ring is the outer boundary, others are holes; each ring is **closed**
  (first point == last point) and has ≥ 4 positions.
- `Multi*` variants hold several parts (a road split in two, a reserve with islands).

### 4.2 Coordinate reference systems (CRS)
- **EPSG:4326 (WGS84 lat/lon, degrees)** — what GeoJSON and MongoDB use. Good for *storage and queries*.
- **EPSG:32643 (UTM zone 43N, metres)** — flat projection for this region. Good for *buffers, areas,
  union, simplification*.
- A degree is not a fixed distance (1° longitude ≈ 109 km at 11°N). `buffer(0.01)` in degrees gives
  distorted, wrong-sized shapes. **Always project to UTM → do geometry math → project back.**

### 4.3 2dsphere index
A MongoDB index that treats the Earth as a sphere (uses Google's S2 cell system internally).
It covers every point of a geometry with cells, so a query only examines documents whose cells
overlap the query area instead of every document.
- Required for `$near`/`$nearSphere`/`$geoNear`.
- Optional (but much faster) for `$geoWithin` and `$geoIntersects`.
- The legacy `2d` index is for flat x/y pairs — **not** what you want.
- Edges between vertices are **geodesics** (great-circle arcs), not straight lines on a map. For small
  features this doesn't matter.

### 4.4 The four operations

| Operation | Question it answers | Needs index? | Reference geometry |
|---|---|---|---|
| `$nearSphere` | "What's closest to this point, in order?" | **Yes** (errors without) | Point only |
| `$geoWithin` | "What is *completely inside* this area?" | No (faster with) | Polygon/MultiPolygon, or `$centerSphere` circle |
| `$geoIntersects` | "What *touches or crosses* this shape?" | No (faster with) | Any GeoJSON type |
| Union (Shapely) | "Merge these shapes into one" | n/a — done in Python | — |

`$geoWithin` vs `$geoIntersects`: a road that starts outside a reserve and enters it is **not** within
the reserve, but it **does** intersect it. For "roads crossing reserves" you want `$geoIntersects`.

### 4.5 Why union happens outside MongoDB
MongoDB can *test* spatial relationships but cannot *construct* new geometries (no union, buffer,
intersection). So: read polygons out → merge in Shapely → write the result into `derived_zones` →
query it like any other polygon. This "compute outside, query inside" pattern is a legitimate design
point to discuss in your report.

### 4.6 explain("executionStats")
Asks MongoDB *how* it ran a query. The fields you care about:

| Field | Meaning |
|---|---|
| `winningPlan.stage` (nested) | `COLLSCAN` = read every doc; `IXSCAN`/`FETCH` = used index; `GEO_NEAR_2DSPHERE` = near query |
| `executionStats.nReturned` | results returned |
| `executionStats.totalKeysExamined` | index entries scanned |
| `executionStats.totalDocsExamined` | documents read |
| `executionStats.executionTimeMillis` | server-side time |

A good index gives `totalDocsExamined` close to `nReturned`. A collection scan gives
`totalDocsExamined` = collection size.

## 5. Data sources summary (details in `03_DATA_ACQUISITION.md`)

| Data | Source | Geometry | Licence | Access |
|---|---|---|---|---|
| Villages | OpenStreetMap | Point | ODbL | osmnx (no key) |
| Roads, tracks, railways, rivers | OpenStreetMap | LineString | ODbL | osmnx |
| Protected areas, forests, water, farmland | OpenStreetMap | Polygon | ODbL | osmnx |
| Fire hotspots | NASA FIRMS (VIIRS 375 m) | Point | Open (NASA) | free MAP_KEY |
| Wildlife sightings | GBIF (includes iNaturalist research-grade) | Point | CC0/CC-BY per dataset | REST API, no key |

## 6. Design decisions (and how to defend them)

| Decision | Alternative | Why we chose this |
|---|---|---|
| MongoDB Atlas | PostGIS | Project brief is about document-store spatial capabilities; Atlas free tier = zero install; shows NoSQL geo features *and* their limits (no union). |
| One collection per theme | Single `features` collection with `type` field | Cleaner queries, one index per theme, benchmark per collection. |
| Shapely for validation | Trust source data | OSM polygons are frequently invalid (self-intersections, unclosed rings); MongoDB rejects them at insert/index time. |
| UTM 43N for metric ops | Degrees | Buffers and areas in metres must be accurate. |
| VIIRS over MODIS | MODIS 1 km | VIIRS 375 m pixels → finer hotspot locations. |
| Store derived zones in Mongo | Keep in Python only | Lets MongoDB query the union results — required by the brief. |
| Develop on local `mongod`, re-run on Atlas for final results | Atlas from day one | Identical behaviour for `2dsphere`, `$nearSphere`, `$geoWithin` and `explain()`, but no network latency per query while iterating; the final numbers and screenshots still come from Atlas. |
| Python 3.14 | 3.12 (as originally planned) | Only 3.10 and 3.14 available on the dev machine; every dependency ships a cp314 wheel. |
| Keep farmland as a tenth collection | Cut it (it is on the time-saving list) | A polygon layer costs no new code — it reuses the forests/water path — and farmland against forest edge is where human–wildlife conflict shows up. |
| Numbered scripts `00`–`09`, one per phase | Fewer, combined scripts | Each phase is separately re-runnable, which makes the demo and the debugging story much easier; a standalone index step also gives a clean place to show that `$nearSphere` fails without a `2dsphere` index. |

## 7. Limitations to acknowledge (examiners like honesty)

- **Sampling bias**: sightings cluster near roads and tourist spots because that's where people observe.
  "More sightings near roads" may reflect observer access, not animal behaviour.
- **Obscured coordinates**: iNaturalist/GBIF blur locations of threatened species (up to ~0.2°).
  Filter by `coordinateUncertaintyInMeters` and mention it.
- **FIRMS ≠ confirmed fire**: hotspots are thermal anomalies; some are agricultural burning or false
  positives. Pixel size ~375 m means location uncertainty.
- **OSM completeness varies**: rural tracks and small villages may be missing.
- **Small data + Atlas M0**: timings are noisy and network-bound; hence the synthetic scale test.

## 8. FAQ — doubts you'll probably have

**Q: Do I need QGIS?** Not required, but installing it (free) to eyeball a GeoJSON takes 2 minutes
and saves hours. https://geojson.io also works for small files.

**Q: `$near` vs `$nearSphere`?** With GeoJSON geometry and a 2dsphere index they behave the same
(spherical distance in metres). The brief says `$nearSphere`, so use that.

**Q: How do I get the *distance* value back?** `$nearSphere` only sorts. Use the aggregation stage
`$geoNear` with `distanceField` when you need numbers (e.g. for a CSV). Show both in the report.

**Q: Can I use `$nearSphere` from a road (LineString) to find sightings?** No — the reference must be a
Point. Flip it: for each *sighting* point, `$nearSphere` on the `transport` collection (2dsphere indexes
lines too, so it finds the nearest road).

**Q: Why does `count_documents` fail with `$nearSphere`?** `count_documents` runs an aggregation
`$match`, where `$near` isn't allowed. Use `$geoWithin: {$centerSphere: [[lon,lat], km/6378.1]}` for counts.

**Q: My forest polygons are huge / the insert says document too large.** MongoDB docs max 16 MB. Simplify
in UTM (`geom.simplify(10)` = 10 m tolerance) before inserting; forests don't need centimetre precision.

**Q: How big a hotspot buffer?** VIIRS pixel ≈ 375 m; a 1 km buffer is a defensible "burn-risk"
radius. State it as a parameter and optionally show 500 m / 2 km sensitivity.

**Q: What counts as "adjacent" forests?** Polygons that touch or are within a small gap (e.g. 50 m, a
road width). Use buffer(+50).buffer(−50) (morphological closing) before/after union.

**Q: How many records should I have?** Rough expectation for the Nilgiris bbox: villages hundreds,
transport tens of thousands of segments, forests thousands of polygons, hotspots hundreds–few thousand
per fire season, sightings several thousand. Anything in that range is fine.

**Q: The unindexed benchmark isn't slower!** With a few thousand docs everything is fast. That's why
the roadmap includes the synthetic 10k → 500k scale test — the index's advantage grows with size.

**Q: Should I use notebooks?** Use a notebook to explore; move working code into `forestgeo/` and
scripts so the pipeline is reproducible.

**Q: Can I change region?** Yes: edit `BBOX` and `CRS_METRIC` in `config.py` and the fire season
dates. Everything else follows. Log the decision in §6 below.
