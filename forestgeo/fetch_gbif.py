"""Fetch wildlife occurrence records from GBIF Global Biodiversity Information Facility(aggregates iNaturalist, eBird, museums)."""

import time

import pandas as pd
import requests

from forestgeo.config import BBOX, RAW_DIR

API = "https://api.gbif.org/v1/occurrence/search"
PAGE = 300          # GBIF's maximum limit per request

CLASSES = {"Mammalia": 359, "Aves": 212}   # verified via /species/match

KEEP = ["key", "species", "scientificName", "class", "order", "family",
        "decimalLatitude", "decimalLongitude", "eventDate", "year",
        "coordinateUncertaintyInMeters", "basisOfRecord", "datasetKey",
        "datasetName", "iucnRedListCategory"] #these are the field which we need for our project teh request comes with more than 100 field which is useless


#bounding box as wkt(well known text )so that we can pass this to gbif  with coordinates
def bbox_wkt(bbox=BBOX) -> str:
    """GBIF needs a counter-clockwise WKT ring."""
    w, s, e, n = bbox
    return f"POLYGON(({w} {s},{e} {s},{e} {n},{w} {n},{w} {s}))"


#paginating one class

def fetch_class(class_key: int, max_records: int = 20_000) -> pd.DataFrame:
    """Page through all occurrences of one taxonomic class inside the bbox."""
    params = {
        "geometry": bbox_wkt(),
        "classKey": class_key,
        "hasCoordinate": "true",
        "hasGeospatialIssue": "false",
        "occurrenceStatus": "PRESENT",
        "year": "2015,2025",
        "limit": PAGE,
    }
    rows, offset = [], 0
    while offset < max_records:
        page = requests.get(API, params={**params, "offset": offset}, timeout=90).json()
        rows += [{k: rec.get(k) for k in KEEP} for rec in page["results"]]
        print(f"  offset {offset:>6} -> {len(rows):>6} rows (of {page['count']:,} matching)")
        if page["endOfRecords"] or not page["results"]:
            break
        offset += PAGE
        time.sleep(0.2)
    return pd.DataFrame(rows, columns=KEEP)


#we are combining classes here we fetch the gbif data of mamalas and store it in raw data folder for future use
def fetch_gbif(classes=("Mammalia",), caps=None, save=True) -> pd.DataFrame:
    """Fetch the given classes and concatenate. Default: mammals only."""
    caps = caps or {}
    frames = [fetch_class(CLASSES[c], caps.get(c, 20_000)) for c in classes]
    out = pd.concat(frames, ignore_index=True).drop_duplicates(subset="key")
    print(f"GBIF total: {len(out)} unique records")
    if save:
        out.to_csv(RAW_DIR / "gbif_sightings.csv", index=False)
    return out

"""
- The counter-clockwise ring. Reverse it and GBIF returns the whole globe minus your box — millions of irrelevant records, no error. It's the same class of silent failure as the lon/lat swap.
- rec.get(k) not rec[k]. GBIF omits absent fields rather than sending null, so bracket access raises KeyError on the first record missing a species name.
- caps=None then caps or {}. A mutable default (caps={}) is created once at function definition and shared by every call — a genuine Python trap worth knowing beyond this project.
"""