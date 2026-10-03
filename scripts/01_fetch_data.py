#!/usr/bin/env python
"""Phase 1 — download every raw dataset into data/raw/ and write an inventory.

Idempotent: re-running overwrites the same raw files (osmnx also caches Overpass
responses in cache/, so repeat runs are fast).

Run:  python scripts/01_fetch_data.py                 # everything
      python scripts/01_fetch_data.py --only osm      # one source group
      python scripts/01_fetch_data.py --test          # tiny bbox around Ooty first
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from forestgeo import config  # noqa: E402
from forestgeo.logutil import banner, setup  # noqa: E402

log = logging.getLogger("fetch")

TEST_BBOX = (76.65, 11.35, 76.75, 11.45)  # small area around Ooty, for a smoke test


def inventory_row(dataset: str, path: Path, rows: int, source: str) -> dict:
    return {
        "dataset": dataset,
        "file": str(path.relative_to(config.ROOT)) if path.exists() else "(missing)",
        "rows_raw": rows,
        "size_kb": round(path.stat().st_size / 1024, 1) if path.exists() else 0,
        "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
        "source": source,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["osm", "firms", "gbif"], action="append",
                    help="fetch only these source groups (repeatable)")
    ap.add_argument("--test", action="store_true", help="use a small test bbox (OSM only)")
    args = ap.parse_args()
    groups = set(args.only or ["osm", "firms", "gbif"])

    setup()
    config.ensure_dirs()
    bbox = TEST_BBOX if args.test else config.BBOX
    banner(f"Phase 1 — fetch raw data | {config.REGION_NAME} | bbox={bbox}")

    inv: list[dict] = []
    failures: list[str] = []

    if "osm" in groups:
        from forestgeo.fetch_osm import LAYERS, fetch_layer
        for name in LAYERS:
            banner(f"OSM: {name}")
            try:
                gdf = fetch_layer(name, bbox=bbox)
                inv.append(inventory_row(f"osm_{name}", config.RAW_DIR / f"osm_{name}.geojson",
                                         len(gdf), "OpenStreetMap / ODbL (via Overpass)"))
            except Exception as exc:
                log.error("OSM %s failed: %s", name, exc)
                failures.append(f"osm_{name}: {exc}")

    if "firms" in groups:
        banner("NASA FIRMS: VIIRS hotspots")
        try:
            from forestgeo.fetch_firms import fetch_firms, key_status
            log.info("MAP_KEY status: %s", key_status().replace("\n", " | ")[:200])
            df = fetch_firms(season=config.FIRE_SEASON)
            inv.append(inventory_row("firms_viirs", config.RAW_DIR / "firms_viirs.csv",
                                     len(df), "NASA FIRMS VIIRS 375 m (SP) / public domain"))
        except Exception as exc:
            log.error("FIRMS failed: %s", exc)
            failures.append(f"firms: {exc}")

    if "gbif" in groups:
        banner("GBIF: wildlife sightings")
        try:
            from forestgeo.fetch_gbif import fetch_gbif
            df = fetch_gbif()
            inv.append(inventory_row("gbif_sightings", config.RAW_DIR / "gbif_sightings.csv",
                                     len(df), "GBIF.org occurrence search / CC-BY"))
        except Exception as exc:
            log.error("GBIF failed: %s", exc)
            failures.append(f"gbif: {exc}")

    banner("Inventory")
    if inv:
        inv_df = pd.DataFrame(inv)
        path = config.OUTPUT_DIR / "data_inventory.csv"
        # Merge with any previous inventory so partial runs accumulate.
        if path.exists():
            old = pd.read_csv(path)
            inv_df = (pd.concat([old, inv_df], ignore_index=True)
                      .drop_duplicates(subset="dataset", keep="last")
                      .sort_values("dataset"))
        inv_df.to_csv(path, index=False)
        print(inv_df.to_string(index=False))
        log.info("wrote %s", path)

    if failures:
        banner("FAILURES")
        for f in failures:
            print(f"  - {f}")
        print("\nSee docs/05_TROUBLESHOOTING.md. Re-run just the failed group with --only <group>.")
        return 1
    print("\nPhase 1 complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
