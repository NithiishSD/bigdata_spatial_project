# ForestGeo Risk Analyser

Forested hill regions face overlapping pressures from wildfires, roads, settlements and wildlife
movement, yet the data describing them usually sits in separate sources. **ForestGeo Risk Analyser**
brings these datasets together in a single **MongoDB Atlas** spatial database and uses spatial queries
to reveal where the pressures coincide.

**Study area:** The Nilgiris, Tamil Nadu, India — bbox `76.20, 11.10, 77.10, 11.70`.

## Features
- MongoDB Atlas + PyMongo, all geometry fields **2dsphere**-indexed
- Open, reproducible data: OpenStreetMap, GBIF (incl. iNaturalist), NASA FIRMS
- **Point, LineString, Polygon** geometries, validated with Shapely before loading
- `$nearSphere`, `$geoWithin`, `$geoIntersects`, and **geometric union** (Shapely → stored in MongoDB)
- Cross-theme query: tracks & villages in the burn-risk footprint near continuous habitat
- Index performance comparison with `explain("executionStats")`
- Interactive **Folium** map with layers and an animated fire-hotspot timeline

## Quick start
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e .
cp .env.example .env        # fill in MONGODB_URI and FIRMS_MAP_KEY

# run in this order — each step consumes the previous step's output
python scripts/check_connection.py
python scripts/fetch_data.py
python scripts/clean_validate.py
python scripts/load_mongo.py
python scripts/create_indexes.py
python scripts/core_queries.py
python scripts/build_unions.py
python scripts/cross_theme.py
python scripts/benchmark.py
python scripts/build_map.py          # → outputs/forestgeo_map.html
```

## Data credits
© OpenStreetMap contributors (ODbL) · NASA FIRMS (LANCE) · GBIF.org occurrence data.
