#!/usr/bin/env python
"""Phase 4 - run the four core spatial operations and save every result to outputs/.

  Q1  $nearSphere / $geoNear  villages near the most intense fire hotspots
  Q2  $nearSphere / $geoNear  wildlife sightings near roads
  Q3  $geoWithin              sightings / hotspots / villages inside protected areas
  Q4  $geoIntersects          roads, tracks, railways and rivers crossing reserves

Run:  python scripts/core_queries.py
"""

from __future__ import annotations

from forestgeo import config
from forestgeo.db import get_db
from forestgeo.queries import (crossings, protected_area_counts, save,
                               sightings_near_roads, sightings_near_roads_summary,
                               villages_near_hotspots)


def main() -> int:
    db = get_db()
    print(f"Phase 4 - core spatial queries | {config.REGION_NAME}\n")
    notes = []

    # ---------------------------------------------------------------- Q1
    print("Q1  $geoNear - villages within "
          f"{config.NEAR_VILLAGE_M/1000:g} km of the top-20 hotspots by FRP")
    q1 = villages_near_hotspots(db, top_n=20)
    if q1.empty:
        print("    no villages within range of the top hotspots")
    else:
        print(f"    {len(q1)} village-hotspot pairs, "
              f"{q1.village.nunique()} distinct villages")
        print(q1.head(8).to_string(index=False))
        notes.append(
            f"Q1: {q1.village.nunique()} distinct villages lie within "
            f"{config.NEAR_VILLAGE_M/1000:g} km of the 20 most intense hotspots; "
            f"closest was {q1.village.iloc[0]} at {q1.distance_m.min():.0f} m.")
    print("   ->", save(q1, "q1_villages_near_fire.csv"), "\n")

    # ---------------------------------------------------------------- Q2
    print(f"Q2  $geoNear - sightings within {config.NEAR_ROAD_M} m of a road "
          "(precise records only, roadkill dataset excluded)")
    q2 = sightings_near_roads(db)
    if q2.empty:
        print("    no sightings matched the precision filter")
    else:
        pct = 100 * q2.near_road.mean()
        print(f"    {len(q2)} sightings tested | {q2.near_road.sum()} within "
              f"{config.NEAR_ROAD_M} m ({pct:.1f}%)")
        summary = sightings_near_roads_summary(q2)
        print(summary.head(8).to_string(index=False))
        save(summary, "q2_sightings_near_roads_by_species.csv")
        notes.append(
            f"Q2: {pct:.1f}% of {len(q2)} precisely-located, non-roadkill sightings "
            f"fall within {config.NEAR_ROAD_M} m of a road.")

        # The contrast that shows why the roadkill dataset had to be excluded.
        q2_all = sightings_near_roads(db, exclude_roadkill=False)
        pct_all = 100 * q2_all.near_road.mean()
        print(f"    with roadkill records included: {pct_all:.1f}% "
              f"(n={len(q2_all)}) <- circular, hence excluded")
        notes.append(
            f"Q2 control: including the roadkill dataset raises the figure to "
            f"{pct_all:.1f}%, confirming that dataset would have made the "
            f"statistic circular.")
    print("   ->", save(q2, "q2_sightings_near_roads.csv"), "\n")

    # ---------------------------------------------------------------- Q3
    print("Q3  $geoWithin - what lies inside each protected area")
    q3 = protected_area_counts(db)
    print(q3.to_string(index=False))
    if not q3.empty:
        notes.append(
            f"Q3: {int(q3.n_hotspots.sum())} hotspots, {int(q3.n_sightings.sum())} "
            f"sightings and {int(q3.n_villages.sum())} villages fall inside the "
            f"{len(q3)} protected areas.")
    print("   ->", save(q3, "q3_protected_area_counts.csv"), "\n")

    # ---------------------------------------------------------------- Q4
    print("Q4  $geoIntersects - linear features crossing protected areas")
    q4 = crossings(db)
    pa = q4[q4.target_type == "protected_area"]
    pivot = (pa.pivot_table(index="target", columns="feature", values="n_crossing",
                            aggfunc="sum", fill_value=0)
               .sort_values("road", ascending=False))
    print(pivot.head(10).to_string())
    if not pa.empty:
        by_kind = pa.groupby("feature").n_crossing.sum().to_dict()
        notes.append(f"Q4: features crossing protected areas - {by_kind}.")
    print("   ->", save(q4, "q4_crossings.csv"), "\n")

    # ------------------------------------------------------------- notes
    path = config.OUTPUT_DIR / "notes.md"
    with path.open("w") as fh:
        fh.write("# Query results - interpretation\n\n")
        fh.write(f"Region: {config.REGION_NAME}, bbox {config.BBOX}\n")
        fh.write(f"Fire season: {config.FIRE_SEASON[0]} to {config.FIRE_SEASON[1]}\n\n")
        for n in notes:
            fh.write(f"- {n}\n")
    print(f"Interpretation notes -> {path}")
    print("\nPhase 4 complete - MVP checkpoint A reached.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
