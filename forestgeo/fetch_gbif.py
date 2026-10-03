"""Fetch wildlife occurrence records from GBIF (which aggregates iNaturalist, eBird, ...).

No API key. The search API caps out at 100k records per query; we cap well below that.
Docs: https://techdocs.gbif.org/en/openapi/v1/occurrence
"""

from __future__ import annotations

import logging
import time

import pandas as pd
import requests

from forestgeo.config import BBOX, RAW_DIR

log = logging.getLogger(__name__)

API = "https://api.gbif.org/v1/occurrence/search"
MATCH = "https://api.gbif.org/v1/species/match"
PAGE = 300  # GBIF max limit per page

# Class keys verified via /species/match (see class_key()).
CLASSES = {"Mammalia": 359, "Aves": 212, "Reptilia": 358, "Amphibia": 131}

INAT_DATASET = "50c9509d-22c7-4a22-a47d-8c48425ef4a7"  # iNaturalist Research-grade

KEEP = ["key", "species", "scientificName", "class", "order", "family",
        "decimalLatitude", "decimalLongitude", "eventDate", "year",
        "coordinateUncertaintyInMeters", "basisOfRecord", "datasetKey",
        "datasetName", "iucnRedListCategory"]


def bbox_wkt(bbox=BBOX) -> str:
    """GBIF needs a counter-clockwise WKT ring."""
    w, s, e, n = bbox
    return f"POLYGON(({w} {s},{e} {s},{e} {n},{w} {n},{w} {s}))"


def class_key(name: str) -> int | None:
    """Look up a GBIF classKey by taxon name — use to verify the CLASSES table."""
    r = requests.get(MATCH, params={"name": name}, timeout=60)
    r.raise_for_status()
    return r.json().get("classKey")


def fetch_class(class_key_: int, max_records: int = 20_000, years: str = "2015,2025",
                dataset_key: str | None = None) -> pd.DataFrame:
    """Paginate one taxonomic class inside the bbox."""
    params = {
        "geometry": bbox_wkt(),
        "classKey": class_key_,
        "hasCoordinate": "true",
        "hasGeospatialIssue": "false",
        "occurrenceStatus": "PRESENT",
        "year": years,
        "limit": PAGE,
    }
    if dataset_key:
        params["datasetKey"] = dataset_key

    rows: list[dict] = []
    offset = 0
    while offset < max_records:
        r = requests.get(API, params={**params, "offset": offset}, timeout=90)
        r.raise_for_status()
        page = r.json()
        rows += [{k: rec.get(k) for k in KEEP} for rec in page["results"]]
        if page.get("endOfRecords") or not page["results"]:
            break
        offset += PAGE
        time.sleep(0.2)
    log.info("  classKey %s: %d records (of %s matching)", class_key_, len(rows),
             page.get("count", "?"))
    return pd.DataFrame(rows, columns=KEEP)


def fetch_gbif(classes=("Mammalia", "Aves"), caps: dict[str, int] | None = None,
               save: bool = True) -> pd.DataFrame:
    """Fetch several classes and concatenate. Birds are capped — eBird makes Aves huge."""
    caps = caps or {"Aves": 15_000}
    frames = []
    for name in classes:
        log.info("GBIF class: %s", name)
        df = fetch_class(CLASSES[name], max_records=caps.get(name, 20_000))
        frames.append(df)
    out = (pd.concat(frames, ignore_index=True)
           .drop_duplicates(subset="key")
           .reset_index(drop=True))
    log.info("GBIF total: %d unique records across %s", len(out), list(classes))
    if save:
        path = RAW_DIR / "gbif_sightings.csv"
        out.to_csv(path, index=False)
        log.info("wrote %s", path)
    return out
