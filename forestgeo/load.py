"""Phase 3 — GeoDataFrame -> BSON documents -> MongoDB, with 2dsphere indexes.

Order matters: the 2dsphere index is created *before* insert_many, so MongoDB rejects
each unindexable document individually instead of accepting it and failing later. With
ordered=False one bad document does not stop the batch; rejects are logged to
outputs/rejected_<collection>.jsonl.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import math

import geopandas as gpd
import numpy as np
import pandas as pd
from pymongo.database import Database
from pymongo.errors import BulkWriteError
from shapely.geometry import mapping

from forestgeo.clean import FIELDS
from forestgeo.config import COLLECTIONS, OUTPUT_DIR

log = logging.getLogger(__name__)

# Non-spatial indexes that the later phases rely on.
EXTRA_INDEXES: dict[str, list[list[tuple[str, int]]]] = {
    "fire_hotspots": [[("acq_datetime", 1)], [("frp", -1)], [("confidence", 1)]],
    "transport": [[("kind", 1)]],
    "sightings": [[("class", 1)], [("species", 1)], [("event_date", 1)]],
    "derived_zones": [[("zone_type", 1)]],
    "protected_areas": [[("name", 1)]],
    "villages": [[("name", 1)]],
}


def _py(v):
    """Convert a pandas/numpy value to something BSON can store."""
    if v is None:
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
        # BSON dates are UTC with millisecond precision; tz-aware -> naive UTC.
        return None if pd.isna(v) else v.tz_convert("UTC").to_pydatetime() if v.tzinfo else v.to_pydatetime()
    if isinstance(v, dt.datetime):
        return v
    if v is pd.NaT:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, (np.str_,)):
        return str(v)
    return v


def gdf_to_docs(gdf: gpd.GeoDataFrame, collection: str,
                extra: dict | None = None) -> list[dict]:
    """Build one document per row: source, source_id, declared fields, geometry, ingested_at."""
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
            "geometry": mapping(geom),  # GeoJSON mapping -> [lon, lat] coordinates
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
        coll.drop()  # idempotent re-runs: replace rather than duplicate
    coll.create_index([("geometry", "2dsphere")], name="geometry_2dsphere")
    for keys in (extra_indexes if extra_indexes is not None else EXTRA_INDEXES.get(name, [])):
        coll.create_index(keys)

    inserted, rejected = 0, 0
    reject_path = OUTPUT_DIR / f"rejected_{name}.jsonl"
    reject_path.unlink(missing_ok=True)
    if docs:
        try:
            inserted = len(coll.insert_many(docs, ordered=False).inserted_ids)
        except BulkWriteError as exc:
            inserted = exc.details.get("nInserted", 0)
            errors = exc.details.get("writeErrors", [])
            rejected = len(errors)
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            with reject_path.open("w") as fh:
                for err in errors:
                    i = err.get("index", -1)
                    fh.write(json.dumps({
                        "index": i,
                        "source_id": docs[i].get("source_id") if 0 <= i < len(docs) else None,
                        "geometry_type": (docs[i].get("geometry") or {}).get("type")
                        if 0 <= i < len(docs) else None,
                        "error": err.get("errmsg", "")[:400],
                    }) + "\n")
            log.error("%s: %d documents rejected -> %s", name, rejected, reject_path)

    summary = {
        "collection": name,
        "docs_built": len(docs),
        "inserted": inserted,
        "rejected": rejected,
        "count": coll.count_documents({}),
        "indexes": [ix["name"] for ix in coll.list_indexes()],
    }
    log.info("%s: inserted %d/%d (rejected %d) | indexes %s",
             name, inserted, len(docs), rejected, summary["indexes"])
    return summary


def geometry_types(db: Database, name: str) -> dict[str, int]:
    """Census of geometry.type in a collection — proves all three GeoJSON types are present."""
    rows = db[name].aggregate([{"$group": {"_id": "$geometry.type", "n": {"$sum": 1}}},
                               {"$sort": {"n": -1}}])
    return {r["_id"]: r["n"] for r in rows}


def verify(db: Database) -> pd.DataFrame:
    """Per-collection count, geometry types and index names."""
    rows = []
    for name in COLLECTIONS:
        if name not in db.list_collection_names():
            rows.append({"collection": name, "count": 0, "geom_types": "-",
                         "has_2dsphere": False, "indexes": "-"})
            continue
        idx = [ix["name"] for ix in db[name].list_indexes()]
        rows.append({
            "collection": name,
            "count": db[name].count_documents({}),
            "geom_types": "|".join(f"{k}:{v}" for k, v in geometry_types(db, name).items()),
            "has_2dsphere": any("2dsphere" in n for n in idx),
            "indexes": ",".join(idx),
        })
    return pd.DataFrame(rows)
