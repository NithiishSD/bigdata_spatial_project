#!/usr/bin/env python
"""Phase 9 - generate the static figures the report needs, straight from the database.

Produces docs/img/fig1..fig4.png. The interactive map is for the demo; a printed report
needs static images, and generating them from the data means they can never drift out of
step with the numbers in the text.

Run:  python scripts/make_figures.py
"""

from __future__ import annotations

import matplotlib
matplotlib.use("Agg")                  # headless: no display required

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
import shapely

from forestgeo import config
from forestgeo.db import get_db
from forestgeo.geo import bbox_polygon

IMG = config.ROOT / "docs" / "img"


def _gdf(db, collection, query=None) -> gpd.GeoDataFrame:
    """Read a collection into a GeoDataFrame for plotting."""
    docs = list(db[collection].find(query or {}))
    if not docs:
        return gpd.GeoDataFrame({"geometry": []}, geometry="geometry",
                                crs=config.CRS_WGS84)
    geoms = [shapely.geometry.shape(d.pop("geometry")) for d in docs]
    return gpd.GeoDataFrame(docs, geometry=geoms, crs=config.CRS_WGS84)


def _frame(ax, title):
    west, south, east, north = config.BBOX
    ax.set_xlim(west, east)
    ax.set_ylim(south, north)
    ax.set_title(title, fontsize=10)
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.grid(alpha=0.25, linewidth=0.4)


def fig_study_area(db):
    """Figure 1 - where the study area is and what is in it."""
    fig, ax = plt.subplots(figsize=(8, 5.6))
    _gdf(db, "forests").plot(ax=ax, color="#2e7d32", alpha=0.35,
                             label="forest (3,521 km²)")
    _gdf(db, "protected_areas").plot(ax=ax, facecolor="none", edgecolor="#1b5e20",
                                     linewidth=1.4, label="protected areas (9)")
    _gdf(db, "water_bodies").plot(ax=ax, color="#1565c0", alpha=0.7)
    _gdf(db, "transport", {"highway": {"$in": ["primary", "secondary", "trunk"]}}) \
        .plot(ax=ax, color="#555", linewidth=0.5, alpha=0.7)
    _gdf(db, "villages").plot(ax=ax, color="#b71c1c", markersize=5,
                              label="villages (421)")
    gpd.GeoSeries([bbox_polygon()], crs=config.CRS_WGS84).boundary.plot(
        ax=ax, color="black", linewidth=1.2, linestyle="--")
    _frame(ax, f"{config.REGION_NAME} — study area, bbox {config.BBOX}")
    ax.legend(fontsize=8, loc="lower left")
    fig.tight_layout()
    fig.savefig(IMG / "fig1_study_area.png", dpi=150)
    plt.close(fig)


def fig_union_before_after(db):
    """Figure 2 - the union: 119 forest polygons become 23 habitat blocks."""
    forests = _gdf(db, "forests")
    block = _gdf(db, "derived_zones", {"zone_type": "habitat_block"})
    fig, axes = plt.subplots(1, 2, figsize=(11, 5))
    forests.plot(ax=axes[0], color="#2e7d32", edgecolor="white", linewidth=0.3)
    _frame(axes[0], f"BEFORE — {len(forests)} separate forest polygons")
    block.plot(ax=axes[1], color="#004d40", alpha=0.85)
    n_parts = int(block.iloc[0]["n_parts"]) if len(block) else 0
    area = float(block.iloc[0]["area_km2"]) if len(block) else 0
    _frame(axes[1], f"AFTER — union + 50 m gap closing: {n_parts} blocks, "
                    f"{area:,.0f} km²")
    fig.suptitle("Geometric union in Shapely (MongoDB has no union operator)",
                 fontsize=11)
    fig.tight_layout()
    fig.savefig(IMG / "fig2_union_before_after.png", dpi=150)
    plt.close(fig)


def fig_burn_footprint(db):
    """Figure 3 - 1,564 hotspots buffered by 1 km and merged."""
    hot = _gdf(db, "fire_hotspots")
    burn = _gdf(db, "derived_zones", {"zone_type": "burn_risk_footprint"})
    fig, axes = plt.subplots(1, 2, figsize=(11, 5))
    hot.plot(ax=axes[0], color="#ff3d00", markersize=3, alpha=0.6)
    _frame(axes[0], f"BEFORE — {len(hot):,} VIIRS hotspot detections")
    burn.plot(ax=axes[1], color="#d84315", alpha=0.75)
    hot.plot(ax=axes[1], color="#3e2723", markersize=1, alpha=0.35)
    area = float(burn.iloc[0]["area_km2"]) if len(burn) else 0
    _frame(axes[1], f"AFTER — 1 km buffer + union: {area:,.0f} km² footprint")
    fig.suptitle(f"Burn-risk footprint, fire season {config.FIRE_SEASON[0]} to "
                 f"{config.FIRE_SEASON[1]}", fontsize=11)
    fig.tight_layout()
    fig.savefig(IMG / "fig3_burn_footprint.png", dpi=150)
    plt.close(fig)


def fig_critical_zone(db):
    """Figure 4 - the cross-theme result: critical zone and villages by risk."""
    crit = _gdf(db, "derived_zones", {"zone_type": "critical_zone"})
    hab = _gdf(db, "derived_zones", {"zone_type": "habitat_block"})
    risk_path = config.OUTPUT_DIR / "q6_village_risk.csv"

    fig, ax = plt.subplots(figsize=(8.5, 6))
    hab.plot(ax=ax, color="#004d40", alpha=0.18, label="habitat block")
    crit.plot(ax=ax, color="#b71c1c", alpha=0.45, label="critical zone (862 km²)")

    if risk_path.exists():
        risk = pd.read_csv(risk_path)
        pts = gpd.GeoDataFrame(
            risk, geometry=gpd.points_from_xy(risk.lon, risk.lat),
            crs=config.CRS_WGS84)
        sc = ax.scatter(pts.geometry.x, pts.geometry.y, c=pts.risk_score,
                        cmap="YlOrRd", s=16, edgecolor="black", linewidth=0.25,
                        vmin=0, vmax=100, zorder=3)
        cb = fig.colorbar(sc, ax=ax, shrink=0.8)
        cb.set_label("village risk score (0-100)", fontsize=9)
        n_crit = int(risk.in_critical_zone.sum())
        title = (f"Cross-theme result — {n_crit} of {len(risk)} villages inside the "
                 "critical zone")
    else:
        title = "Critical zone"
    _frame(ax, title)
    ax.legend(fontsize=8, loc="lower left")
    fig.tight_layout()
    fig.savefig(IMG / "fig4_critical_zone.png", dpi=150)
    plt.close(fig)


def main() -> int:
    IMG.mkdir(parents=True, exist_ok=True)
    db = get_db()
    print("Phase 9 - report figures\n")
    for fn in (fig_study_area, fig_union_before_after, fig_burn_footprint,
               fig_critical_zone):
        fn(db)
        print(f"  {fn.__name__}")
    print(f"\n  -> {IMG}")
    for p in sorted(IMG.glob("fig*.png")):
        print(f"     {p.name}  {p.stat().st_size/1024:.0f} KB")
    print("\n  plus outputs/benchmark.png (generated by scripts/benchmark.py)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
