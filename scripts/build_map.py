#!/usr/bin/env python
"""Phase 8 - build the interactive Folium map with the animated fire timeline.

Run:  python scripts/build_map.py
Then open outputs/forestgeo_map.html in a browser.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from forestgeo import config
from forestgeo.db import get_db
from forestgeo.mapviz import build


def main() -> int:
    db = get_db()
    print(f"Phase 8 - interactive map | {config.REGION_NAME}\n")

    risk_path = config.OUTPUT_DIR / "q6_village_risk.csv"
    risk = None
    if risk_path.exists():
        risk = pd.read_csv(risk_path)
        print(f"  village risk scores loaded ({len(risk)} villages) - "
              "villages will be coloured by risk")
    else:
        print("  no q6_village_risk.csv - run scripts/cross_theme.py first for "
              "risk colouring")

    path = build(db, risk)
    size_mb = Path(path).stat().st_size / 1e6
    print(f"\n  map -> {path}  ({size_mb:.1f} MB)")
    if size_mb > 30:
        print("  !! over 30 MB - consider limiting transport to main road classes")
    print("\nPhase 8 complete - MVP done. Open the file in a browser.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
