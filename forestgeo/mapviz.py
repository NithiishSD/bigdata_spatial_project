"""Build the interactive Folium map: layered themes plus an animated fire timeline.

Folium wraps Leaflet.js, so the output is a self-contained HTML file that opens in any
browser with no server.

THE ONE COORDINATE EXCEPTION IN THIS PROJECT: Folium's location= argument takes
[latitude, longitude] - the reverse of GeoJSON. Everything stored in MongoDB is
[longitude, latitude]. This module is where the two meet, so every flip is marked.
"""

from __future__ import annotations

import folium
from folium.plugins import MarkerCluster, TimestampedGeoJson
from pymongo.database import Database

from forestgeo.config import BBOX, FIRE_SEASON, OUTPUT_DIR, REGION_NAME

# Display styling per theme.
STYLE = {
    "protected_areas": {"color": "#2e7d32", "weight": 2, "fillOpacity": 0.12},
    "forests": {"color": "#1b5e20", "weight": 1, "fillOpacity": 0.25},
    "water_bodies": {"color": "#1565c0", "weight": 1, "fillOpacity": 0.45},
    "farmland": {"color": "#f9a825", "weight": 1, "fillOpacity": 0.20},
    "habitat_block": {"color": "#004d40", "weight": 2, "fillOpacity": 0.15},
    "burn_risk_footprint": {"color": "#d84315", "weight": 1, "fillOpacity": 0.25},
    "critical_zone": {"color": "#b71c1c", "weight": 2, "fillOpacity": 0.35},
}
TRANSPORT_COLOUR = {"road": "#546e7a", "track": "#8d6e63", "railway": "#000000"}

# Residential and unclassified streets are 34,387 of 37,665 transport features (91%)
# and nearly all of the map's file size, while adding nothing to a regional fire and
# habitat story. They stay in MongoDB - every query still uses the full network - but
# the map draws only the classes that carry the narrative.
MAP_ROAD_CLASSES = ["motorway", "trunk", "primary", "secondary", "tertiary"]


def base_map() -> folium.Map:
    """A map centred on the study region, with three switchable basemaps."""
    west, south, east, north = BBOX
    centre = [(south + north) / 2, (west + east) / 2]   # FOLIUM: [lat, lon]
    m = folium.Map(location=centre, zoom_start=10, tiles=None, control_scale=True)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(m)
    # CartoDB basemaps now require an API key, so OpenTopoMap is used instead - and
    # its contour shading suits a hill region better anyway.
    folium.TileLayer(
        tiles="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
        attr="OpenTopoMap (CC-BY-SA)", name="OpenTopoMap", max_zoom=17,
    ).add_to(m)
    folium.TileLayer(
        tiles=("https://server.arcgisonline.com/ArcGIS/rest/services/"
               "World_Imagery/MapServer/tile/{z}/{y}/{x}"),
        attr="Esri", name="Esri Satellite",
    ).add_to(m)
    # fit_bounds also takes [[lat, lon], [lat, lon]] - Folium's order, not GeoJSON's.
    m.fit_bounds([[south, west], [north, east]])
    return m


def _features(db: Database, collection: str, query: dict | None = None,
              fields: tuple[str, ...] = ()) -> list[dict]:
    """Read documents and wrap them as GeoJSON Features for Folium."""
    proj = {"geometry": 1, **{f: 1 for f in fields}}
    out = []
    for d in db[collection].find(query or {}, proj):
        props = {f: d.get(f) for f in fields}
        props = {k: (v if v is not None else "-") for k, v in props.items()}
        out.append({"type": "Feature", "geometry": d["geometry"],
                    "properties": props})
    return out


def add_polygon_layer(m, db, collection, name, style_key=None, query=None,
                      fields=("name", "area_km2"), show=False) -> int:
    feats = _features(db, collection, query, fields)
    if not feats:
        return 0
    style = STYLE.get(style_key or collection, {"color": "#555", "weight": 1,
                                                "fillOpacity": 0.2})
    fg = folium.FeatureGroup(name=f"{name} ({len(feats)})", show=show)
    folium.GeoJson(
        {"type": "FeatureCollection", "features": feats},
        style_function=lambda _f, s=style: dict(s, fillColor=s["color"]),
        tooltip=folium.GeoJsonTooltip(fields=list(fields)),
    ).add_to(fg)
    fg.add_to(m)
    return len(feats)


def add_transport(m, db, show=False) -> int:
    """Roads, tracks and railways, coloured by kind."""
    total = 0
    for kind, colour in TRANSPORT_COLOUR.items():
        query: dict = {"kind": kind}
        if kind == "road":
            query["highway"] = {"$in": MAP_ROAD_CLASSES}
        feats = _features(db, "transport", query,
                          ("name", "kind", "highway", "length_km"))
        if not feats:
            continue
        label = f"transport: {kind}" + (" (main classes)" if kind == "road" else "")
        fg = folium.FeatureGroup(name=f"{label} ({len(feats)})", show=show)
        folium.GeoJson(
            {"type": "FeatureCollection", "features": feats},
            style_function=lambda _f, c=colour: {"color": c, "weight": 1.5,
                                                 "opacity": 0.75},
            tooltip=folium.GeoJsonTooltip(fields=["name", "kind", "length_km"]),
        ).add_to(fg)
        fg.add_to(m)
        total += len(feats)
    return total


def add_villages(m, db, risk_df=None, show=True) -> int:
    """Villages, coloured by risk score when the Phase 6 table is available."""
    fg = folium.FeatureGroup(name="villages", show=show)
    risk = {}
    if risk_df is not None and not risk_df.empty:
        risk = {(round(r.lon, 5), round(r.lat, 5)): r.risk_score
                for r in risk_df.itertuples()}

    n = 0
    for v in db.villages.find({}, {"geometry": 1, "name": 1, "place": 1}):
        lon, lat = v["geometry"]["coordinates"]          # GeoJSON: [lon, lat]
        score = risk.get((round(lon, 5), round(lat, 5)))
        colour = ("#9e9e9e" if score is None else
                  "#b71c1c" if score >= 75 else
                  "#ef6c00" if score >= 50 else
                  "#fbc02d" if score >= 25 else "#2e7d32")
        label = v.get("name") or "(unnamed)"
        folium.CircleMarker(
            location=[lat, lon],                         # FOLIUM: [lat, lon]
            radius=4 + (0 if score is None else score / 25),
            color=colour, fill=True, fillColor=colour, fillOpacity=0.85, weight=1,
            popup=folium.Popup(
                f"<b>{label}</b><br>{v.get('place') or ''}<br>"
                f"risk score: {'n/a' if score is None else round(score, 1)}",
                max_width=250),
            tooltip=label,
        ).add_to(fg)
        n += 1
    fg.add_to(m)
    return n


def add_sightings(m, db, show=False) -> tuple[int, int]:
    """Precise sightings clustered; obscured ones in a separate, labelled layer.

    Keeping them apart is a data-honesty decision: the obscured records are displaced
    by up to ~31 km, so showing them as ordinary points would imply a precision the
    data does not have.
    """
    precise = folium.FeatureGroup(name="sightings (precise)", show=show)
    cluster = MarkerCluster().add_to(precise)
    n_precise = 0
    for s in db.sightings.find({"precision": "precise"},
                               {"geometry": 1, "species": 1, "iucn_category": 1,
                                "event_date": 1}):
        lon, lat = s["geometry"]["coordinates"]
        folium.Marker(
            location=[lat, lon],                          # FOLIUM: [lat, lon]
            tooltip=s.get("species") or "?",
            popup=folium.Popup(
                f"<b>{s.get('species')}</b><br>IUCN: {s.get('iucn_category') or '-'}"
                f"<br>{str(s.get('event_date'))[:10]}", max_width=250),
            icon=folium.Icon(color="green", icon="paw-print", prefix="fa"),
        ).add_to(cluster)
        n_precise += 1
    precise.add_to(m)

    coarse = folium.FeatureGroup(
        name="sightings (location obscured, +/-31 km)", show=False)
    n_coarse = 0
    for s in db.sightings.find({"precision": "coarse"},
                               {"geometry": 1, "species": 1, "uncertainty_m": 1}):
        lon, lat = s["geometry"]["coordinates"]
        folium.CircleMarker(
            location=[lat, lon], radius=3, color="#7b1fa2", fill=True,
            fillOpacity=0.4, weight=1,
            tooltip=f"{s.get('species')} (obscured, "
                    f"+/-{int(s.get('uncertainty_m') or 0)} m)",
        ).add_to(coarse)
        n_coarse += 1
    coarse.add_to(m)
    return n_precise, n_coarse


def add_fire_timeline(m, db, show=True) -> int:
    """Animated daily fire hotspots using TimestampedGeoJson.

    The plugin needs a 'time' property on each feature, as an ISO 8601 string. Marker
    size is scaled by FRP so intense fires stand out.
    """
    feats = []
    for h in db.fire_hotspots.find(
            {}, {"geometry": 1, "acq_datetime": 1, "frp": 1, "confidence": 1}):
        when = h.get("acq_datetime")
        if when is None:
            continue
        frp = h.get("frp") or 0
        feats.append({
            "type": "Feature",
            "geometry": h["geometry"],
            "properties": {
                "time": when.isoformat(),
                "popup": f"FRP {frp:.1f} MW<br>{when:%Y-%m-%d %H:%M} UTC"
                         f"<br>confidence: {h.get('confidence')}",
                "icon": "circle",
                "iconstyle": {
                    "fillColor": "#ff3d00",
                    "fillOpacity": 0.8,
                    "stroke": "false",
                    "radius": 3 + min(frp, 100) / 12,
                },
            },
        })
    if not feats:
        return 0
    TimestampedGeoJson(
        {"type": "FeatureCollection", "features": feats},
        period="P1D",              # one step per day
        duration="P2D",            # each detection stays visible for two days
        add_last_point=False,
        auto_play=False,
        loop=False,
        max_speed=10,
        loop_button=True,
        date_options="YYYY-MM-DD",
        time_slider_drag_update=True,
    ).add_to(m)
    return len(feats)


def add_legend(m, counts: dict) -> None:
    """A collapsible HTML legend. Folium has no built-in legend widget.

    Placed BOTTOM-RIGHT, deliberately. The obvious spot is bottom-left, but
    TimestampedGeoJson puts its time slider and speed control there, so a legend in
    that corner silently covers the fire timeline - the one thing the map exists to
    show. Leaflet's own controls occupy top-left (zoom), top-right (layers) and
    bottom-left (time slider, scale bar), which leaves bottom-right.

    It is wrapped in <details> so it can be folded away, and capped at 45% of the
    viewport height with its own scrollbar so it can never cover the map on a short
    screen.
    """
    rows = "".join(
        f"<div style='white-space:nowrap'><span style='display:inline-block;"
        f"width:12px;height:12px;background:{c};margin-right:6px;"
        f"border:1px solid #666;vertical-align:-1px'></span>{label}</div>"
        for label, c in [
            ("village: high risk (&ge;75)", "#b71c1c"),
            ("village: medium (50-74)", "#ef6c00"),
            ("village: low (25-49)", "#fbc02d"),
            ("village: minimal (&lt;25)", "#2e7d32"),
            ("critical zone", "#b71c1c"),
            ("burn-risk footprint", "#d84315"),
            ("habitat block", "#004d40"),
            ("fire hotspot (animated)", "#ff3d00"),
        ])
    summary = " &middot; ".join(f"{k}: {v:,}" for k, v in counts.items())
    html = f"""
    <div style="position: fixed; bottom: 26px; right: 12px; z-index: 9999;
                background: rgba(255,255,255,0.94); border: 1px solid #999;
                border-radius: 4px; font: 12px/1.5 system-ui, sans-serif;
                max-width: 270px; max-height: 45vh; overflow-y: auto;
                box-shadow: 0 1px 4px rgba(0,0,0,0.3);">
      <details open style="padding: 8px 10px;">
        <summary style="font-weight:600; cursor:pointer; outline:none">
          {REGION_NAME} &mdash; legend
        </summary>
        <div style="margin-top:6px">{rows}</div>
        <div style="margin-top:6px;color:#555">Fire season {FIRE_SEASON[0]} to
          {FIRE_SEASON[1]}</div>
        <div style="margin-top:4px;color:#777;font-size:11px">{summary}</div>
      </details>
    </div>"""
    m.get_root().html.add_child(folium.Element(html))


def build(db: Database, risk_df=None, out_name: str = "forestgeo_map.html") -> str:
    """Assemble every layer and write the HTML."""
    m = base_map()
    counts = {}

    counts["forests"] = add_polygon_layer(m, db, "forests", "forests",
                                          fields=("name", "area_km2"))
    counts["water"] = add_polygon_layer(m, db, "water_bodies", "water bodies",
                                        fields=("name", "area_km2"))
    counts["farmland"] = add_polygon_layer(m, db, "farmland", "farmland",
                                           fields=("name", "area_km2"))
    counts["protected"] = add_polygon_layer(m, db, "protected_areas",
                                            "protected areas", show=True,
                                            fields=("name", "area_km2"))
    for zone_type, label in (("habitat_block", "habitat block (union)"),
                             ("burn_risk_footprint", "burn-risk footprint (union)"),
                             ("critical_zone", "critical zone (intersection)")):
        counts[zone_type] = add_polygon_layer(
            m, db, "derived_zones", label, style_key=zone_type,
            query={"zone_type": zone_type}, fields=("zone_type", "area_km2"),
            show=(zone_type == "critical_zone"))

    counts["rivers"] = add_polygon_layer(m, db, "rivers", "rivers",
                                         style_key="water_bodies",
                                         fields=("name", "length_km"))
    counts["transport"] = add_transport(m, db)
    counts["villages"] = add_villages(m, db, risk_df)
    n_precise, n_coarse = add_sightings(m, db)
    counts["sightings"] = n_precise + n_coarse
    counts["hotspots"] = add_fire_timeline(m, db)

    folium.LayerControl(collapsed=False).add_to(m)
    add_legend(m, counts)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / out_name
    m.save(str(path))
    return str(path)
