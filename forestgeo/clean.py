"""Turn raw downloads into validated, MongoDB-ready GeoDataFrames.

Every geometry leaves this module having passed geo.clean_geometry(), clipped to BBOX,
in EPSG:4326, with coordinates rounded to 6 decimals. Each cleaner returns
(GeoDataFrame, stats) where stats feeds outputs/validation_report.csv - the fixed and
dropped counts that the report cites.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

from forestgeo import geo
from forestgeo.config import (BBOX, COLLECTIONS, CRS_WGS84, GBIF_MAX_UNCERTAINTY_M,
                              PROCESSED_DIR, RAW_DIR, SIMPLIFY_TOLERANCE_M)

# Fields kept per collection, beyond source/source_id/geometry.
FIELDS: dict[str, list[str]] = {
    "villages": ["name", "place"],
    "transport": ["name", "kind", "highway", "railway", "surface", "length_km"],
    "rivers": ["name", "waterway", "length_km"],
    "protected_areas": ["name", "protect_class", "area_km2"],
    "forests": ["name", "landuse", "natural", "area_km2"],
    "water_bodies": ["name", "water", "natural", "area_km2"],
    "farmland": ["name", "landuse", "area_km2"],
    "fire_hotspots": ["acq_datetime", "acq_date", "frp", "confidence", "satellite",
                      "instrument", "daynight", "bright_ti4", "bright_ti5",
                      "firms_source"],
    "sightings": ["species", "scientific_name", "class", "order", "family",
                  "event_date", "year", "uncertainty_m", "precision", "is_roadkill",
                  "basis_of_record", "dataset_name", "iucn_category", "gbif_id"],
}

# Columns to re-parse as datetimes after a GeoJSON round-trip, because GeoJSON has
# no date type and stores them as ISO strings.
DATE_FIELDS: dict[str, list[str]] = {
    "fire_hotspots": ["acq_datetime"],
    "sightings": ["event_date"],
}

ROADKILL_DATASET = "Global Roadkill Data"

# Polygons at or below this area keep full precision instead of being simplified
# (1 ha). Below it, SIMPLIFY_TOLERANCE_M is a large fraction of the feature's size.
MIN_SIMPLIFY_AREA_KM2 = 0.01

# Degenerate slivers: 25 m2 is a 5x5 m feature - below real-world mapping precision.
MIN_FEATURE_AREA_KM2 = 0.000025

# A "protected area" below 0.1 km2 is a mapping artefact, not a reserve - typically a
# park gate or signboard traced as an area and tagged leisure=nature_reserve. Keeping
# them produces meaningless per-km2 densities in the protected-area query.
MIN_PROTECTED_AREA_KM2 = 0.1


def _stats(collection: str, rows_in: int) -> dict:
    return {"collection": collection, "rows_in": rows_in, "fixed": 0,
            "dropped_empty": 0, "dropped_family": 0, "dropped_bbox": 0,
            "dropped_duplicate": 0, "dropped_attr": 0, "rows_out": 0}


def clean_geometries(gdf: gpd.GeoDataFrame, family: str, stats: dict,
                     simplify: bool = False) -> gpd.GeoDataFrame:
    """Validate, clean, optionally simplify, and clip every geometry.

    Counts what was repaired and what was discarded, and why - those numbers are the
    evidence that the data was handled properly.
    """
    kept_geoms, kept_idx = [], []
    for idx, g in gdf.geometry.items():
        if g is None or g.is_empty:
            stats["dropped_empty"] += 1
            continue
        was_invalid = not g.is_valid
        if family == "point":
            g = geo.as_point(g)          # polygon-mapped villages -> interior point
        cleaned = geo.clean_geometry(g, family)
        if cleaned is None:
            # Unfixable, or the wrong family for this collection (e.g. a Point in
            # the transport layer, or a LineString tagged natural=water).
            stats["dropped_family"] += 1
            continue
        if was_invalid:
            stats["fixed"] += 1
        if simplify and geo.area_km2(cleaned) > MIN_SIMPLIFY_AREA_KM2:
            # Only simplify features comfortably larger than the tolerance. A 10 m
            # tolerance applied to a 15 m pond shrinks it out of existence, so small
            # polygons are kept at full precision - they have few vertices anyway.
            cleaned = geo.clean_geometry(
                geo.simplify_m(cleaned, SIMPLIFY_TOLERANCE_M), family)
            if cleaned is None:
                stats["dropped_family"] += 1
                continue
        clipped = geo.clip_to_bbox(cleaned, BBOX)
        if clipped is None:
            stats["dropped_bbox"] += 1
            continue
        # Clipping can change the geometry type: a polygon cut by the bbox edge, or a
        # line split into pieces. So clean once more.
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


# ------------------------------------------------------------------------- OSM

def _read_osm(layer: str) -> gpd.GeoDataFrame:
    path = RAW_DIR / f"osm_{layer}.geojson"
    if not path.exists():
        raise FileNotFoundError(f"{path} - run scripts/fetch_data.py first")
    gdf = gpd.read_file(path)
    gdf = gdf.set_crs(CRS_WGS84) if gdf.crs is None else gdf.to_crs(CRS_WGS84)
    # A layer whose tag spec lists several keys (protected_areas asks for both
    # boundary=* and leisure=nature_reserve) gets the same OSM element back once per
    # matching key, so Bandipur and Mudumalai each arrived twice with identical ids.
    # Deduplicating on the OSM id here fixes it for every layer at once.
    if "id" in gdf.columns:
        gdf = gdf.drop_duplicates(subset="id")
    return gdf


def _finalise(gdf: gpd.GeoDataFrame, collection: str, source: str,
              id_col: str = "id") -> gpd.GeoDataFrame:
    """Reduce to source/source_id + the declared fields + geometry."""
    gdf = gdf.copy()
    gdf["source"] = source
    gdf["source_id"] = (gdf[id_col].astype(str) if id_col in gdf.columns
                        else pd.Series(range(len(gdf)), index=gdf.index).astype(str))
    for field in FIELDS[collection]:
        if field not in gdf.columns:
            gdf[field] = None
    cols = ["source", "source_id", *FIELDS[collection], "geometry"]
    return gpd.GeoDataFrame(gdf[cols], geometry="geometry", crs=CRS_WGS84)


def clean_villages() -> tuple[gpd.GeoDataFrame, dict]:
    """OSM places -> Points. 44 of 421 are polygons; they become interior points."""
    gdf = _read_osm("villages")
    st = _stats("villages", len(gdf))
    gdf = clean_geometries(gdf, "point", st)
    if "id" in gdf.columns:
        before = len(gdf)
        gdf = gdf.drop_duplicates(subset="id")
        st["dropped_duplicate"] += before - len(gdf)
        st["rows_out"] = len(gdf)
    return _finalise(gdf, "villages", "osm"), st


def clean_transport() -> tuple[gpd.GeoDataFrame, dict]:
    """OSM highways + railways -> lines, tagged kind = road / track / railway."""
    gdf = _read_osm("transport")
    st = _stats("transport", len(gdf))
    gdf = clean_geometries(gdf, "line", st)
    no = pd.Series(False, index=gdf.index)
    is_rail = gdf["railway"].notna() if "railway" in gdf.columns else no
    is_track = (gdf["highway"] == "track") if "highway" in gdf.columns else no
    gdf["kind"] = "road"
    gdf.loc[is_track, "kind"] = "track"
    gdf.loc[is_rail, "kind"] = "railway"   # railway wins: it is the stronger signal
    gdf["length_km"] = [round(geo.length_km(g), 4) for g in gdf.geometry]
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
    floor_km2 = (MIN_PROTECTED_AREA_KM2 if layer == "protected_areas"
                 else MIN_FEATURE_AREA_KM2)
    gdf = gdf[gdf["area_km2"] > floor_km2]
    st["dropped_attr"] += before - len(gdf)
    st["rows_out"] = len(gdf)
    return _finalise(gdf, layer, "osm"), st


# ----------------------------------------------------------------------- FIRMS

def clean_fire_hotspots() -> tuple[gpd.GeoDataFrame, dict]:
    """FIRMS VIIRS CSV -> Points with a real UTC timestamp; low confidence dropped."""
    path = RAW_DIR / "firms_viirs.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} - needs FIRMS_MAP_KEY; see docs/03")
    df = pd.read_csv(path)
    st = _stats("fire_hotspots", len(df))
    if df.empty:
        empty = gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs=CRS_WGS84)
        return empty, st

    # acq_time is HHMM in UTC stored as an integer: 745 -> 07:45. Zero-pad to 4.
    df["acq_datetime"] = pd.to_datetime(
        df["acq_date"].astype(str) + " "
        + df["acq_time"].astype(int).astype(str).str.zfill(4),
        format="%Y-%m-%d %H%M", utc=True, errors="coerce")
    before = len(df)
    df = df[df["acq_datetime"].notna()]
    st["dropped_attr"] += before - len(df)

    # VIIRS confidence is l/n/h. Low-confidence detections are largely noise.
    if "confidence" in df.columns:
        before = len(df)
        df = df[df["confidence"].astype(str).str.lower() != "l"]
        st["dropped_attr"] += before - len(df)

    # FIRMS records carry no ID, so identity is position + time + satellite.
    before = len(df)
    df = df.drop_duplicates(subset=["latitude", "longitude", "acq_date",
                                    "acq_time", "satellite"])
    st["dropped_duplicate"] += before - len(df)

    df["source_id"] = (df["latitude"].round(5).astype(str) + "_"
                       + df["longitude"].round(5).astype(str) + "_"
                       + df["acq_datetime"].dt.strftime("%Y%m%dT%H%M"))
    gdf = gpd.GeoDataFrame(
        df, geometry=gpd.points_from_xy(df["longitude"], df["latitude"]),
        crs=CRS_WGS84)
    gdf = clean_geometries(gdf, "point", st)
    return _finalise(gdf, "fire_hotspots", "firms", id_col="source_id"), st


# ------------------------------------------------------------------------ GBIF

def clean_sightings() -> tuple[gpd.GeoDataFrame, dict]:
    """GBIF occurrences -> Points, with a three-tier positional-accuracy policy.

    Records are NOT filtered on accuracy. 24.7% of them are obscured to ~31 km by
    iNaturalist to protect threatened species, and those are exactly the flagship
    animals (170 elephant, 48 tiger, 16 leopard). Dropping them would leave a
    collection of squirrels. Instead every record is tagged:

        precision = "precise" (<= 1 km) | "unknown" (null) | "coarse" (> 1 km)

    so distance queries can select the trustworthy subset while the map can still
    show obscured records in a clearly labelled layer. is_roadkill is flagged for the
    same reason: 479 precise records come from a roadkill dataset, which would make
    any "% of sightings near a road" statistic circular.
    """
    path = RAW_DIR / "gbif_sightings.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} - run scripts/fetch_data.py --only gbif")
    df = pd.read_csv(path)
    st = _stats("sightings", len(df))
    if df.empty:
        empty = gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs=CRS_WGS84)
        return empty, st

    before = len(df)
    df = df.drop_duplicates(subset="key")
    st["dropped_duplicate"] += before - len(df)

    before = len(df)
    df = df[df["decimalLatitude"].notna() & df["decimalLongitude"].notna()]
    df = df[df["species"].notna()]
    st["dropped_attr"] += before - len(df)

    df = df.rename(columns={
        "key": "gbif_id", "scientificName": "scientific_name",
        "eventDate": "event_date", "coordinateUncertaintyInMeters": "uncertainty_m",
        "basisOfRecord": "basis_of_record", "datasetName": "dataset_name",
        "iucnRedListCategory": "iucn_category",
    })

    unc = pd.to_numeric(df["uncertainty_m"], errors="coerce")
    df["uncertainty_m"] = unc
    df["precision"] = "coarse"
    df.loc[unc <= GBIF_MAX_UNCERTAINTY_M, "precision"] = "precise"
    df.loc[unc.isna(), "precision"] = "unknown"
    df["is_roadkill"] = (df["dataset_name"].fillna("")
                         .str.startswith(ROADKILL_DATASET))

    # eventDate arrives in mixed formats (2025-01-04T16:20 and ...T11:41:20).
    df["event_date"] = pd.to_datetime(df["event_date"], errors="coerce",
                                      utc=True, format="mixed")
    df["gbif_id"] = df["gbif_id"].astype(str)

    gdf = gpd.GeoDataFrame(
        df, geometry=gpd.points_from_xy(df["decimalLongitude"], df["decimalLatitude"]),
        crs=CRS_WGS84)
    gdf = clean_geometries(gdf, "point", st)
    return _finalise(gdf, "sightings", "gbif", id_col="gbif_id"), st


# -------------------------------------------------------------------- pipeline

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
    """Write data/processed/<collection>.geojson. Datetimes become ISO strings."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    path = PROCESSED_DIR / f"{collection}.geojson"
    out = gdf.copy()
    for col in DATE_FIELDS.get(collection, []):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], errors="coerce", utc=True).map(
                lambda v: None if pd.isna(v) else v.isoformat())
    path.unlink(missing_ok=True)      # idempotent: replace, never append
    out.to_file(path, driver="GeoJSON")
    return str(path)


def read_processed(collection: str) -> gpd.GeoDataFrame:
    """Read a processed layer back, restoring datetime columns."""
    path = PROCESSED_DIR / f"{collection}.geojson"
    if not path.exists():
        raise FileNotFoundError(f"{path} - run scripts/clean_validate.py first")
    gdf = gpd.read_file(path)
    for col in DATE_FIELDS.get(collection, []):
        if col in gdf.columns:
            gdf[col] = pd.to_datetime(gdf[col], errors="coerce", utc=True,
                                      format="mixed")
    return gdf


def all_valid(gdf: gpd.GeoDataFrame) -> bool:
    """Phase 2's definition of done: 100% of processed geometries are valid."""
    return bool(gdf.empty or gdf.geometry.is_valid.all())


def expected_family(collection: str) -> str:
    return COLLECTIONS[collection]
