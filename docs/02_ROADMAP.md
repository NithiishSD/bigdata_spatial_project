# 02 — Roadmap (Hackathon Style)

**How to use this file:** work top to bottom. Tick `[x]` as you finish. Each phase has a
**Definition of Done (DoD)** — don't move on until it's true. Time estimates assume focused work;
the whole MVP is roughly **30–40 hours** (≈ one intense week, or 2–3 relaxed weeks).

**Hackathon rules for yourself**
1. **MVP first, polish later.** Get one row per operation working end-to-end before perfecting any.
2. **Commit after every green step** (`git commit -m "phase 3: villages loaded"`).
3. **Timebox**: if stuck > 45 min on one issue → check `05_TROUBLESHOOTING.md` → search the exact
   error text → if still stuck, take the simpler path and note it as a limitation.
4. **Save outputs to files** as you go — your report writes itself from `outputs/`.

```
Phase 0  Setup ............................ 2 h   ██
Phase 1  Data acquisition ................. 5 h   █████
Phase 2  Clean & validate ................. 4 h   ████
Phase 3  Load + 2dsphere indexes .......... 3 h   ███
Phase 4  Core queries (near/within/inter.). 5 h   █████      ← MVP checkpoint A
Phase 5  Union + derived zones ............ 4 h   ████
Phase 6  Cross-theme query ................ 3 h   ███        ← MVP checkpoint B
Phase 7  Index benchmark .................. 4 h   ████
Phase 8  Folium map + timeline ............ 5 h   █████      ← MVP complete
Phase 9  Report, demo, cleanup ............ 5 h   █████
Stretch  (optional extras) ................ ∞
```

---

## Phase 0 — Setup (≈ 2 h)

- [ ] `git init`, add `.gitignore` (already provided), first commit
- [x] `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
- [ ] Create **MongoDB Atlas** account → free **M0** cluster (pick a region near you, e.g. Mumbai `ap-south-1`)
- [ ] Atlas → *Database Access*: create a DB user (password without `@ : / ?` or URL-encode it)
- [ ] Atlas → *Network Access*: add your current IP (or `0.0.0.0/0` for dev only — mention in report)
- [ ] Atlas → *Connect → Drivers → Python*: copy the `mongodb+srv://...` URI
- [ ] Request **NASA FIRMS MAP_KEY**: https://firms.modaps.eosdis.nasa.gov/api/map_key/ (arrives by email instantly)
- [x] `cp .env.example .env` and fill `MONGODB_URI`, `FIRMS_MAP_KEY`
- [x] Create folders: `forestgeo/ scripts/ data/raw data/processed outputs tests`
- [x] Write `forestgeo/config.py` (region bbox, CRS codes, collection names) and `forestgeo/db.py`
- [x] Write & run `scripts/00_check_connection.py` → prints server version and `ping: ok`

**DoD:** `python scripts/00_check_connection.py` prints `{'ok': 1.0}`; `.env` is git-ignored.

Starter `forestgeo/db.py`:
```python
import os
from functools import lru_cache
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

@lru_cache
def get_client() -> MongoClient:
    return MongoClient(os.environ["MONGODB_URI"], serverSelectionTimeoutMS=10_000)

def get_db():
    return get_client()[os.getenv("MONGODB_DB", "forestgeo")]
```

---

## Phase 1 — Data acquisition (≈ 5 h)

Follow `03_DATA_ACQUISITION.md`. Save raw files to `data/raw/`.

- [ ] OSM points: villages → `data/raw/osm_villages.geojson`
- [ ] OSM lines: roads, tracks, railways → `osm_transport.geojson`; rivers → `osm_rivers.geojson`
- [ ] OSM polygons: protected areas, forests, water bodies, farmland (one file each)
- [ ] FIRMS VIIRS hotspots for the fire season (5-day chunks) → `firms_viirs.csv`
- [ ] GBIF sightings (mammals + birds, or all animals) → `gbif_sightings.csv`
- [ ] Quick sanity plot: `gdf.plot()` for each file, or open in geojson.io/QGIS
- [ ] Record row counts + download date in `outputs/data_inventory.csv`

**DoD:** every dataset exists on disk, row counts > 0, a quick plot shows them inside the Nilgiris.

> 🚩 If Overpass times out: fetch one tag group at a time, or split the bbox into 4 tiles.

---

## Phase 2 — Clean & validate (≈ 4 h)

Implement `forestgeo/geo.py` (reference code in `04_QUERY_COOKBOOK.md §1`).

- [x] `clean_geometry(geom, family)` — make_valid → keep Point/Line/Polygon family → remove repeated
      points → drop empty → round to 6 decimals
- [x] `to_metric(geom)` / `to_wgs84(geom)` helpers with `always_xy=True`
- [ ] Villages: OSM place polygons → use centroid (representative_point) so all villages are Points
- [ ] Transport: add `kind` field (`road` / `track` / `railway`); explode nothing, keep MultiLineStrings
- [ ] Polygons: simplify in UTM (5–10 m tolerance), compute `area_km2`
- [ ] FIRMS: build `acq_datetime` (UTC) from `acq_date` + `acq_time`; drop `confidence == "l"`
- [ ] GBIF: drop rows with `coordinateUncertaintyInMeters > 1000`; deduplicate on `gbifID`
- [ ] Clip everything to BBOX
- [ ] Write `data/processed/<collection>.geojson` + a validation report
      (`outputs/validation_report.csv`: collection, input rows, fixed, dropped, output rows)

**DoD:** `shapely.is_valid` is True for 100 % of processed geometries; validation report exists.
Keep the "fixed/dropped" numbers — they go straight into your report.

---

## Phase 3 — Load into MongoDB + indexes (≈ 3 h)

- [x] `forestgeo/load.py`: GeoDataFrame → list of dicts `{..., "geometry": mapping(geom)}`
- [x] Datetimes as Python `datetime` (become BSON Dates), NaN → `None`
- [ ] Create **2dsphere index first**, then `insert_many(docs, ordered=False)` — bad docs are
      rejected individually; log them to `outputs/rejected_<coll>.jsonl`
- [x] Extra indexes: `fire_hotspots.acq_datetime`, `transport.kind`, `derived_zones.zone_type`
- [x] Script is idempotent: `coll.drop()` (or `delete_many({})`) before reload
- [ ] Print summary: collection → count, geometry types (`$group` on `geometry.type`), indexes

**DoD:** all 9 source collections loaded; `list_indexes()` shows `geometry_2dsphere` on each;
rejected count is 0 or explained.

---

## Phase 4 — Core spatial queries (≈ 5 h) 🎯 MVP checkpoint A

Reference code: `04_QUERY_COOKBOOK.md §2–4`. Save each result to `outputs/`.

- [ ] **Q1 `$nearSphere` — villages near fire hotspots**: for top-20 hotspots by FRP, villages within
      5 km ordered by distance. Plus `$geoNear` version with `distanceField` → `q1_villages_near_fire.csv`
- [ ] **Q2 `$nearSphere` — sightings near roads**: for each sighting, nearest road within 500 m;
      summarise % of sightings within 500 m of a road, by species class → `q2_sightings_near_roads.csv`
- [ ] **Q3 `$geoWithin` — counts per protected area**: sightings & hotspots inside each PA
      → `q3_pa_counts.csv` (name, area_km2, n_sightings, n_hotspots, per-km² densities)
- [ ] **Q4 `$geoIntersects` — linear features crossing protected areas** (by `kind`) and **crossing
      water bodies** → `q4_crossings.csv`
- [ ] Sanity-check one result per query visually (quick Folium map or QGIS)

**DoD:** four CSVs in `outputs/`, each with a 1–2 sentence interpretation written in `outputs/notes.md`.

---

## Phase 5 — Union + derived zones (≈ 4 h)

Reference code: `04_QUERY_COOKBOOK.md §5`.

- [ ] **Habitat block**: all forests → UTM → buffer(+50) → `union_all` → buffer(−50) → keep polygons
      ≥ 1 km² (optional) → simplify(20) → WGS84 → clean → store `zone_type="habitat_block"`
- [ ] **Burn-risk footprint**: hotspots → UTM → buffer(1000) → `union_all` → simplify → store
      `zone_type="burn_risk_footprint"`
- [ ] Store `params`, `input_count`, `area_km2`, `created_at` with each derived doc
- [ ] Query derived zones with MongoDB: e.g. `$geoWithin` villages in burn footprint;
      `$geoIntersects` PAs touching habitat block
- [ ] Record before/after numbers: input polygons → output parts, total area

**DoD:** `derived_zones` has both zones, both valid and indexed, and at least one MongoDB query runs
against each.

---

## Phase 6 — Cross-theme query (≈ 3 h) 🎯 MVP checkpoint B

Reference code: `04_QUERY_COOKBOOK.md §6`.

- [ ] Build `habitat_buffer` (habitat block + 2 km) and `critical_zone` = burn footprint ∩ habitat
      buffer (Shapely), store both in `derived_zones`
- [ ] Query: **villages** `$geoWithin` critical zone; **tracks** (`kind="track"`) `$geoIntersects` it
- [ ] Alternative form: combine two geo predicates with `$and` (burn footprint AND habitat buffer)
      and show the results match
- [ ] Village risk table: for each village → hotspots within 5 km (`$centerSphere` count), distance
      to nearest hotspot (`$geoNear`), inside burn footprint (bool), inside habitat buffer (bool) →
      simple risk score → `q6_village_risk.csv`

**DoD:** a ranked list of at-risk villages and tracks with an explanation of the logic.

---

## Phase 7 — Index performance benchmark (≈ 4 h)

Reference code: `04_QUERY_COOKBOOK.md §7`.

- [ ] `explain` helper returning stage, nReturned, keysExamined, docsExamined, executionTimeMillis
- [ ] Real data: run Q3 & Q4 with index vs `.hint({"$natural": 1})` (5 runs each, median)
- [ ] Show that `$nearSphere` **fails** without an index (capture the error text — it's a finding)
- [ ] Synthetic scale test: `bench_points` with 10k, 50k, 100k, 250k(, 500k) random points in bbox;
      `$geoWithin` a fixed polygon; indexed vs COLLSCAN
- [ ] Save `outputs/benchmark.csv`, `outputs/benchmark.png` (log-scale line chart), and a couple of raw
      explain JSONs to `outputs/explain/`

**DoD:** chart shows COLLSCAN time/docsExamined growing linearly while indexed stays low.

---

## Phase 8 — Folium map + timeline (≈ 5 h) — MVP complete ✅

Reference code: `04_QUERY_COOKBOOK.md §8`.

- [ ] Base map centred on Nilgiris, 2–3 tile options (OpenStreetMap, Esri World Imagery, CartoDB)
- [ ] `FeatureGroup` layers: protected areas, forests, water, farmland, transport (colour by kind),
      rivers, villages (colour by risk), sightings (`MarkerCluster`), habitat block, burn footprint,
      critical zone
- [ ] Popups/tooltips with names and key numbers
- [ ] `TimestampedGeoJson` animated fire hotspots (daily step)
- [ ] `LayerControl`, legend, title
- [ ] Keep HTML < ~30 MB (simplify polygons for display, limit roads to main classes if needed)

**DoD:** `outputs/forestgeo_map.html` opens in a browser, every layer toggles, the timeline plays.

---

## Phase 9 — Report, demo, cleanup (≈ 5 h)

See `06_REPORT_AND_DEMO.md`.

- [ ] README "how to run" works on a fresh clone (test it!)
- [ ] Screenshots of map & benchmark chart into `docs/img/`
- [ ] Report written from `outputs/` numbers
- [ ] Demo script rehearsed (5 minutes)
- [ ] Remove secrets from history; `.env` never committed

**DoD:** someone else could clone, fill `.env`, run scripts 00→09, and get the same map.

---

## Stretch goals (only after MVP)

| Idea | Value | Effort |
|---|---|---|
| Multi-year fire comparison (2022 vs 2023 vs 2024) | Trend story | Low |
| Hotspot density grid (H3 hex or 1 km grid) with `$geoWithin` per cell | Nice heat layer | Medium |
| Buffer sensitivity (500 m / 1 km / 2 km footprints) | Robustness | Low |
| Streamlit dashboard with filters (species, date) | Wow factor | Medium |
| Aggregation pipeline with `$geoNear` + `$lookup` to enrich villages | Shows Mongo depth | Medium |
| Compound index `{geometry: "2dsphere", acq_datetime: 1}` benchmark for time+space | Good benchmark insight | Low |
| Unit tests in `tests/` for geo helpers | Engineering quality | Low |
| Docker / Makefile `make all` | Reproducibility | Low |

---

## If you're running out of time — cut in this order

1. Stretch goals
2. Synthetic benchmark sizes beyond 100k
3. Farmland layer
4. Q2 per-species breakdown (keep overall %)
5. Map polish (legend, multiple tiles)

**Never cut:** valid geometries, 2dsphere indexes, the four operations, the union stored in Mongo,
one cross-theme query, one indexed-vs-unindexed comparison, the map.
