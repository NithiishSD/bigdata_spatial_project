"""Phase 2 — turn raw downloads into validated, MongoDB-ready GeoDataFrames.

Every geometry leaves this module having passed geo.clean_geometry(), clipped to BBOX,
in EPSG:4326, with coordinates rounded to 6 decimals. Each function returns
(GeoDataFrame, stats) where stats feeds outputs/validation_report.csv.
"""

from __future__ import annotations

import logging

import geopandas as gpd
import pandas as pd

from forestgeo import geo
from forestgeo.config import (BBOX, COLLECTIONS, CRS_WGS84, GBIF_MAX_UNCERTAINTY_M,
                              PROCESSED_DIR, RAW_DIR, SIMPLIFY_TOLERANCE_M)

log = logging.getLogger(__name__)

# Columns kept per collection, over and above geometry/source/source_id.
FIELDS: dict[str, list[str]] = {
    "villages": ["name", "place"],
    "transport": ["name", "kind", "highway", "railway", "surface", "length_km"],
    "rivers": ["name", "waterway", "length_km"],
    "protected_areas": ["name", "protect_class", "protection_title", "area_km2"],
    "forests": ["name", "landuse", "natural", "area_km2"],
    "water_bodies": ["name", "water", "natural", "area_km2"],
    "farmland": ["name", "landuse", "area_km2"],
    "fire_hotspots": ["acq_datetime", "acq_date", "frp", "confidence", "satellite",
                      "instrument", "daynight", "bright_ti4", "bright_ti5", "firms_source"],
    "sightings": ["species", "scientific_name", "class", "order", "family", "event_date",
                  "year", "uncertainty_m", "basis_of_record", "dataset_name",
                  "iucn_category", "gbif_id"],
}

# Columns that must be re-parsed as datetimes after a GeoJSON round-trip
# (GeoJSON has no date type, so they are stored as ISO strings).
DATE_FIELDS: dict[str, list[str]] = {
    "fire_hotspots": ["acq_datetime"],
    "sightings": ["event_date"],
}


def _stats(collection: str, rows_in: int) -> dict:
    return {"collection": collection, "rows_in": rows_in, "fixed": 0,
            "dropped_invalid": 0, "dropped_family": 0, "dropped_bbox": 0,
            "dropped_duplicate": 0, "dropped_attr": 0, "rows_out": 0}


def clean_geometries(gdf: gpd.GeoDataFrame, family: str, stats: dict,
                     simplify: bool = False) -> gpd.GeoDataFrame:
    """Validate/clean/clip every geometry, counting what was fixed and dropped."""
    kept_geoms, kept_idx = [], []
    for idx, g in gdf.geometry.items():
        if g is None or g.is_empty:
            stats["dropped_invalid"] += 1
            continue
        was_invalid = not g.is_valid
        if family == "point":
            g = geo.as_point(g)
        cleaned = geo.clean_geometry(g, family)
        if cleaned is None:
            # Either unfixable, or the wrong geometry family for this collection
            # (e.g. a highway=bus_stop node inside the transport layer).
            stats["dropped_family"] += 1
            continue
        if was_invalid:
            stats["fixed"] += 1
        if simplify:
            cleaned = geo.clean_geometry(
                geo.simplify_m(cleaned, SIMPLIFY_TOLERANCE_M), family)
            if cleaned is None:
                stats["dropped_family"] += 1
                continue
        clipped = geo.clip_to_bbox(cleaned, BBOX)
        if clipped is None:
            stats["dropped_bbox"] += 1
            continue
        # Clipping can change the geometry type (a polygon cut by the bbox edge, or a
        # line clipped into pieces), so clean once more.
        final = geo.clean_geometry(clipped, family)
        if final is None:
            stats["dropped_bbox"] += 1
            continue
        kept_geoms.append(final)
        kept_idx.append(idx)

    out = gdf.loc[kept_idx].copy()
    out["geometry"] = kept_geoms
    out = gpd.GeoDataFrame(out, geometry="geometry", crs=CRS_WGS84)
    stats["rows_out"] = len(out)
    return out


# --------------------------------------------------------------------------- OSM

def _read_osm(layer: str) -> gpd.GeoDataFrame:
    path = RAW_DIR / f"osm_{layer}.geojson"
    if not path.exists():
        raise FileNotFoundError(f"{path} — run scripts/01_fetch_data.py first")
    gdf = gpd.read_file(path)
    if gdf.crs is None:
        gdf = gdf.set_crs(CRS_WGS84)
    return gdf.to_crs(CRS_WGS84)


def _finalise(gdf: gpd.GeoDataFrame, collection: str, source: str,
              id_col: str = "id") -> gpd.GeoDataFrame:
    """Keep only the declared fields plus source/source_id/geometry."""
    gdf = gdf.copy()
    gdf["source"] = source
    gdf["source_id"] = (gdf[id_col].astype(str) if id_col in gdf.columns
                        else pd.Series(range(len(gdf)), index=gdf.index).astype(str))
    for f in FIELDS[collection]:
        if f not in gdf.columns:
            gdf[f] = None
    cols = ["source", "source_id", *FIELDS[collection], "geometry"]
    return gpd.GeoDataFrame(gdf[cols], geometry="geometry", crs=CRS_WGS84)


def clean_villages() -> tuple[gpd.GeoDataFrame, dict]:
    """OSM places -> Points. Polygon-mapped villages become a representative interior point."""
    gdf = _read_osm("villages")
    st = _stats("villages", len(gdf))
    gdf = clean_geometries(gdf, "point", st)
    before = len(gdf)
    gdf = gdf.drop_duplicates(subset="id") if "id" in gdf.columns else gdf
    st["dropped_duplicate"] += before - len(gdf)
    st["rows_out"] = len(gdf)
    return _finalise(gdf, "villages", "osm"), st


def clean_transport() -> tuple[gpd.GeoDataFrame, dict]:
    """OSM highways + railways -> LineStrings, tagged with kind (road/track/railway)."""
    gdf = _read_osm("transport")
    st = _stats("transport", len(gdf))
    gdf = clean_geometries(gdf, "line", st)
    rail = gdf["railway"].notna() if "railway" in gdf.columns else pd.Series(False, index=gdf.index)
    track = (gdf["highway"] == "track") if "highway" in gdf.columns else pd.Series(False, index=gdf.index)
    gdf["kind"] = "road"
    gdf.loc[track, "kind"] = "track"
    gdf.loc[rail, "kind"] = "railway"
    gdf["length_km"] = [round(geo.length_km(g), 4) for g in gdf.geometry]
    log.info("transport kinds: %s", dict(gdf["kind"].value_counts()))
    return _finalise(gdf, "transport", "osm"), st


def clean_rivers() -> tuple[gpd.GeoDataFrame, dict]:
    gdf = _read_osm("rivers")
    st = _stats("rivers", len(gdf))
    gdf = clean_geometries(gdf, "line", st)
    gdf["length_km"] = [round(geo.length_km(g), 4) for g in gdf.geometry]
    return _finalise(gdf, "rivers", "osm"), st


def clean_polygon_layer(layer: str) -> tuple[gpd.GeoDataFrame, dict]:
    """Shared path for protected_areas / forests / water_bodies / farmland."""
    gdf = _read_osm(layer)
    st = _stats(layer, len(gdf))
    gdf = clean_geometries(gdf, "polygon", st, simplify=True)
    gdf["area_km2"] = [round(geo.area_km2(g), 4) for g in gdf.geometry]
    before = len(gdf)
    gdf = gdf[gdf["area_km2"] > 0.0001]  # drop slivers smaller than 100 m^2
    st["dropped_attr"] += before - len(gdf)
    st["rows_out"] = len(gdf)
    log.info("%s: total area %.1f km2", layer, gdf["area_km2"].sum())
    return _finalise(gdf, layer, "osm"), st


# ------------------------------------------------------------------------- FIRMS

def clean_fire_hotspots() -> tuple[gpd.GeoDataFrame, dict]:
    """FIRMS VIIRS CSV -> Points with a real UTC datetime; low-confidence rows dropped."""
    path = RAW_DIR / "firms_viirs.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} — needs FIRMS_MAP_KEY; see docs/03_DATA_ACQUISITION.md §2")
    df = pd.read_csv(path)
    st = _stats("fire_hotspots", len(df))
    if df.empty:
        return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=CRS_WGS84), st

    # acq_time is HHMM in UTC stored as an integer: 745 -> 07:45.
    df["acq_datetime"] = pd.to_datetime(
        df["acq_date"].astype(str) + " " + df["acq_time"].astype(int).astype(str).str.zfill(4),
        format="%Y-%m-%d %H%M", utc=True, errors="coerce")
    before = len(df)
    df = df[df["acq_datetime"].notna()]
    st["dropped_attr"] += before - len(df)

    # VIIRS confidence is l/n/h. Low-confidence detections are mostly noise.
    if "confidence" in df.columns:
        before = len(df)
        df = df[df["confidence"].astype(str).str.lower() != "l"]
        st["dropped_attr"] += before - len(df)

    before = len(df)
    df = df.drop_duplicates(subset=["latitude", "longitude", "acq_date", "acq_time", "satellite"])
    st["dropped_duplicate"] += before - len(df)

    df["source_id"] = (df["latitude"].round(5).astype(str) + "_"
                       + df["longitude"].round(5).astype(str) + "_"
                       + df["acq_datetime"].dt.strftime("%Y%m%dT%H%M"))
    gdf = gpd.GeoDataFrame(
        df, geometry=gpd.points_from_xy(df["longitude"], df["latitude"]), crs=CRS_WGS84)
    gdf = clean_geometries(gdf, "point", st)
    log.info("hotspots: %d  frp max=%.1f MW  span %s..%s", len(gdf),
             gdf["frp"].max() if len(gdf) else 0,
             gdf["acq_datetime"].min() if len(gdf) else "-",
             gdf["acq_datetime"].max() if len(gdf) else "-")
    return _finalise(gdf, "fire_hotspots", "firms", id_col="source_id"), st


# -------------------------------------------------------------------------- GBIF

def clean_sightings() -> tuple[gpd.GeoDataFrame, dict]:
    """GBIF occurrences -> Points, dropping imprecise coordinates and duplicates."""
    path = RAW_DIR / "gbif_sightings.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} — run scripts/01_fetch_data.py --only gbif")
    df = pd.read_csv(path)
    st = _stats("sightings", len(df))
    if df.empty:
        return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=CRS_WGS84), st

    before = len(df)
    df = df.drop_duplicates(subset="key")
    st["dropped_duplicate"] += before - len(df)

    before = len(df)
    df = df[df["decimalLatitude"].notna() & df["decimalLongitude"].notna()]
    # Keep records whose stated accuracy is good enough to compare against a 500 m
    # road buffer. Missing uncertainty is kept (most iNaturalist records omit it).
    unc = pd.to_numeric(df["coordinateUncertaintyInMeters"], errors="coerce")
    df = df[unc.isna() | (unc <= GBIF_MAX_UNCERTAINTY_M)]
    df = df[df["species"].notna()]
    st["dropped_attr"] += before - len(df)

    df = df.rename(columns={
        "key": "gbif_id", "scientificName": "scientific_name", "eventDate": "event_date",
        "coordinateUncertaintyInMeters": "uncertainty_m", "basisOfRecord": "basis_of_record",
        "datasetName": "dataset_name", "iucnRedListCategory": "iucn_category",
    })
    df["event_date"] = pd.to_datetime(df["event_date"], errors="coerce", utc=True, format="mixed")
    df["gbif_id"] = df["gbif_id"].astype(str)

    gdf = gpd.GeoDataFrame(
        df, geometry=gpd.points_from_xy(df["decimalLongitude"], df["decimalLatitude"]),
        crs=CRS_WGS84)
    gdf = clean_geometries(gdf, "point", st)
    log.info("sightings: %d records | %d species | classes %s", len(gdf),
             gdf["species"].nunique(), dict(gdf["class"].value_counts()))
    return _finalise(gdf, "sightings", "gbif", id_col="gbif_id"), st


# ---------------------------------------------------------------------- pipeline

CLEANERS = {
    "villages": clean_villages,
    "transport": clean_transport,
    "rivers": clean_rivers,
    "protected_areas": lambda: clean_polygon_layer("protected_areas"),
    "forests": lambda: clean_polygon_layer("forests"),
    "water_bodies": lambda: clean_polygon_layer("water_bodies"),
    "farmland": lambda: clean_polygon_layer("farmland"),
    "fire_hotspots": clean_fire_hotspots,
    "sightings": clean_sightings,
}


def write_processed(collection: str, gdf: gpd.GeoDataFrame) -> str:
    """Write data/processed/<collection>.geojson (datetimes become ISO strings)."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    path = PROCESSED_DIR / f"{collection}.geojson"
    out = gdf.copy()
    for col in DATE_FIELDS.get(collection, []):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], errors="coerce", utc=True).map(
                lambda v: None if pd.isna(v) else v.isoformat())
    if path.exists():
        path.unlink()  # idempotent: replace, never append
    out.to_file(path, driver="GeoJSON")
    return str(path)


def read_processed(collection: str) -> gpd.GeoDataFrame:
    """Read a processed layer back, restoring datetime columns."""
    path = PROCESSED_DIR / f"{collection}.geojson"
    if not path.exists():
        raise FileNotFoundError(f"{path} — run scripts/02_clean_validate.py first")
    gdf = gpd.read_file(path)
    for col in DATE_FIELDS.get(collection, []):
        if col in gdf.columns:
            gdf[col] = pd.to_datetime(gdf[col], errors="coerce", utc=True, format="mixed")
    return gdf


def all_valid(gdf: gpd.GeoDataFrame) -> bool:
    """The Phase 2 Definition of Done: 100% of processed geometries are valid."""
    return bool(gdf.empty or gdf.geometry.is_valid.all())


def expected_family(collection: str) -> str:
    return COLLECTIONS[collection]
