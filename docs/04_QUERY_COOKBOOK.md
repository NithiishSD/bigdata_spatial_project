# 04 — Query & Code Cookbook

Reference implementations for every step. Copy them into the `forestgeo/` package and adapt.
Every snippet assumes:

```python
from forestgeo.db import get_db
from forestgeo.config import *     # BBOX, CRS_METRIC, HOTSPOT_BUFFER_M, ...
db = get_db()
```

Contents: §1 Geometry helpers · §2 Loading & indexes · §3 `$nearSphere` · §4 `$geoWithin` &
`$geoIntersects` · §5 Union · §6 Cross-theme · §7 Benchmark · §8 Folium map

---

## §1 Geometry helpers (`forestgeo/geo.py`)

```python
import shapely
from shapely.geometry import MultiLineString, MultiPolygon
from shapely.ops import transform
from pyproj import Transformer
from forestgeo.config import CRS_METRIC

_to_m  = Transformer.from_crs("EPSG:4326", CRS_METRIC, always_xy=True).transform
_to_ll = Transformer.from_crs(CRS_METRIC, "EPSG:4326", always_xy=True).transform

def to_metric(g):  return transform(_to_m, g)    # degrees → metres (UTM 43N)
def to_wgs84(g):   return transform(_to_ll, g)   # metres → degrees

BASE = {"point": "Point", "line": "LineString", "polygon": "Polygon"}

def flatten(g):
    """Yield single-part geometries from Multi*/GeometryCollection."""
    if hasattr(g, "geoms"):
        for part in g.geoms:
            yield from flatten(part)
    else:
        yield g

def _keep_family(g, family):
    parts = [p for p in flatten(g) if p.geom_type == BASE[family] and not p.is_empty]
    if not parts:
        return None
    if family == "point":
        return parts[0]
    if family == "line":
        return parts[0] if len(parts) == 1 else MultiLineString(parts)
    return shapely.union_all(parts)          # polygons: merge overlapping pieces

def clean_geometry(g, family: str):
    """Return a MongoDB-safe geometry of the given family ('point'|'line'|'polygon') or None."""
    if g is None or g.is_empty:
        return None
    if not g.is_valid:
        g = shapely.make_valid(g)            # fixes self-intersections, bow-ties, etc.
    g = _keep_family(g, family)
    if g is None:
        return None
    g = shapely.set_precision(g, 1e-6)        # ~0.1 m; removes near-duplicate vertices
    g = shapely.remove_repeated_points(g)
    if g.is_empty or not g.is_valid:
        return None
    return _keep_family(g, family)           # set_precision can change type; re-check

def simplify_m(g, tol_m: float):
    """Simplify with a tolerance in metres (done in UTM)."""
    return to_wgs84(to_metric(g).simplify(tol_m, preserve_topology=True))
```

**Why each step matters**
- `make_valid`: MongoDB rejects self-intersecting polygons with *"Can't extract geo keys … Edges cross"*.
- `_keep_family`: `make_valid` may return a `GeometryCollection` (polygon + stray line) — MongoDB
  can index that, but your queries expect polygons.
- `set_precision` + `remove_repeated_points`: fixes *"Duplicate vertices"* errors and shrinks docs.
- Polygons: `area_km2 = to_metric(g).area / 1e6`.

---

## §2 Loading & indexes (`forestgeo/load.py`)

```python
import datetime as dt, json, math
import numpy as np, pandas as pd
from shapely.geometry import mapping
from pymongo.errors import BulkWriteError

def _py(v):
    """Convert pandas/numpy values to BSON-friendly Python types."""
    if v is None: return None
    if isinstance(v, float) and math.isnan(v): return None
    if isinstance(v, np.integer): return int(v)
    if isinstance(v, np.floating): return None if np.isnan(v) else float(v)
    if isinstance(v, pd.Timestamp): return v.to_pydatetime()
    return v

def gdf_to_docs(gdf, source: str, id_col: str, fields: list[str]):
    now = dt.datetime.now(dt.timezone.utc)
    docs = []
    for rec in gdf.to_dict("records"):
        docs.append({
            "source": source,
            "source_id": str(rec[id_col]),
            **{f: _py(rec.get(f)) for f in fields},
            "geometry": mapping(rec["geometry"]),
            "ingested_at": now,
        })
    return docs

def load_collection(db, name, docs, extra_indexes=()):
    coll = db[name]
    coll.drop()                                         # idempotent re-runs
    coll.create_index([("geometry", "2dsphere")])       # index FIRST → bad docs fail individually
    for keys in extra_indexes:
        coll.create_index(keys)
    try:
        inserted = len(coll.insert_many(docs, ordered=False).inserted_ids)
    except BulkWriteError as e:
        inserted = e.details["nInserted"]
        with open(f"outputs/rejected_{name}.jsonl", "w") as f:
            for err in e.details["writeErrors"]:
                f.write(json.dumps({"index": err["index"],
                                    "source_id": docs[err["index"]].get("source_id"),
                                    "error": err["errmsg"][:300]}) + "\n")
    print(f"{name}: inserted {inserted}/{len(docs)}")
    return inserted
```

Extra indexes to create:
```python
load_collection(db, "fire_hotspots", docs, extra_indexes=[[("acq_datetime", 1)], [("frp", -1)]])
load_collection(db, "transport", docs, extra_indexes=[[("kind", 1)]])
```

Verification:
```python
for name in db.list_collection_names():
    types = list(db[name].aggregate([{"$group": {"_id": "$geometry.type", "n": {"$sum": 1}}}]))
    print(name, db[name].estimated_document_count(), types,
          [ix["name"] for ix in db[name].list_indexes()])
```

---

## §3 `$nearSphere` (and `$geoNear` when you need distances)

### Q1 — Villages near the strongest fire hotspots
```python
rows = []
top = db.fire_hotspots.find({}, {"geometry": 1, "frp": 1, "acq_datetime": 1}).sort("frp", -1).limit(20)
for h in top:
    cur = db.villages.find(
        {"geometry": {"$nearSphere": {"$geometry": h["geometry"],
                                      "$maxDistance": NEAR_VILLAGE_M}}},   # metres
        {"name": 1},
    )
    for rank, v in enumerate(cur, 1):                   # already sorted nearest → farthest
        rows.append({"hotspot_id": str(h["_id"]), "frp": h["frp"],
                     "date": h["acq_datetime"], "village": v.get("name"), "rank": rank})
pd.DataFrame(rows).to_csv("outputs/q1_villages_near_fire.csv", index=False)
```

Same thing **with distances** (aggregation — `$geoNear` must be the first stage):
```python
pipeline = [
    {"$geoNear": {"near": h["geometry"], "key": "geometry", "spherical": True,
                  "distanceField": "dist_m", "maxDistance": NEAR_VILLAGE_M}},
    {"$project": {"name": 1, "dist_m": {"$round": ["$dist_m", 0]}}},
]
list(db.villages.aggregate(pipeline))
```

### Q2 — Sightings near roads
`$nearSphere` needs a **Point** as reference → iterate over sightings and search the `transport`
collection (2dsphere indexes lines, so "nearest road to this point" works).

```python
from concurrent.futures import ThreadPoolExecutor

def nearest_road(s):
    r = db.transport.find_one(
        {"kind": {"$in": ["road", "track"]},
         "geometry": {"$nearSphere": {"$geometry": s["geometry"], "$maxDistance": NEAR_ROAD_M}}},
        {"kind": 1, "highway": 1, "name": 1},
    )
    return {"gbif_id": s["source_id"], "species": s.get("species"), "class": s.get("class"),
            "near_road": r is not None, "road_kind": r and r.get("kind"),
            "highway": r and r.get("highway")}

sightings = list(db.sightings.find({}, {"geometry": 1, "source_id": 1, "species": 1, "class": 1}))
with ThreadPoolExecutor(max_workers=8) as pool:          # Atlas round-trips are the bottleneck
    rows = list(pool.map(nearest_road, sightings))
df = pd.DataFrame(rows)
df.to_csv("outputs/q2_sightings_near_roads.csv", index=False)
print(df.groupby("class")["near_road"].mean().round(3))   # share within 500 m of a road
```
💡 **Make it a real finding:** repeat with the same number of *random points* in the bbox. If 70 % of
sightings but only 30 % of random points are within 500 m of a road, that's observer (access) bias —
a great discussion point.

---

## §4 `$geoWithin` and `$geoIntersects`

### Q3 — Sightings and hotspots inside each protected area (`$geoWithin`)
```python
rows = []
for pa in db.protected_areas.find({}, {"name": 1, "geometry": 1, "area_km2": 1}):
    inside = {"geometry": {"$geoWithin": {"$geometry": pa["geometry"]}}}
    n_s = db.sightings.count_documents(inside)
    n_h = db.fire_hotspots.count_documents(inside)
    rows.append({"protected_area": pa.get("name"), "area_km2": pa.get("area_km2"),
                 "sightings": n_s, "hotspots": n_h,
                 "sightings_per_km2": n_s / pa["area_km2"] if pa.get("area_km2") else None,
                 "hotspots_per_km2": n_h / pa["area_km2"] if pa.get("area_km2") else None})
pd.DataFrame(rows).sort_values("hotspots", ascending=False).to_csv("outputs/q3_pa_counts.csv", index=False)
```
Note: protected areas can overlap (a national park inside a tiger reserve) → per-row counts are
correct but **don't sum the column**.

Bonus (aggregation): hotspots per month inside one PA
```python
db.fire_hotspots.aggregate([
    {"$match": {"geometry": {"$geoWithin": {"$geometry": pa["geometry"]}}}},
    {"$group": {"_id": {"$dateToString": {"format": "%Y-%m", "date": "$acq_datetime"}},
                "n": {"$sum": 1}, "mean_frp": {"$avg": "$frp"}}},
    {"$sort": {"_id": 1}},
])
```

Circle version (works in `count_documents`, unlike `$nearSphere`):
```python
{"geometry": {"$geoWithin": {"$centerSphere": [[lon, lat], 5 / 6378.1]}}}   # 5 km, radius in radians
```

### Q4 — Roads, railways, tracks crossing protected areas / water bodies (`$geoIntersects`)
```python
rows = []
for pa in db.protected_areas.find({}, {"name": 1, "geometry": 1}):
    for g in db.transport.aggregate([
        {"$match": {"geometry": {"$geoIntersects": {"$geometry": pa["geometry"]}}}},
        {"$group": {"_id": "$kind", "segments": {"$sum": 1}}},
    ]):
        rows.append({"target": "protected_area", "name": pa.get("name"),
                     "kind": g["_id"], "segments": g["segments"]})

for wb in db.water_bodies.find({"area_km2": {"$gte": 0.05}}, {"name": 1, "geometry": 1}):
    n = db.transport.count_documents({"geometry": {"$geoIntersects": {"$geometry": wb["geometry"]}}})
    if n:
        rows.append({"target": "water_body", "name": wb.get("name"), "kind": "all", "segments": n})
pd.DataFrame(rows).to_csv("outputs/q4_crossings.csv", index=False)
```
**Km of road inside each PA** (MongoDB can't measure; Shapely can): fetch the intersecting lines,
then `sum(to_metric(shape(l)).intersection(to_metric(shape(pa))).length) / 1000`.

---

## §5 Union — habitat block & burn-risk footprint (`forestgeo/unions.py`)

```python
import datetime as dt, bson, numpy as np, shapely
from shapely.geometry import shape, mapping, MultiPolygon
from forestgeo.geo import to_metric, to_wgs84, clean_geometry, flatten

def store_zone(db, zone_type, geom_wgs84, params, input_count, area_km2):
    doc = {"zone_type": zone_type, "geometry": mapping(geom_wgs84), "params": params,
           "input_count": input_count, "area_km2": round(area_km2, 3),
           "n_parts": len(list(flatten(geom_wgs84))),
           "created_at": dt.datetime.now(dt.timezone.utc)}
    size_mb = len(bson.encode(doc)) / 1e6
    assert size_mb < 15, f"{zone_type} is {size_mb:.1f} MB — simplify more"
    db.derived_zones.create_index([("geometry", "2dsphere")])
    db.derived_zones.create_index("zone_type")
    db.derived_zones.replace_one({"zone_type": zone_type}, doc, upsert=True)
    print(f"{zone_type}: {doc['n_parts']} parts, {area_km2:.1f} km², {size_mb:.2f} MB")

def build_habitat_block(db, gap_m=HABITAT_GAP_CLOSE_M, min_part_km2=1.0, simplify_m=20):
    forests = [to_metric(shape(d["geometry"])) for d in db.forests.find({}, {"geometry": 1})]
    grown = shapely.buffer(np.array(forests, dtype=object), gap_m)      # close small gaps
    merged = shapely.union_all(grown).buffer(-gap_m)                    # shrink back
    parts = [p for p in flatten(merged) if p.area >= min_part_km2 * 1e6]
    merged = MultiPolygon(parts).simplify(simplify_m, preserve_topology=True)
    geom = clean_geometry(to_wgs84(merged), "polygon")
    store_zone(db, "habitat_block", geom,
               {"gap_close_m": gap_m, "min_part_km2": min_part_km2, "simplify_m": simplify_m},
               len(forests), merged.area / 1e6)

def build_burn_footprint(db, buffer_m=HOTSPOT_BUFFER_M, simplify_m=20):
    pts = [to_metric(shape(d["geometry"])) for d in db.fire_hotspots.find({}, {"geometry": 1})]
    circles = shapely.buffer(np.array(pts, dtype=object), buffer_m)
    merged = shapely.union_all(circles).simplify(simplify_m, preserve_topology=True)
    geom = clean_geometry(to_wgs84(merged), "polygon")
    store_zone(db, "burn_risk_footprint", geom,
               {"buffer_m": buffer_m, "simplify_m": simplify_m}, len(pts), merged.area / 1e6)
```

**Why buffer(+gap) then buffer(−gap)?** Two forest polygons separated by a 10 m road would stay
separate in a plain union. Growing then shrinking ("morphological closing") fuses them without
changing the outer boundary much. Report `input_count → n_parts` as evidence of merging.

**Now query the derived zones with MongoDB (required by the brief):**
```python
burn = db.derived_zones.find_one({"zone_type": "burn_risk_footprint"})["geometry"]
habitat = db.derived_zones.find_one({"zone_type": "habitat_block"})["geometry"]

db.villages.count_documents({"geometry": {"$geoWithin": {"$geometry": burn}}})       # villages in burn zone
db.protected_areas.find({"geometry": {"$geoIntersects": {"$geometry": habitat}}}, {"name": 1})

# Reverse direction — the derived collection is itself queryable by its own 2dsphere index:
db.derived_zones.find({"geometry": {"$geoIntersects": {"$geometry": some_village["geometry"]}}},
                      {"zone_type": 1})
```

---

## §6 Cross-theme query

Goal: **tracks and villages inside the burn-risk footprint *and* near the merged habitat.**

### Step 1 — build helper zones in Shapely and store them
```python
hab_m  = to_metric(shape(habitat))
burn_m = to_metric(shape(burn))
hab_buf_m = hab_m.buffer(2000)                    # "near habitat" = within 2 km
critical_m = burn_m.intersection(hab_buf_m)

store_zone(db, "habitat_buffer", clean_geometry(to_wgs84(hab_buf_m.simplify(20)), "polygon"),
           {"buffer_m": 2000}, 1, hab_buf_m.area / 1e6)
store_zone(db, "critical_zone", clean_geometry(to_wgs84(critical_m.simplify(20)), "polygon"),
           {"burn": "burn_risk_footprint", "near": "habitat_buffer"}, 2, critical_m.area / 1e6)
```

### Step 2 — query MongoDB
```python
crit = db.derived_zones.find_one({"zone_type": "critical_zone"})["geometry"]

villages_at_risk = list(db.villages.find(
    {"geometry": {"$geoWithin": {"$geometry": crit}}}, {"name": 1, "geometry": 1}))

tracks_at_risk = list(db.transport.find(
    {"kind": "track", "geometry": {"$geoIntersects": {"$geometry": crit}}}, {"name": 1, "osm_id": 1}))
```

### Alternative — let MongoDB combine two spatial predicates
```python
hab_buf = db.derived_zones.find_one({"zone_type": "habitat_buffer"})["geometry"]
q = {"$and": [
    {"geometry": {"$geoWithin": {"$geometry": burn}}},
    {"geometry": {"$geoIntersects": {"$geometry": hab_buf}}},
]}
alt = list(db.villages.find(q, {"name": 1}))
```
The two approaches should return the same villages (small differences at boundaries come from
simplification — mention it). If your MongoDB version rejects two geo predicates on one field, run
them separately and intersect the `_id` sets in Python; both are valid designs.

### Step 3 — village risk table (combines all operations)
```python
def village_risk(v):
    lon, lat = v["geometry"]["coordinates"]
    n5 = db.fire_hotspots.count_documents(
        {"geometry": {"$geoWithin": {"$centerSphere": [[lon, lat], 5 / 6378.1]}}})
    nearest = next(db.fire_hotspots.aggregate([
        {"$geoNear": {"near": v["geometry"], "key": "geometry",
                      "distanceField": "d", "spherical": True}},
        {"$limit": 1}, {"$project": {"d": 1}}]), None)
    d = nearest["d"] if nearest else 1e9
    in_zone = lambda zt: db.derived_zones.count_documents(
        {"zone_type": zt, "geometry": {"$geoIntersects": {"$geometry": v["geometry"]}}}) > 0
    in_burn, near_hab = in_zone("burn_risk_footprint"), in_zone("habitat_buffer")
    score = (0.4 * min(n5 / 10, 1) + 0.3 * (1 - min(d / 10_000, 1))
             + 0.2 * in_burn + 0.1 * near_hab)
    return {"village": v.get("name"), "lon": lon, "lat": lat, "hotspots_5km": n5,
            "nearest_hotspot_m": round(d), "in_burn_footprint": in_burn,
            "near_habitat": near_hab, "risk_score": round(score, 3)}
```
Run it over all villages (ThreadPoolExecutor as in Q2), sort by `risk_score`, save
`outputs/q6_village_risk.csv`. **State the weights are illustrative**, not a validated model.

---

## §7 Index benchmark (`forestgeo/benchmark.py`)

```python
import statistics, time

def _stages(plan):
    out = [plan["stage"]]
    for key in ("inputStage",):
        if key in plan: out += _stages(plan[key])
    for sub in plan.get("inputStages", []): out += _stages(sub)
    return out

def explain_find(coll, flt, hint=None):
    cmd = {"find": coll.name, "filter": flt}
    if hint is not None:
        cmd["hint"] = hint
    ex = coll.database.command("explain", cmd, verbosity="executionStats")
    wp = ex["queryPlanner"]["winningPlan"]
    wp = wp.get("queryPlan", wp)                      # newer servers nest the plan here
    st = ex["executionStats"]
    return {"plan": ">".join(_stages(wp)), "nReturned": st["nReturned"],
            "keysExamined": st["totalKeysExamined"], "docsExamined": st["totalDocsExamined"],
            "ms": st["executionTimeMillis"]}

def compare(coll, flt, label, runs=5):
    rows = []
    for mode, hint in (("indexed", None), ("collscan", {"$natural": 1})):
        res = [explain_find(coll, flt, hint) for _ in range(runs)]
        cur = coll.find(flt).hint([("$natural", 1)]) if hint else coll.find(flt)   # cursor.hint wants a list
        t0 = time.perf_counter(); list(cur)
        wall = (time.perf_counter() - t0) * 1000
        rows.append({"query": label, "mode": mode, "plan": res[0]["plan"],
                     "nReturned": res[0]["nReturned"], "keysExamined": res[0]["keysExamined"],
                     "docsExamined": res[0]["docsExamined"],
                     "server_ms_median": statistics.median(r["ms"] for r in res),
                     "wall_ms": round(wall, 1)})
    return rows
```

**Real-data comparisons**
```python
pa = db.protected_areas.find_one(sort=[("area_km2", -1)])       # biggest PA
rows  = compare(db.sightings, {"geometry": {"$geoWithin": {"$geometry": pa["geometry"]}}}, "Q3 within")
rows += compare(db.transport, {"geometry": {"$geoIntersects": {"$geometry": pa["geometry"]}}}, "Q4 intersects")
```

**`$nearSphere` without an index** — show that it's impossible:
```python
db.villages.drop_index("geometry_2dsphere")
try:
    list(db.villages.find({"geometry": {"$nearSphere": {"$geometry": pt, "$maxDistance": 5000}}}))
except Exception as e:
    print("Expected failure:", e)        # "unable to find index for $geoNear query"
db.villages.create_index([("geometry", "2dsphere")])     # restore!
```

**Synthetic scale test** (where the index really shows its value)
```python
import numpy as np
W, S, E, N = BBOX
box = {"type": "Polygon", "coordinates": [[[76.60, 11.35], [76.65, 11.35], [76.65, 11.40],
                                           [76.60, 11.40], [76.60, 11.35]]]}   # ~5 × 5 km
rng = np.random.default_rng(42)
rows = []
for n in (10_000, 50_000, 100_000, 250_000):
    db.bench_points.drop()
    xs, ys = rng.uniform(W, E, n), rng.uniform(S, N, n)
    db.bench_points.insert_many(
        [{"i": i, "geometry": {"type": "Point", "coordinates": [float(x), float(y)]}}
         for i, (x, y) in enumerate(zip(xs, ys))], ordered=False)
    db.bench_points.create_index([("geometry", "2dsphere")])
    for r in compare(db.bench_points, {"geometry": {"$geoWithin": {"$geometry": box}}}, "bench"):
        rows.append({**r, "n_docs": n})
pd.DataFrame(rows).to_csv("outputs/benchmark_scale.csv", index=False)
```

Plot:
```python
import matplotlib.pyplot as plt
df = pd.read_csv("outputs/benchmark_scale.csv")
fig, axes = plt.subplots(1, 2, figsize=(11, 4))
for mode, g in df.groupby("mode"):
    axes[0].plot(g.n_docs, g.server_ms_median, marker="o", label=mode)
    axes[1].plot(g.n_docs, g.docsExamined, marker="o", label=mode)
axes[0].set(xlabel="documents", ylabel="server time (ms)", title="Execution time")
axes[1].set(xlabel="documents", ylabel="docs examined", title="Documents examined", yscale="log")
for ax in axes: ax.legend(); ax.grid(alpha=.3)
plt.tight_layout(); plt.savefig("outputs/benchmark.png", dpi=150)
```
Also dump one indexed and one COLLSCAN explain JSON to `outputs/explain/` (use `bson.json_util.dumps`).

**How to read the result:** indexed `docsExamined` ≈ `nReturned` (+ some S2 cell overhead);
COLLSCAN `docsExamined` = n_docs. That ratio is the core evidence — more robust than milliseconds.

---

## §8 Folium map (`forestgeo/mapviz.py`)

```python
import folium, pandas as pd
from folium.plugins import MarkerCluster, TimestampedGeoJson

def to_fc(cursor, props):
    """Mongo cursor → GeoJSON FeatureCollection (props must be JSON-serialisable)."""
    feats = []
    for d in cursor:
        feats.append({"type": "Feature", "geometry": d["geometry"],
                      "properties": {p: (str(d.get(p)) if d.get(p) is not None else "") for p in props}})
    return {"type": "FeatureCollection", "features": feats}

m = folium.Map(location=[11.40, 76.65], zoom_start=10, tiles=None, control_scale=True)
folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(m)
folium.TileLayer("CartoDB positron", name="Light").add_to(m)
folium.TileLayer(
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attr="Esri World Imagery", name="Satellite").add_to(m)

def polygon_layer(name, coll, color, props=("name",), query=None, show=True):
    fg = folium.FeatureGroup(name=name, show=show)
    folium.GeoJson(to_fc(db[coll].find(query or {}), props),
                   style_function=lambda f, c=color: {"color": c, "weight": 1, "fillOpacity": 0.25},
                   tooltip=folium.GeoJsonTooltip(list(props))).add_to(fg)
    fg.add_to(m)

polygon_layer("Protected areas", "protected_areas", "#1b5e20")
polygon_layer("Forests", "forests", "#66bb6a", show=False)
polygon_layer("Water bodies", "water_bodies", "#1e88e5")
polygon_layer("Farmland", "farmland", "#f9a825", show=False)
polygon_layer("Habitat block (union)", "derived_zones", "#004d40", ("zone_type",), {"zone_type": "habitat_block"})
polygon_layer("Burn-risk footprint (union)", "derived_zones", "#e65100", ("zone_type",), {"zone_type": "burn_risk_footprint"})
polygon_layer("Critical zone", "derived_zones", "#b71c1c", ("zone_type",), {"zone_type": "critical_zone"})

KIND_COLOR = {"road": "#616161", "track": "#8d6e63", "railway": "#000000"}
fg = folium.FeatureGroup(name="Roads / tracks / railways")
folium.GeoJson(to_fc(db.transport.find(), ["kind", "name", "highway"]),
               style_function=lambda f: {"color": KIND_COLOR.get(f["properties"]["kind"], "grey"),
                                         "weight": 1.5},
               tooltip=folium.GeoJsonTooltip(["kind", "name"])).add_to(fg)
fg.add_to(m)

# Villages coloured by risk (from §6)
risk = pd.read_csv("outputs/q6_village_risk.csv")
fg = folium.FeatureGroup(name="Villages (risk)")
for r in risk.itertuples():
    color = "red" if r.risk_score > 0.6 else "orange" if r.risk_score > 0.3 else "green"
    folium.CircleMarker([r.lat, r.lon], radius=5, color=color, fill=True,        # Folium = [lat, lon]!
                        tooltip=f"{r.village}: {r.risk_score}").add_to(fg)
fg.add_to(m)

# Sightings clustered
mc = MarkerCluster(name="Wildlife sightings", show=False)
for s in db.sightings.find({}, {"geometry": 1, "species": 1}):
    lon, lat = s["geometry"]["coordinates"]
    folium.CircleMarker([lat, lon], radius=3, color="purple", tooltip=s.get("species")).add_to(mc)
mc.add_to(m)

# Animated fire timeline
feats = [{"type": "Feature", "geometry": h["geometry"],
          "properties": {"time": h["acq_datetime"].strftime("%Y-%m-%dT%H:%M:%S"),
                         "popup": f"FRP {h['frp']} MW",
                         "icon": "circle",
                         "iconstyle": {"fillColor": "red", "fillOpacity": 0.8, "stroke": False, "radius": 5}}}
         for h in db.fire_hotspots.find().sort("acq_datetime", 1)]
TimestampedGeoJson({"type": "FeatureCollection", "features": feats},
                   period="P1D", duration="P3D", add_last_point=False, auto_play=False,
                   loop=False, date_options="YYYY-MM-DD", time_slider_drag_update=True).add_to(m)

folium.LayerControl(collapsed=False).add_to(m)
m.get_root().html.add_child(folium.Element(
    '<h3 style="position:fixed;top:10px;left:60px;z-index:9999;background:white;padding:4px 8px;'
    'border-radius:4px">ForestGeo Risk Analyser — The Nilgiris</h3>'))
m.save("outputs/forestgeo_map.html")
```

**Notes**
- The timeline layer is controlled by its own slider (it does not appear in LayerControl).
- If the HTML is huge/slow: show forests only via the habitat block, limit transport to
  `kind in (track, railway)` + main highways, and simplify polygons *for display only*
  (`shapely.simplify(g, 0.0003)` in degrees is fine visually).
- A legend can be added with a small HTML `<div>` via `folium.Element`, like the title above.
