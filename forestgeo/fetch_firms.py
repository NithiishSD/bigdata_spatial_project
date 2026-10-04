"""
 FIRMS (Fire Information for Resource Management System) serves satellite fire detections. 
 VIIRS is the sensor, flying on Suomi-NPP and NOAA-20, with 375 m pixels. 
 Critically: a "hotspot" is a thermal anomaly detection, 
 not a confirmed fire — it's the satellite reporting that a pixel was unusually hot. That distinction belongs in your report.
"""

"""Fetch NASA FIRMS VIIRS active-fire hotspots. Requires FIRMS_MAP_KEY in .env."""

import datetime as dt
import io
import time

import pandas as pd
import requests

from forestgeo.config import BBOX, FIRE_SEASON, FIRMS_MAP_KEY, RAW_DIR

BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
STATUS = "https://firms.modaps.eosdis.nasa.gov/mapserver/mapkey_status/"
AVAILABILITY = "https://firms.modaps.eosdis.nasa.gov/api/data_availability/csv"

SOURCES = ("VIIRS_SNPP_SP", "VIIRS_NOAA20_SP")
MAX_DAYS = 5          # the area API serves at most 5 days per request


def _require_key() -> str:
    if not FIRMS_MAP_KEY:
        raise RuntimeError(
            "FIRMS_MAP_KEY is not set. Request one (email only, instant) at "
            "https://firms.modaps.eosdis.nasa.gov/api/map_key/ and add it to .env"
        )
    return FIRMS_MAP_KEY


def key_status() -> str:
    """Confirm the key works and see how much of the rate limit is used."""
    r = requests.get(STATUS, params={"MAP_KEY": _require_key()}, timeout=60)
    r.raise_for_status()
    return r.text.strip()


def data_availability() -> pd.DataFrame:
    """Which date range each FIRMS source actually covers — check before a historical fetch."""
    r = requests.get(f"{AVAILABILITY}/{_require_key()}/all", timeout=60)
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text))



def _fetch_chunk(source: str, area: str, span: int, day: dt.date, key: str) -> pd.DataFrame:
    url = f"{BASE}/{key}/{source}/{area}/{span}/{day:%Y-%m-%d}"
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    text = r.text.lstrip()
    # FIRMS reports errors as plain text with HTTP 200 — so status code is not enough.
    if not text.lower().startswith("latitude"):
        raise RuntimeError(f"FIRMS returned: {text[:200]!r}")
    return pd.read_csv(io.StringIO(text))


def fetch_firms(sources=SOURCES, season=FIRE_SEASON, bbox=BBOX, save=True) -> pd.DataFrame:
    """All hotspots in bbox for the season, across sources. Raw CSV columns kept."""
    key = _require_key()
    area = ",".join(str(v) for v in bbox)          # west,south,east,north
    start, end = (dt.date.fromisoformat(d) for d in season)

    frames = []
    for source in sources:
        day, n = start, 0
        while day <= end:
            span = min(MAX_DAYS, (end - day).days + 1)
            df = _fetch_chunk(source, area, span, day, key)
            if not df.empty:
                df["firms_source"] = source
                frames.append(df)
                n += len(df)
            day += dt.timedelta(days=span)
            time.sleep(1)
        print(f"{source}: {n} hotspots {start}..{end}")

    out = (pd.concat(frames, ignore_index=True)
             .drop_duplicates(subset=["latitude", "longitude", "acq_date",
                                      "acq_time", "satellite"])
           ) if frames else pd.DataFrame()
    print(f"FIRMS total: {len(out)} unique hotspots")
    if save:
        out.to_csv(RAW_DIR / "firms_viirs.csv", index=False)
    return out