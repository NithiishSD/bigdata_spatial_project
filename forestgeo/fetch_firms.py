"""Fetch NASA FIRMS VIIRS active-fire hotspots for the fire season.

Requires FIRMS_MAP_KEY in .env (free, email only):
https://firms.modaps.eosdis.nasa.gov/api/map_key/
The area API serves at most 5 days per request, so the season is fetched in 5-day chunks.
"""

from __future__ import annotations

import datetime as dt
import io
import logging
import time

import pandas as pd
import requests

from forestgeo.config import BBOX, FIRE_SEASON, FIRMS_MAP_KEY, RAW_DIR

log = logging.getLogger(__name__)

BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
STATUS = "https://firms.modaps.eosdis.nasa.gov/mapserver/mapkey_status/"
AVAILABILITY = "https://firms.modaps.eosdis.nasa.gov/api/data_availability/csv"

# Science-quality (standard processing) sources — correct for historical seasons.
# NRT sources only cover roughly the last two months.
DEFAULT_SOURCES = ("VIIRS_SNPP_SP", "VIIRS_NOAA20_SP")
MAX_DAY_SPAN = 5


def _require_key() -> str:
    if not FIRMS_MAP_KEY:
        raise RuntimeError(
            "FIRMS_MAP_KEY is not set. Request one (email only, instant) at "
            "https://firms.modaps.eosdis.nasa.gov/api/map_key/ and add it to .env"
        )
    return FIRMS_MAP_KEY


def key_status() -> str:
    """Check the MAP_KEY is live and how much of the rate limit is used. Never logs the key."""
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
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=120)
            r.raise_for_status()
            text = r.text.lstrip()
            # FIRMS reports errors as plain text with HTTP 200.
            if not text.lower().startswith("latitude"):
                raise RuntimeError(f"FIRMS returned: {text[:200]!r}")
            return pd.read_csv(io.StringIO(text))
        except Exception as exc:
            last_exc = exc
            log.warning("  %s %s: attempt %d failed (%s)", source, day, attempt + 1, exc)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"FIRMS chunk failed for {source} {day}") from last_exc


def fetch_firms(sources=DEFAULT_SOURCES, season=FIRE_SEASON, bbox=BBOX,
                save: bool = True) -> pd.DataFrame:
    """All hotspots in bbox for the season, concatenated across sources. Raw CSV columns kept."""
    key = _require_key()
    area = ",".join(str(v) for v in bbox)  # west,south,east,north
    start, end = (dt.date.fromisoformat(d) for d in season)

    frames = []
    for source in sources:
        day, n_src = start, 0
        while day <= end:
            span = min(MAX_DAY_SPAN, (end - day).days + 1)
            df = _fetch_chunk(source, area, span, day, key)
            if not df.empty:
                df["firms_source"] = source
                frames.append(df)
                n_src += len(df)
            day += dt.timedelta(days=span)
            time.sleep(1)  # stay well inside 5000 transactions / 10 min
        log.info("%s: %d hotspots %s..%s", source, n_src, start, end)

    if not frames:
        log.warning("no hotspots returned for %s..%s — try another season or source", start, end)
        out = pd.DataFrame()
    else:
        out = pd.concat(frames, ignore_index=True).drop_duplicates(
            subset=["latitude", "longitude", "acq_date", "acq_time", "satellite"]
        )
    log.info("FIRMS total: %d unique hotspots", len(out))
    if save:
        path = RAW_DIR / "firms_viirs.csv"
        out.to_csv(path, index=False)
        log.info("wrote %s", path)
    return out
