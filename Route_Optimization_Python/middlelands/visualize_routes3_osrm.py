"""
Visualize routes3.py (or osrm_matrix_routes.py) visit order on a road map.

Reads CSV visit order from our heuristics (NN / 2-opt / RR-2opt), then draws
OSRM driving geometry and optional turn-by-turn steps via /route.

Not Folium — standalone HTML + Leaflet.js (CDN), same idea as visualize_map3.py
but polylines follow real roads.

Prerequisites:
    python cluster3.py
    python routes3.py                    -> data/routes3_*.csv
    # optional, for OSRM-matrix visit order:
    python osrm_matrix_routes.py         -> data/routes_osrm_*.csv
    OSRM HTTP server on OSRM_BASE (default http://127.0.0.1:5000)

Usage:
    python visualize_routes3_osrm.py              # routes3 RR-2opt (default)
    python visualize_routes3_osrm.py nn
    python visualize_routes3_osrm.py 2opt --source osrm
    python visualize_routes3_osrm.py rr2opt --no-turns
    python visualize_routes3_osrm.py --no-open

Output:
    html/routes3_osrm_<algorithm>.html
    html/routes_osrm_<algorithm>.html   (with --source osrm)
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.parse
import urllib.request
import webbrowser
from typing import Any

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA_DIR = os.path.join(REPO_ROOT, "data")
HTML_DIR = os.path.join(REPO_ROOT, "html")
os.makedirs(HTML_DIR, exist_ok=True)

OSRM_BASE = os.environ.get("OSRM_BASE", "http://127.0.0.1:5000").rstrip("/")
OSRM_PROFILE = os.environ.get("OSRM_PROFILE", "driving")

ROUTES3_FILES = {
    "nn": "routes3_nn.csv",
    "2opt": "routes3_2opt.csv",
    "rr2opt": "routes3_rr2opt.csv",
    "rr": "routes3_rr2opt.csv",
}
OSRM_MATRIX_FILES = {
    "nn": "routes_osrm_nn.csv",
    "2opt": "routes_osrm_2opt.csv",
    "rr2opt": "routes_osrm_rr2opt.csv",
    "rr": "routes_osrm_rr2opt.csv",
}
ALGO_LABELS = {
    "nn": "Nearest Neighbour",
    "2opt": "2-opt",
    "rr2opt": "Random Restart 2-opt",
    "rr": "Random Restart 2-opt",
}

CLUSTER_COLOURS = [
    "#e53935", "#1e88e5", "#43a047", "#fb8c00", "#8e24aa",
    "#00acc1", "#f4511e", "#6d4c41", "#546e7a", "#c0ca33",
    "#d81b60", "#3949ab", "#00897b", "#fdd835", "#5e35b1",
]


def lonlat(lat: float, lon: float) -> str:
    return f"{lon},{lat}"


def fetch_osrm_route(
    points: list[dict],
    include_steps: bool = True,
    timeout: int = 120,
) -> tuple[float | None, float | None, dict | None, list[dict]]:
    """GET /route/v1/{profile}/... -> (km, sec, GeoJSON geometry, turns)."""
    if len(points) < 2:
        return 0.0, 0.0, None, []

    coord_str = ";".join(lonlat(p["latitude"], p["longitude"]) for p in points)
    path = f"/route/v1/{OSRM_PROFILE}/{coord_str}"
    params: dict[str, str] = {
        "overview": "full",
        "geometries": "geojson",
        "steps": "true" if include_steps else "false",
        "continue_straight": "false",
    }
    url = f"{OSRM_BASE}{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"    OSRM /route error: {e}")
        return None, None, None, []

    if data.get("code") != "Ok" or not data.get("routes"):
        print(f"    OSRM returned: {data.get('code', 'no routes')}")
        return None, None, None, []

    r0 = data["routes"][0]
    dist_km = float(r0.get("distance", 0)) / 1000.0
    dur_s = float(r0.get("duration", 0))
    geom = r0.get("geometry")
    if geom and geom.get("type") != "LineString":
        geom = None

    turns: list[dict] = []
    if include_steps:
        idx = 0
        for leg in r0.get("legs") or []:
            for step in leg.get("steps") or []:
                m = step.get("maneuver") or {}
                loc = m.get("location")
                if not loc or len(loc) < 2:
                    continue
                typ = str(m.get("type") or "")
                mod = str(m.get("modifier") or "")
                street = str(step.get("name") or "").strip()
                hint = " ".join(
                    x for x in (mod.replace("_", " "), typ.replace("_", " ")) if x
                ).strip()
                if street:
                    hint = f"{hint} — {street}".strip(" —") if hint else street
                elif not hint:
                    hint = typ or "continue"
                turns.append(
                    {
                        "index": idx,
                        "instruction": hint[:200],
                        "distanceM": round(float(step.get("distance", 0)), 1),
                        "durationS": round(float(step.get("duration", 0)), 1),
                        "lon": float(loc[0]),
                        "lat": float(loc[1]),
                    }
                )
                idx += 1
    return dist_km, dur_s, geom, turns


def straight_line_geometry(points: list[dict]) -> dict:
    return {
        "type": "LineString",
        "coordinates": [
            [float(p["longitude"]), float(p["latitude"])] for p in points
        ],
    }


def load_routes(path: str) -> tuple[dict[int, list[dict]], list[int]]:
    vans: dict[int, list[dict]] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            van = int(row["van"])
            row["stop_order"] = int(row["stop_order"])
            row["latitude"] = float(row["latitude"])
            row["longitude"] = float(row["longitude"])
            row["demand"] = int(row["demand"])
            vans.setdefault(van, []).append(row)
    for van in vans:
        vans[van].sort(key=lambda r: r["stop_order"])
    return vans, sorted(vans.keys())


def build_html(
    routes_path: str,
    algo_label: str,
    source_label: str,
    include_turns: bool,
) -> str:
    if not os.path.isfile(routes_path):
        raise SystemExit(
            f"Missing {routes_path}\n"
            "Run routes3.py (and optionally osrm_matrix_routes.py) first."
        )

    vans, van_ids = load_routes(routes_path)
    if not van_ids:
        raise SystemExit(f"No routes in {routes_path}")

    van_payloads: list[dict] = []
    all_lats: list[float] = []
    all_lons: list[float] = []
    warnings: list[str] = []

    print(f"  OSRM_BASE: {OSRM_BASE}  profile={OSRM_PROFILE}")
    for i, vid in enumerate(van_ids):
        route = vans[vid]
        colour = CLUSTER_COLOURS[i % len(CLUSTER_COLOURS)]
        points = [
            {"latitude": r["latitude"], "longitude": r["longitude"]} for r in route
        ]
        for p in points:
            all_lats.append(p["latitude"])
            all_lons.append(p["longitude"])

        plan_km = float(route[-1].get("route_km_so_far") or 0)
        n_stops = sum(1 for r in route if r["delivery_id"] != "DEPOT")

        print(f"  Van {vid + 1}/{len(van_ids)} — {n_stops} stops, fetching /route …")
        road_km, dur_s, geom, turns = fetch_osrm_route(points, include_turns)
        if geom is None:
            geom = straight_line_geometry(points)
            warnings.append(f"Van {vid + 1}: OSRM geometry failed; straight-line fallback.")
            turns = []
        if road_km is None:
            road_km = plan_km
        if dur_s is None:
            dur_s = 0.0

        markers = []
        for r in route:
            if r["delivery_id"] == "DEPOT":
                markers.append(
                    {
                        "lat": r["latitude"],
                        "lon": r["longitude"],
                        "type": "depot",
                        "popup": f"<b>Depot</b> — Van {vid + 1}<br>{r['postcode']}",
                    }
                )
            else:
                markers.append(
                    {
                        "lat": r["latitude"],
                        "lon": r["longitude"],
                        "type": "stop",
                        "popup": (
                            f"<b>{r['delivery_id']}</b> — Van {vid + 1}, "
                            f"stop #{r['stop_order']}<br>"
                            f"{r['customer_name']}<br>{r['postcode']}<br>"
                            f"Demand: {r['demand']} | {r['priority']}"
                        ),
                    }
                )

        van_payloads.append(
            {
                "id": vid,
                "colour": colour,
                "stops": n_stops,
                "planKm": round(plan_km, 2),
                "roadKm": round(float(road_km), 2),
                "durationMin": round(float(dur_s) / 60.0, 1),
                "geometry": geom,
                "markers": markers,
                "turns": turns,
                "visitOrder": [r["delivery_id"] for r in route],
            }
        )

    map_lat = sum(all_lats) / len(all_lats)
    map_lon = sum(all_lons) / len(all_lons)
    vans_json = json.dumps(van_payloads)
    warnings_json = json.dumps(warnings)
    pills_html = "".join(
        f'<span class="pill" style="background:{v["colour"]}">'
        f'Van {v["id"] + 1}: {v["stops"]}</span>'
        for v in van_payloads
    )
    warn_html = (
        "<ul>"
        + "".join(f"<li>{w}</li>" for w in warnings)
        + "</ul>"
        if warnings
        else ""
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{source_label} — {algo_label} (OSRM roads)</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <style>
    *{{margin:0;padding:0;box-sizing:border-box}}
    body{{font-family:Arial,sans-serif;height:100vh;display:flex;flex-direction:column}}
    #header{{
      background:#1a237e;color:white;padding:8px 14px;flex-shrink:0
    }}
    #header h1{{font-size:14px;margin-bottom:4px}}
    #header .sub{{font-size:11px;opacity:0.9}}
    #pills{{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}}
    .pill{{padding:3px 10px;border-radius:12px;font-size:11px;font-weight:bold;color:white}}
    #main{{flex:1;display:flex;min-height:0}}
    #map{{flex:1;min-width:0}}
  #sidebar{{
      width:320px;background:#fafafa;border-left:1px solid #ccc;
      display:flex;flex-direction:column;flex-shrink:0
    }}
    #sidebar h2{{font-size:13px;padding:10px 12px;background:#eee;border-bottom:1px solid #ccc}}
    #vanSelect{{margin:8px 12px;padding:6px;font-size:12px}}
    #turnsList{{
      flex:1;overflow-y:auto;padding:8px 12px;font-size:12px;line-height:1.45
    }}
    .turn-row{{padding:6px 0;border-bottom:1px solid #e0e0e0;cursor:pointer}}
    .turn-row:hover{{background:#e8eaf6}}
    .turn-meta{{color:#666;font-size:10px}}
    #legend{{
      background:white;padding:10px 14px;border-radius:8px;font-size:12px;
      box-shadow:0 2px 8px rgba(0,0,0,0.2);line-height:1.9;max-height:50vh;overflow-y:auto
    }}
    #legend h4{{font-size:13px;margin-bottom:4px;border-bottom:1px solid #ddd;padding-bottom:3px}}
    .leg-row{{display:flex;align-items:center;gap:7px;cursor:pointer}}
    .leg-row:hover{{opacity:0.8}}
    .leg-line{{width:18px;height:3px;flex-shrink:0}}
    .warn{{background:#fff3e0;color:#e65100;padding:8px 12px;font-size:11px}}
  </style>
</head>
<body>
<div id="header">
  <h1>{source_label} — {algo_label} | {len(van_ids)} vans</h1>
  <div class="sub">Visit order from CSV heuristics · road lines from OSRM /route · {OSRM_BASE}</div>
  <div id="pills">{pills_html}</div>
</div>
{"<div class='warn'>" + warn_html + "</div>" if warnings else ""}
<div id="main">
  <div id="map"></div>
  <aside id="sidebar">
    <h2>Turn-by-turn</h2>
    <select id="vanSelect"></select>
    <div id="turnsList"></div>
  </aside>
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const vans = {vans_json};
const includeTurns = {str(include_turns).lower()};
const warnings = {warnings_json};

const map = L.map("map").setView([{map_lat},{map_lon}], 9);
L.tileLayer("https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", {{
  attribution: "© OpenStreetMap", maxZoom: 18
}}).addTo(map);

const routeLayers = {{}};
const stopLayers = {{}};
const bounds = L.latLngBounds();

vans.forEach(v => {{
  if (v.geometry && v.geometry.coordinates) {{
    const layer = L.geoJSON(v.geometry, {{
      style: {{ color: v.colour, weight: 4, opacity: 0.88 }}
    }}).bindPopup(
      "Van " + (v.id + 1) + "<br>"
      + "Planned (CSV): " + v.planKm + " km<br>"
      + "OSRM road: " + v.roadKm + " km · " + v.durationMin + " min"
    );
    routeLayers["Van " + (v.id + 1) + " route"] = layer;
    layer.addTo(map);
    bounds.extend(layer.getBounds());
  }}

  const sk = "Van " + (v.id + 1) + " stops";
  if (!stopLayers[sk]) stopLayers[sk] = L.layerGroup();

  const stopIcon = () => L.divIcon({{
    className: "",
    html: `<div style="width:10px;height:10px;background:${{v.colour}};
      border:2px solid white;border-radius:50%"></div>`,
    iconSize: [10, 10], iconAnchor: [5, 5]
  }});
  const depotIcon = () => L.divIcon({{
    className: "",
    html: `<div style="width:18px;height:18px;background:#1a237e;border:2px solid white;
      border-radius:3px;color:white;font-size:10px;font-weight:bold;
      display:flex;align-items:center;justify-content:center">D</div>`,
    iconSize: [18, 18], iconAnchor: [9, 9]
  }});

  v.markers.forEach(m => {{
    const mk = m.type === "depot"
      ? L.marker([m.lat, m.lon], {{ icon: depotIcon() }}).bindPopup(m.popup)
      : L.marker([m.lat, m.lon], {{ icon: stopIcon() }}).bindPopup(m.popup);
    stopLayers[sk].addLayer(mk);
    bounds.extend([m.lat, m.lon]);
  }});
}});

Object.values(stopLayers).forEach(lg => lg.addTo(map));
L.control.layers(null, Object.assign({{}}, routeLayers, stopLayers), {{ collapsed: false }}).addTo(map);
if (bounds.isValid()) map.fitBounds(bounds, {{ padding: [40, 40], maxZoom: 11 }});

const legend = L.control({{ position: "bottomleft" }});
legend.onAdd = () => {{
  const div = L.DomUtil.create("div", "");
  div.id = "legend";
  let h = "<h4>Van routes (click → turns)</h4>";
  vans.forEach(v => {{
    h += `<div class="leg-row" data-van="${{v.id}}">`
      + `<span class="leg-line" style="background:${{v.colour}}"></span>`
      + " Van " + (v.id + 1) + " — " + v.stops + " stops<br>"
      + "<small>CSV " + v.planKm + " km · OSRM " + v.roadKm + " km</small></div>";
  }});
  div.innerHTML = h;
  div.querySelectorAll(".leg-row").forEach(el => {{
    el.addEventListener("click", () => {{
      const id = parseInt(el.getAttribute("data-van"), 10);
      document.getElementById("vanSelect").value = String(id);
      renderTurns(id);
    }});
  }});
  return div;
}};
legend.addTo(map);

const sel = document.getElementById("vanSelect");
vans.forEach(v => {{
  const o = document.createElement("option");
  o.value = v.id;
  o.textContent = "Van " + (v.id + 1) + " (" + v.stops + " stops)";
  sel.appendChild(o);
}});
sel.addEventListener("change", () => renderTurns(parseInt(sel.value, 10)));

function renderTurns(vanId) {{
  const box = document.getElementById("turnsList");
  const v = vans.find(x => x.id === vanId);
  if (!v) {{ box.innerHTML = ""; return; }}
  if (!includeTurns) {{
    box.innerHTML = "<p>Turns disabled (--no-turns).</p>";
    return;
  }}
  if (!v.turns || !v.turns.length) {{
    box.innerHTML = "<p>No OSRM steps (fallback line or empty route).</p>";
    return;
  }}
  let h = "<p><b>Van " + (v.id + 1) + "</b> — " + v.turns.length + " steps</p>";
  v.turns.forEach(t => {{
    h += `<div class="turn-row" data-lat="${{t.lat}}" data-lon="${{t.lon}}">`
      + (t.index + 1) + ". " + t.instruction
      + `<div class="turn-meta">${{t.distanceM}} m · ${{t.durationS}} s</div></div>`;
  }});
  box.innerHTML = h;
  box.querySelectorAll(".turn-row").forEach(el => {{
    el.addEventListener("click", () => {{
      const lat = parseFloat(el.getAttribute("data-lat"));
      const lon = parseFloat(el.getAttribute("data-lon"));
      map.setView([lat, lon], 15);
    }});
  }});
}}

if (vans.length) renderTurns(vans[0].id);
</script>
</body>
</html>"""

    # Fix accidental tag typos from template editing
    prefix = "routes_osrm" if "osrm" in source_label.lower() else "routes3_osrm"
    safe = algo_label.replace(" ", "_").replace("-", "").lower()
    out_file = os.path.join(HTML_DIR, f"{prefix}_{safe}.html")
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(html)
    return out_file


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Leaflet map: routes3/osrm_matrix CSV visit order + OSRM /route geometry"
    )
    parser.add_argument(
        "algo",
        nargs="?",
        default="rr2opt",
        choices=list(ROUTES3_FILES.keys()),
        help="Algorithm: nn, 2opt, rr2opt (default)",
    )
    parser.add_argument(
        "--source",
        choices=("routes3", "osrm"),
        default="routes3",
        help="routes3 = Haversine-planned CSV; osrm = routes_osrm_*.csv from osrm_matrix_routes.py",
    )
    parser.add_argument("--no-turns", action="store_true", help="Skip OSRM step parsing")
    parser.add_argument("--no-open", action="store_true", help="Do not open browser")
    args = parser.parse_args()

    files = OSRM_MATRIX_FILES if args.source == "osrm" else ROUTES3_FILES
    routes_path = os.path.join(DATA_DIR, files[args.algo])
    algo_label = ALGO_LABELS.get(args.algo, args.algo)
    source_label = (
        "OSRM matrix + heuristics"
        if args.source == "osrm"
        else "routes3 (Haversine heuristics)"
    )

    print("=" * 60)
    print("  Route map — visit order from CSV, roads from OSRM")
    print("=" * 60)
    print(f"  Input  : {routes_path}")
    out = build_html(routes_path, algo_label, source_label, not args.no_turns)
    print(f"  Saved  : {out}")
    if not args.no_open:
        webbrowser.open(f"file:///{os.path.abspath(out)}")
        print("  Opened in browser.")
    print("=" * 60)


if __name__ == "__main__":
    main()
