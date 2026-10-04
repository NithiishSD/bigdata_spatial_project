"""GeoDataFrame -> BSON documents -> MongoDB, with 2dsphere indexes.

BSON = Binary JSON, MongoDB's storage format. It adds types JSON lacks - notably
Date - which is why fire timestamps can be compared and sorted as real dates.

Order matters: the 2dsphere index is created BEFORE insert_many, so MongoDB rejects
each unindexable document individually instead of accepting it and failing later.
With ordered=False one bad document does not abort the batch; rejects are written to
outputs/rejected_<collection>.jsonl.
"""

from __future__ import annotations

import datetime as dt
import json
import math

import geopandas as gpd
import numpy as np
import pandas as pd
from pymongo.database import Database
from pymongo.errors import BulkWriteError
from shapely.geometry import mapping

from forestgeo.clean import FIELDS
from forestgeo.config import OUTPUT_DIR

# Non-spatial indexes the later phases rely on. A list of (field, direction) pairs;
# 1 = ascending, -1 = descending. Direction matters for sorting, not for equality.
EXTRA_INDEXES: dict[str, list[list[tuple[str, int]]]] = {
    "fire_hotspots": [[("acq_datetime", 1)], [("frp", -1)], [("confidence", 1)]],
    "transport": [[("kind", 1)]],
    "sightings": [[("class", 1)], [("species", 1)], [("precision", 1)],
                  [("is_roadkill", 1)]],
    "derived_zones": [[("zone_type", 1)]],
    "protected_areas": [[("name", 1)]],
    "villages": [[("name", 1)]],
}


def _py(v):
    """Convert a pandas/numpy value into something BSON can store.

    PyMongo cannot serialise numpy scalars (np.int64, np.float64) or pandas NaT, and
    NaN is a valid float that would be stored as a number rather than a missing value.
    """
    if v is None or v is pd.NaT:
        return None
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        f = float(v)
        return None if math.isnan(f) else f
    if isinstance(v, float):
        return None if math.isnan(v) else v
    if isinstance(v, pd.Timestamp):
        if pd.isna(v):
            return None
        # BSON dates are UTC with millisecond precision.
        return v.tz_convert("UTC").to_pydatetime() if v.tzinfo else v.to_pydatetime()
    if isinstance(v, dt.datetime):
        return v
    if isinstance(v, np.str_):
        return str(v)
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass          # arrays and other non-scalars reach here; pass them through
    return v


def gdf_to_docs(gdf: gpd.GeoDataFrame, collection: str,
                extra: dict | None = None) -> list[dict]:
    """One document per row: source, source_id, declared fields, geometry, ingested_at."""
    now = dt.datetime.now(dt.timezone.utc)
    fields = FIELDS.get(collection, [])
    docs = []
    for rec in gdf.to_dict("records"):
        geom = rec.get("geometry")
        if geom is None or geom.is_empty:
            continue
        doc = {
            "source": _py(rec.get("source")),
            "source_id": _py(rec.get("source_id")),
            **{f: _py(rec.get(f)) for f in fields},
            # mapping() produces a GeoJSON dict with [longitude, latitude] coordinates.
            "geometry": mapping(geom),
            "ingested_at": now,
        }
        if extra:
            doc.update(extra)
        docs.append(doc)
    return docs


def load_collection(db: Database, name: str, docs: list[dict],
                    extra_indexes: list | None = None, drop: bool = True) -> dict:
    """Drop, index, then bulk-insert. Returns a summary dict."""
    coll = db[name]
    if drop:
        coll.drop()      # idempotent re-runs: replace rather than duplicate
    coll.create_index([("geometry", "2dsphere")], name="geometry_2dsphere")
    for keys in (extra_indexes if extra_indexes is not None
                 else EXTRA_INDEXES.get(name, [])):
        coll.create_index(keys)

    inserted, rejected = 0, 0
    reject_path = OUTPUT_DIR / f"rejected_{name}.jsonl"
    reject_path.unlink(missing_ok=True)
    if docs:
        try:
            inserted = len(coll.insert_many(docs, ordered=False).inserted_ids)
        except BulkWriteError as exc:
            # ordered=False means the good documents were still inserted.
            inserted = exc.details.get("nInserted", 0)
            errors = exc.details.get("writeErrors", [])
            rejected = len(errors)
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            with reject_path.open("w") as fh:
                for err in errors:
                    i = err.get("index", -1)
                    doc = docs[i] if 0 <= i < len(docs) else {}
                    fh.write(json.dumps({
                        "index": i,
                        "source_id": doc.get("source_id"),
                        "geometry_type": (doc.get("geometry") or {}).get("type"),
                        "error": err.get("errmsg", "")[:400],
                    }) + "\n")
            print(f"  !! {name}: {rejected} documents rejected -> {reject_path}")

    return {
        "collection": name,
        "docs_built": len(docs),
        "inserted": inserted,
        "rejected": rejected,
        "count": coll.count_documents({}),
        "indexes": [ix["name"] for ix in coll.list_indexes()],
    }
