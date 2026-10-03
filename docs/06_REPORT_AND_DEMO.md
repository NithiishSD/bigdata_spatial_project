# 06 — Report, Demo & Viva Prep

## 1. Report outline (≈ 12–20 pages)

| # | Section | What to put in it | Source of content |
|---|---|---|---|
| 1 | Abstract | Your "Full description" paragraph, plus 2–3 headline numbers | `outputs/` |
| 2 | Introduction & motivation | Overlapping pressures in hill forests; why a single spatial DB | `01_PROJECT_GUIDE §1` |
| 3 | Study area | Nilgiris map, bbox, why chosen | screenshot + `01_PROJECT_GUIDE §6` |
| 4 | Data | Inventory table (rows raw/clean, source, licence, date) | `outputs/data_inventory.csv` |
| 5 | System design | Architecture diagram, collection schema table, index list | `01_PROJECT_GUIDE §3`, `forestgeo/config.py` |
| 6 | Data preparation | Validation steps + counts of fixed/dropped geometries; CRS strategy | `outputs/validation_report.csv` |
| 7 | Spatial operations | For each of the 4 ops: question → query code → result table/figure → interpretation | `outputs/q1…q4` |
| 8 | Union & derived zones | Method (closing, buffer), input_count → n_parts, areas; why outside MongoDB | `derived_zones` docs |
| 9 | Cross-theme analysis | Critical zone logic, villages/tracks at risk, risk table (top 10) | `outputs/q6_village_risk.csv` |
| 10 | Performance evaluation | Method, table, chart, explain excerpts, `$nearSphere` requires index | `outputs/benchmark*.csv/png` |
| 11 | Visualisation | Map screenshots (layers, timeline frames) | `outputs/forestgeo_map.html` |
| 12 | Limitations | Sampling bias, obscured coordinates, FIRMS false positives, OSM gaps, M0 latency | `01_PROJECT_GUIDE §7` |
| 13 | Conclusion & future work | Stretch goals list | `02_ROADMAP` |
| 14 | References | OSM, FIRMS, GBIF citation, MongoDB docs, Shapely | — |

**Writing tip:** every result paragraph = *question → method (one line) → number → meaning*.
e.g. "38 of 412 villages (9 %) lie inside the 1 km burn-risk footprint; 21 of these are also within
2 km of the continuous habitat block, forming the critical zone."

## 2. Figures checklist

- [ ] Study-area map with bbox
- [ ] Architecture diagram
- [ ] Before/after union (forest polygons vs habitat block)
- [ ] Burn-risk footprint over hotspots
- [ ] Critical zone with at-risk villages & tracks
- [ ] Benchmark chart (time + docsExamined)
- [ ] Map screenshot with layer control open
- [ ] 2–3 timeline frames (early, peak, late fire season)

## 3. 5-minute demo script

| Time | Show | Say |
|---|---|---|
| 0:00 | Title + map overview | "Four pressures, three data sources, one spatial database." |
| 0:30 | Atlas UI: collections + indexes | "Point, LineString, Polygon collections — all 2dsphere-indexed, validated with Shapely." |
| 1:15 | Run `05_core_queries.py` (or show CSVs) | One sentence per operation with a headline number. |
| 2:15 | Map: toggle forests → habitat block; hotspots → burn footprint | "MongoDB can't build geometry, so union happens in Shapely and is stored back for querying." |
| 3:00 | Map: critical zone + red villages | The cross-theme result. |
| 3:45 | Benchmark chart | "Index keeps docs examined ≈ results; collection scan grows linearly. `$nearSphere` can't even run without it." |
| 4:30 | Play fire timeline | Peak weeks, where fires cluster. |
| 4:50 | Limitations + future work | One line each. |

**Backup plan:** record a screen video of the demo and keep the HTML map offline — Wi-Fi or Atlas
can fail on demo day.

## 4. Likely viva / examiner questions (prepare answers)

1. Why MongoDB instead of PostGIS? What did you lose? *(no union/buffer/intersection; fewer spatial functions)*
2. How does a 2dsphere index work? *(S2 cells covering geometry; query finds candidate cells then exact check)*
3. Difference between `$geoWithin` and `$geoIntersects`? Give an example from your data.
4. Why does `$nearSphere` need an index but `$geoWithin` doesn't?
5. Why `[lon, lat]`? What happens if swapped?
6. Why reproject to UTM for buffering? What's the error if you don't?
7. How did you validate geometries? How many were invalid, and what kinds?
8. What does `totalDocsExamined` tell you vs `executionTimeMillis`?
9. Why was the unindexed query not slower on real data? *(small collections; network dominates)*
10. How would this scale to all of India? *(sharding on a zone key, bigger cluster, pre-computed tiles, batch jobs)*
11. How sensitive are results to the 1 km buffer / 2 km habitat distance?
12. Are sightings near roads because animals like roads? *(no — observer bias; random-point baseline)*
13. What are false positives in FIRMS?
14. How would you keep the data updated? *(scheduled FIRMS NRT fetch + upsert by (lat, lon, acq_datetime))*
15. Why store derived geometries in MongoDB rather than recomputing?
