#!/usr/bin/env python
"""Phase 1 - download every raw dataset into data/raw/ and write the data inventory.

Idempotent: raw files are overwritten. OSM responses are cached by osmnx, so repeat
runs of unchanged queries do not touch the network.

Run:  python scripts/fetch_data.py                  # everything
      python scripts/fetch_data.py --only osm       # one source group
      python scripts/fetch_data.py --inventory      # rebuild the inventory only
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys

import pandas as pd

from forestgeo import config


def inventory() -> pd.DataFrame:
    """Describe every file in data/raw/ - row counts, size, licence."""
    import geopandas as gpd

    licences = {
        "osm": "OpenStreetMap contributors / ODbL (via Overpass API)",
        "firms": "NASA FIRMS VIIRS 375 m, Standard Processing / public domain",
        "gbif": "GBIF.org occurrence search / CC-BY",
    }
    rows = []
    for path in sorted(config.RAW_DIR.glob("*")):
        if path.suffix not in (".geojson", ".csv"):
            continue
        source = ("osm" if path.name.startswith("osm_")
                  else "firms" if path.name.startswith("firms") else "gbif")
        if path.suffix == ".geojson":
            gdf = gpd.read_file(path)
            n, types = len(gdf), "|".join(sorted(set(gdf.geometry.geom_type)))
        else:
            n, types = len(pd.read_csv(path)), "Point (from lat/lon columns)"
        rows.append({
            "dataset": path.stem,
            "file": str(path.relative_to(config.ROOT)),
            "rows_raw": n,
            "geometry": types,
            "size_kb": round(path.stat().st_size / 1024, 1),
            "modified": dt.datetime.fromtimestamp(path.stat().st_mtime)
                          .isoformat(timespec="seconds"),
            "source": licences[source],
        })
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["osm", "firms", "gbif"], action="append",
                    help="fetch only these source groups (repeatable)")
    ap.add_argument("--inventory", action="store_true",
                    help="skip fetching, just rebuild outputs/data_inventory.csv")
    args = ap.parse_args()

    config.ensure_dirs() if hasattr(config, "ensure_dirs") else None
    for d in (config.RAW_DIR, config.PROCESSED_DIR, config.OUTPUT_DIR):
        d.mkdir(parents=True, exist_ok=True)

    groups = set(args.only or ["osm", "firms", "gbif"])
    failures = []

    if not args.inventory:
        print(f"Phase 1 - fetch raw data | {config.REGION_NAME} | bbox={config.BBOX}\n")

        if "osm" in groups:
            from forestgeo.fetch_osm import LAYERS, fetch_layer
            for name in LAYERS:
                try:
                    fetch_layer(name)
                except Exception as exc:
                    print(f"  !! osm_{name}: {type(exc).__name__}: {exc}"[:200])
                    failures.append(f"osm_{name}")

        if "gbif" in groups:
            print("\nGBIF:")
            try:
                from forestgeo.fetch_gbif import fetch_gbif
                fetch_gbif()
            except Exception as exc:
                print(f"  !! gbif: {type(exc).__name__}: {exc}"[:200])
                failures.append("gbif")

        if "firms" in groups:
            print("\nFIRMS:")
            try:
                from forestgeo.fetch_firms import fetch_firms
                fetch_firms()
            except Exception as exc:
                print(f"  !! firms: {type(exc).__name__}: {exc}"[:200])
                failures.append("firms")

    inv = inventory()
    path = config.OUTPUT_DIR / "data_inventory.csv"
    inv.to_csv(path, index=False)
    print("\nData inventory")
    print(inv[["dataset", "rows_raw", "geometry", "size_kb"]].to_string(index=False))
    print(f"\ntotal raw features: {inv.rows_raw.sum():,}  ->  {path}")

    if failures:
        print(f"\nFAILED: {failures} - re-run with --only <group>")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
