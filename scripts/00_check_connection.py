#!/usr/bin/env python
"""Phase 0 — prove the environment works: libraries import, CRS is right, Mongo answers.

Run:  python scripts/00_check_connection.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pymongo.errors import PyMongoError  # noqa: E402

from forestgeo import config  # noqa: E402
from forestgeo.db import get_db, safe_uri  # noqa: E402


def check_crs() -> bool:
    """CRS_METRIC must be the UTM zone that actually contains the region centre."""
    lon, lat = config.bbox_centre()
    expected = config.utm_epsg(lon, lat)
    ok = expected == config.CRS_METRIC
    print(f"  region centre : ({lon:.3f}, {lat:.3f})")
    print(f"  CRS_METRIC    : {config.CRS_METRIC}  (expected {expected})  "
          f"{'ok' if ok else 'MISMATCH — fix config.CRS_METRIC'}")
    return ok


def check_libs() -> bool:
    import geopandas, pyproj, shapely  # noqa: E401
    from pyproj import Transformer
    from shapely.geometry import Point

    print(f"  shapely {shapely.__version__} | pyproj {pyproj.__version__} | "
          f"geopandas {geopandas.__version__}")
    # always_xy=True means we pass (lon, lat) — the order GeoJSON uses.
    tf = Transformer.from_crs(config.CRS_WGS84, config.CRS_METRIC, always_xy=True)
    lon, lat = config.bbox_centre()
    x, y = tf.transform(lon, lat)
    print(f"  (lon,lat)->UTM: ({lon:.3f}, {lat:.3f}) -> ({x:.1f}, {y:.1f}) m")
    # A plausible UTM 43N easting/northing for this region.
    ok = 600_000 < x < 800_000 and 1_200_000 < y < 1_320_000
    if not ok:
        print("  !! reprojection looks wrong — check always_xy=True")
    print(f"  shapely point : {Point(lon, lat).wkt}")
    return ok


def check_mongo() -> bool:
    print(f"  uri           : {safe_uri()}")
    try:
        db = get_db()
        ping = db.command("ping")
        info = db.client.server_info()
        print(f"  ping          : {ping}")
        print(f"  server version: {info['version']}")
        print(f"  database      : {db.name}")
        existing = db.list_collection_names()
        print(f"  collections   : {existing if existing else '(none yet)'}")
        return ping.get("ok") == 1.0
    except PyMongoError as exc:
        print(f"  !! connection failed: {type(exc).__name__}: {exc}")
        print("  -> see docs/05_TROUBLESHOOTING.md (URI, password encoding, IP allowlist)")
        return False


def main() -> int:
    config.ensure_dirs()
    print(f"\nForestGeo Risk Analyser — environment check  [{config.REGION_NAME}]")
    print(f"python {sys.version.split()[0]}\n")
    print("1) libraries & CRS")
    libs_ok = check_libs()
    crs_ok = check_crs()
    print("\n2) mongodb")
    mongo_ok = check_mongo()
    print("\n3) directories")
    for d in (config.RAW_DIR, config.PROCESSED_DIR, config.OUTPUT_DIR):
        print(f"  {d.relative_to(config.ROOT)}: {'ok' if d.is_dir() else 'MISSING'}")

    all_ok = libs_ok and crs_ok and mongo_ok
    print("\n" + ("ALL CHECKS PASSED — Phase 0 done." if all_ok
                  else "SOME CHECKS FAILED — see messages above."))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
