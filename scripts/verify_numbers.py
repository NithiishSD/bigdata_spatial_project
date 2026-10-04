#!/usr/bin/env python
"""Check that every headline number quoted in the docs matches the actual outputs.

Documentation drifts the moment a pipeline is re-run. This script recomputes the figures
the docs cite from outputs/ and reports any that no longer appear, so a stale number is a
failed check rather than something a reader notices.

Run:  python scripts/verify_numbers.py
"""

from __future__ import annotations

import re

import pandas as pd

from forestgeo import config

DOCS = ["docs/07_CODE_EXPLAINED.md", "docs/09_DEMO_RUNBOOK.md",
        "docs/10_COLAB_AND_ATLAS.md", "docs/06_REPORT_AND_DEMO.md",
        "notebooks/forestgeo_demo.ipynb", "CLAUDE.md"]


def facts() -> dict[str, str]:
    """The numbers the documentation cites, recomputed from outputs/."""
    out = config.OUTPUT_DIR
    inv = pd.read_csv(out / "data_inventory.csv")
    val = pd.read_csv(out / "validation_report.csv")
    q2 = pd.read_csv(out / "q2_sightings_near_roads.csv")
    q3 = pd.read_csv(out / "q3_protected_area_counts.csv")
    q4 = pd.read_csv(out / "q4_crossings.csv")
    zones = pd.read_csv(out / "derived_zones_summary.csv").set_index("zone_type")
    risk = pd.read_csv(out / "q6_village_risk.csv")
    crit = pd.read_csv(out / "q6_critical_zone_contents.csv").set_index("feature")

    mud = q3[q3.protected_area.str.contains("Mudumalai", na=False)].iloc[0]
    sat = q3[q3.protected_area.str.contains("Sathyamangalam", na=False)].iloc[0]
    mud_roads = q4[(q4.target.str.contains("Mudumalai", na=False))
                   & (q4.feature == "road")].n_crossing.iloc[0]
    top = risk.iloc[0]

    return {
        "raw features": f"{inv.rows_raw.sum():,}",
        "after id dedupe": f"{val.rows_in.sum():,}",
        "valid features": f"{val.rows_out.sum():,}",
        "villages total": f"{int(val.loc[val.collection == 'villages', 'rows_out'].iloc[0]):,}",
        "transport": f"{int(val.loc[val.collection == 'transport', 'rows_out'].iloc[0]):,}",
        "hotspots": f"{int(val.loc[val.collection == 'fire_hotspots', 'rows_out'].iloc[0]):,}",
        "sightings": f"{int(val.loc[val.collection == 'sightings', 'rows_out'].iloc[0]):,}",
        "protected areas": str(int(val.loc[val.collection == 'protected_areas', 'rows_out'].iloc[0])),
        "forests": str(int(val.loc[val.collection == 'forests', 'rows_out'].iloc[0])),
        "Q2 tested": f"{len(q2):,}",
        "Q2 pct near road": f"{100 * q2.near_road.mean():.1f}%",
        "Sathyamangalam hotspots": str(int(sat.n_hotspots)),
        "Sathyamangalam sightings": str(int(sat.n_sightings)),
        "Mudumalai sightings": str(int(mud.n_sightings)),
        "Mudumalai density": f"{mud.sightings_per_km2:.3f}",
        "Mudumalai roads crossing": str(int(mud_roads)),
        "habitat block parts": str(int(zones.loc["habitat_block", "n_parts"])),
        "habitat block km2": f"{zones.loc['habitat_block', 'area_km2']:,.0f}",
        "burn footprint km2": f"{zones.loc['burn_risk_footprint', 'area_km2']:,.0f}",
        "critical zone km2": str(int(round(zones.loc["critical_zone", "area_km2"]))),
        "villages in critical zone": str(int(risk.in_critical_zone.sum())),
        "villages in burn footprint": str(int(risk.in_burn_footprint.sum())),
        "top village": str(top.village),
        "top village hotspots": str(int(top.n_hotspots_5km)),
        "hotspots in critical zone": f"{int(crit.loc['fire_hotspots', 'n']):,}",
    }


def main() -> int:
    text = {}
    for path in DOCS:
        p = config.ROOT / path
        if p.exists():
            text[path] = p.read_text()

    print("Checking documented figures against outputs/\n")
    rows, missing = [], 0
    for label, value in facts().items():
        # a figure is "cited" if it appears anywhere in the docs
        where = [d for d, t in text.items() if value in t]
        rows.append({"figure": label, "actual": value,
                     "cited in": len(where),
                     "status": "ok" if where else "NOT FOUND"})
        if not where:
            missing += 1
    df = pd.DataFrame(rows)
    print(df.to_string(index=False))

    if missing:
        print(f"\n{missing} figure(s) do not appear in any doc. Either the docs are "
              "stale, or the figure is simply not quoted anywhere - check each one.")
        return 1
    print("\nEvery recomputed figure appears in the documentation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
