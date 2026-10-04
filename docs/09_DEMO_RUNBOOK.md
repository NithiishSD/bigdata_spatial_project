# 09 — Demo Runbook

Everything needed to present this project, with the real numbers from the
2026-10-04 run. Nothing here requires the internet except the map's basemap tiles.

---

## 1. What to do now, in order

| # | Task | Time | Status |
|---|---|---|---|
| 1 | Generate report figures — `python scripts/make_figures.py` | done | ✅ |
| 2 | Open `outputs/forestgeo_map.html` and screenshot 3–4 views | 20 min | |
| 3 | Write the report from `outputs/` using the §1 outline in `06_REPORT_AND_DEMO.md` | 4–6 h | |
| 4 | Rehearse the 5-minute demo below, out loud, twice | 30 min | |
| 5 | Record a screen capture of the demo as a fallback | 10 min | |
| 6 | *(optional)* re-run against Atlas for cloud numbers | 1 h | |

Figures already generated in `docs/img/`:

| file | shows |
|---|---|
| `fig1_study_area.png` | the region, forests, reserves, villages, bbox |
| `fig2_union_before_after.png` | 119 forest polygons → 23 habitat blocks |
| `fig3_burn_footprint.png` | 1,564 hotspots → 1,051 km² footprint |
| `fig4_critical_zone.png` | critical zone + villages coloured by risk |
| `outputs/benchmark.png` | indexed vs COLLSCAN at two selectivities |

Still to capture by hand from the map: layer control open, timeline at peak fire week,
a village popup showing its risk score.

---

## 2. Set up 15 minutes before

```bash
cd ~/Projects/bigdata_spatial_project
source .venv/bin/activate

systemctl is-active mongod            # must print: active
python scripts/check_connection.py    # must end: ALL CHECKS PASSED
```

Open these **before** you start, so nothing has to load live:

1. `outputs/forestgeo_map.html` in a browser tab
2. `outputs/benchmark.png` in another tab
3. `docs/img/fig2_union_before_after.png` in a third
4. A terminal with `mongosh forestgeo` already connected
5. A second terminal in the project folder

**Do not run the fetch scripts live.** They depend on three public APIs, and Overpass
failed three times during development. Everything else runs offline against the local
database in seconds.

---

## 3. The 5-minute demo

### 0:00 — the question (30 s)

*Show `fig1_study_area.png`.*

> "The Nilgiris: 6,519 km², 54% forest cover, nine protected areas including two tiger
> reserves. Four pressures act on it — wildfire, roads, settlements and wildlife — and
> they come from four unrelated open datasets that know nothing about each other.
> The question is where they overlap. That is a spatial question, so it needs a spatial
> database."

### 0:30 — what is in the database (45 s)

*Switch to the `mongosh` terminal and type:*

```javascript
show collections
db.villages.countDocuments()
db.transport.aggregate([{$group: {_id: "$geometry.type", n: {$sum: 1}}}])
db.villages.getIndexes()
```

> "Ten collections, 46,208 documents. All three GeoJSON types — Points for villages,
> hotspots and sightings; LineStrings for 37,665 roads and rivers; Polygons for forests
> and reserves. Every geometry validated in Shapely before insert, and every collection
> carries a 2dsphere index. 46,779 raw features went in, 46,208 came out valid, and
> MongoDB rejected zero."

### 1:15 — the four operations, live (1 min)

*Paste these one at a time:*

```javascript
// $geoWithin — what is inside Mudumalai National Park
pa = db.protected_areas.findOne({name: /Mudumalai/})
db.sightings.countDocuments({geometry: {$geoWithin: {$geometry: pa.geometry}}})

// $geoIntersects — roads crossing it (a road that exits is not "within")
db.transport.countDocuments({geometry: {$geoIntersects: {$geometry: pa.geometry}}, kind: "road"})

// $nearSphere — villages nearest the region centre, in distance order
db.villages.find({geometry: {$nearSphere: {$geometry: {type: "Point",
  coordinates: [76.65, 11.40]}, $maxDistance: 5000}}}, {name: 1, _id: 0}).limit(3)
```

> "533 sightings inside Mudumalai, 104 roads crossing it. Note I used `$geoIntersects`
> for the roads — a road that enters the reserve and leaves again is not *entirely
> inside* it, so `$geoWithin` would have returned zero. And `$nearSphere` returns
> results already sorted by distance."

**Headline from the CSVs** (`outputs/q3_protected_area_counts.csv`):

> "Sathyamangalam Tiger Reserve has the most fire detections, 52, and the fewest
> wildlife records, 14. Mudumalai has 533 sightings. Fire pressure and wildlife
> recording are almost inverse."

### 2:15 — the union, and MongoDB's limit (45 s)

*Show `fig2_union_before_after.png`.*

> "Here is the one thing MongoDB cannot do. It can test whether shapes relate to each
> other, but it cannot *build* geometry — there is no union operator. So I compute the
> union in Shapely, in a metre-based projection, and write the result back into a
> `derived_zones` collection. 119 separate forest polygons become 23 continuous habitat
> blocks. The 50-metre grow-then-shrink seals gaps like tracks that split a forest on
> paper but not ecologically."

*Then in `mongosh`:*

```javascript
db.derived_zones.find({}, {zone_type: 1, n_parts: 1, area_km2: 1, _id: 0})
```

> "And now it is just another collection — fully queryable."

### 3:00 — the cross-theme answer (45 s)

*Show `fig4_critical_zone.png`, then the map with the critical zone layer on.*

```javascript
crit = db.derived_zones.findOne({zone_type: "critical_zone"})
db.villages.countDocuments({geometry: {$geoWithin: {$geometry: crit.geometry}}})
```

> "The critical zone is the burn-risk footprint intersected with the habitat buffer —
> 862 km² where fire pressure meets continuous forest. **79 of 421 villages sit inside
> it.** Thoraihatty is the most exposed: 239 hotspots within 5 km, the nearest 372 metres
> away.
>
> And I validated that intersection against MongoDB itself — asking for villages inside
> *both* source zones with two `$geoWithin` predicates also returns 79. Two engines, two
> representations, same answer."

### 3:45 — performance (45 s)

*Show `outputs/benchmark.png`.*

> "250,000 synthetic points, same query, with and without the index. On a selective
> query returning 0.2% of the collection, the index is **180× faster** and examines
> **334× fewer documents** — and stays flat as the collection grows 25×, while the
> collection scan grows linearly.
>
> But on a broad query returning 25%, the same index gives only 1.3×. That is the more
> interesting result: an index accelerates *selective* queries. Past about a third
> selectivity, scanning wins — which is why query planners sometimes ignore an index on
> purpose.
>
> And `$nearSphere` doesn't just get slower without an index — it refuses to run:
> *unable to find index for `$geoNear` query*."

### 4:30 — the timeline (20 s)

*Switch to the map, press play on the time slider.*

> "1,564 hotspots animated daily across the Jan–May 2024 season. You can watch activity
> build through February and peak in March."

### 4:50 — limitations (10 s)

> "Two I'd flag. 88.7% of sightings are within 500 m of a road — that is observer bias,
> not animal behaviour; people record wildlife where people are. And a quarter of the
> wildlife records are deliberately obscured to 31 km because they are tiger and elephant
> locations, so the analysis tiers records by precision rather than filtering them out."

---

## 4. `mongosh` cheat sheet — paste-ready

```javascript
use forestgeo
show collections

// counts per collection
db.getCollectionNames().forEach(c => print(c, db[c].countDocuments()))

// geometry types — proves all three GeoJSON types
["villages","transport","forests"].forEach(c =>
  printjson(db[c].aggregate([{$group:{_id:"$geometry.type", n:{$sum:1}}}]).toArray()))

// the most intense fire of the season
db.fire_hotspots.find().sort({frp: -1}).limit(1)

// $geoWithin + $centerSphere — radius in RADIANS (km / 6378.1)
db.fire_hotspots.countDocuments({geometry: {$geoWithin:
  {$centerSphere: [[76.70, 11.41], 5 / 6378.1]}}})

// explain: index vs scan
db.bench = db.sightings
db.sightings.find({geometry: {$geoWithin: {$centerSphere: [[76.70,11.41], 5/6378.1]}}})
  .explain("executionStats").executionStats
db.sightings.find({geometry: {$geoWithin: {$centerSphere: [[76.70,11.41], 5/6378.1]}}})
  .hint({$natural: 1}).explain("executionStats").executionStats

// the derived zones
db.derived_zones.find({}, {zone_type:1, input_count:1, n_parts:1, area_km2:1, params:1, _id:0})
```

---

## 5. If something breaks

| problem | fix |
|---|---|
| `mongod` not running | `sudo systemctl start mongod` |
| map tiles blank | no internet — the vector layers still render; say so and move on |
| a query returns 0 | check `use forestgeo` was run |
| laptop dies | the screen recording from step 5 |
| asked to re-run the pipeline | `python scripts/clean_validate.py && python scripts/load_mongo.py && python scripts/core_queries.py` — about 40 seconds, no network |

**Never demo the fetch scripts.** They need three public APIs; Overpass refused
connections three times during development.

---

## 6. Numbers worth memorising

| | |
|---|---|
| study area | 6,519 km², 54% forest |
| raw → clean | 46,779 → 46,208 features, **0 invalid, 0 rejected** |
| collections | 10, all 2dsphere-indexed |
| hotspots | 1,564 (Jan–May 2024, 201 low-confidence dropped) |
| sightings | 2,661, 72 species |
| habitat block | 119 polygons → 23 blocks, 3,520 km² |
| burn footprint | 1,564 points → 1,051 km² |
| critical zone | 862 km² |
| **villages at risk** | **79 of 421** (111 in the burn footprint) |
| most exposed village | Thoraihatty — 239 hotspots within 5 km |
| most fires | Sathyamangalam Tiger Reserve, 52 |
| most sightings | Mudumalai, 533 (1.589 / km²) |
| index gain (local, 250k synthetic) | **180×** at 0.2% selectivity, **1.3×** at 25% |
| index gain (Atlas, real transport) | **32×** — 24 ms indexed vs 763 ms scanned |
| Atlas network overhead | **~95 ms per query** — wall-clock shows 97.3 vs 98.1 ms, i.e. nothing |
| obscured records | 24.7%, incl. 48 tiger and 170 elephant |
| sightings near roads | 88.7% within 500 m (observer bias) |
