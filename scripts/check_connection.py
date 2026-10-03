"""
 prove the environment works before you spend an hour downloading data. 
 It checks the three things that can silently ruin everything: reprojection, CRS choice, and the database.
 """

from pymongo.errors import PyMongoError   #to catch any py-mondo related errors
from pyproj import Transformer

from forestgeo import config
from forestgeo.db import get_db, safe_uri



#check teh project is sane thsi is a verification about teh crs utm for given lon lang in bbox

def check_reprojection() -> bool:
    """Catch a swapped lon/lat: the UTM result must land in zone 43N's plausible range."""
    tf = Transformer.from_crs(config.CRS_WGS84, config.CRS_METRIC, always_xy=True)#true for thsi argument makes pyproj to read as lon,lat since transform is lat,log
    lon, lat = config.bbox_centre()
    x, y = tf.transform(lon, lat)#to do this need always_xy=true
    ok = 600_000 < x < 800_000 and 1_200_000 < y < 1_320_000 #numbers for nilgiris location
    print(f"  (lon,lat)->UTM : ({lon:.3f}, {lat:.3f}) -> ({x:.0f}, {y:.0f}) m"
          f"  {'ok' if ok else 'SWAPPED?'}")
    return ok

#chck crs is right
def check_crs() -> bool:
    """CRS_METRIC must be the UTM zone that actually contains the region centre."""
    lon, lat = config.bbox_centre()
    expected = config.utm_epsg(lon, lat)
    ok = expected == config.CRS_METRIC
    print(f"  CRS_METRIC     : {config.CRS_METRIC} (expected {expected})"
          f"  {'ok' if ok else 'MISMATCH — fix config.CRS_METRIC'}")
    return ok




#mongo reachablity

def check_mongo() -> bool:
    print(f"  uri            : {safe_uri()}")
    try:
        db = get_db()
        ping = db.command("ping")
        print(f"  ping           : {ping}")
        print(f"  server version : {db.client.server_info()['version']}")
        print(f"  collections    : {db.list_collection_names() or '(none yet)'}")
        return ping.get("ok") == 1.0
    except PyMongoError as exc:
        print(f"  !! {type(exc).__name__}: {exc}")
        print("  -> see docs/05_TROUBLESHOOTING.md (URI, password encoding, IP allowlist)")
        return False



def main() -> int:
    print(f"\nForestGeo environment check — {config.REGION_NAME}\n")

    print("1) CRS")
    repro_ok = check_reprojection()
    crs_ok = check_crs()

    print("2) MongoDB")
    mongo_ok = check_mongo()

    print("3) folders")
    for d in (config.RAW_DIR, config.PROCESSED_DIR, config.OUTPUT_DIR):
        d.mkdir(parents=True, exist_ok=True)
        print(f"  {d.relative_to(config.ROOT)}")

    ok = repro_ok and crs_ok and mongo_ok
    print("\n" + ("ALL CHECKS PASSED — Phase 0 done." if ok else "CHECKS FAILED — see above."))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main()) #this is usefull when multiple script are run sequenceally and then return 1 if sucessful so the next command runs only this succeed
