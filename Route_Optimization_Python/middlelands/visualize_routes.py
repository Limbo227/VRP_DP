"""
Route map visualizer for routes3.py output
------------------------------------------
Reads routes_*.csv and draws each van's visit order as coloured polylines
on an interactive Leaflet map.

Prerequisites:
    python cluster3.py   (or cluster2.py)  -> clusters3.csv
    python routes3.py                      -> routes_*.csv

Usage:
    python visualize_map3.py          # Random Restart 2-opt (default)
    python visualize_map3.py nn
    python visualize_map3.py 2opt

Output:
    html/route_map3_<algorithm>.html
"""

import csv
import json
import os
import sys
import webbrowser

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA_DIR = os.path.join(REPO_ROOT, "data")
HTML_DIR = os.path.join(REPO_ROOT, "html")
os.makedirs(HTML_DIR, exist_ok=True)

ALGO_FILES = {
    "nn": "routes3_nn.csv",
    "2opt": "routes3_2opt.csv",
    "rr2opt": "routes3_rr2opt.csv",  # Use "rr2opt" only—"rr" was a confusing duplicate
}
ALGO_LABELS = {
    "nn": "Nearest Neighbour",
    "2opt": "2-opt",
    "rr2opt": "Random Restart 2-opt",
}

CLUSTER_COLOURS = [
    "#e53935", "#1e88e5", "#43a047", "#fb8c00", "#8e24aa",
    "#00acc1", "#f4511e", "#6d4c41", "#546e7a", "#c0ca33",
    "#d81b60", "#3949ab", "#00897b", "#fdd835", "#5e35b1",
]


def load_routes(path: str) -> tuple[dict, list[int]]:
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


def build_map(routes_path: str, algo_label: str) -> str:
    if not os.path.isfile(routes_path):
        raise SystemExit(
            f"Missing {routes_path}\nRun routes3.py first (needs clusters3.csv)."
        )

    vans, van_ids = load_routes(routes_path)
    if not van_ids:
        raise SystemExit(f"No routes in {routes_path}")

    polylines = []
    markers = []
    van_meta = []
    all_lats, all_lons = [], []

    for i, vid in enumerate(van_ids):
        route = vans[vid]
        colour = CLUSTER_COLOURS[i % len(CLUSTER_COLOURS)]
        coords = [[r["latitude"], r["longitude"]] for r in route]
        for lat, lon in coords:
            all_lats.append(lat)
            all_lons.append(lon)

        total_km = float(route[-1].get("route_km_so_far") or 0)
        n_stops = sum(1 for r in route if r["delivery_id"] != "DEPOT")
        van_meta.append({
            "id": vid, "colour": colour, "stops": n_stops, "km": round(total_km, 2),
        })

        polylines.append({
            "van": vid,
            "colour": colour,
            "coords": coords,
            "label": f"Van {vid + 1} — {n_stops} stops, {total_km:.1f} km",
        })

        for r in route:
            if r["delivery_id"] == "DEPOT":
                markers.append({
                    "lat": r["latitude"], "lon": r["longitude"],
                    "type": "depot", "van": vid, "colour": colour,
                    "popup": f"<b>Depot</b> — Van {vid + 1} route<br>{r['postcode']}",
                })
            else:
                markers.append({
                    "lat": r["latitude"], "lon": r["longitude"],
                    "type": "stop", "van": vid, "colour": colour,
                    "popup": (
                        f"<b>{r['delivery_id']}</b> — Van {vid + 1}, "
                        f"stop #{r['stop_order']}<br>"
                        f"{r['customer_name']}<br>{r['postcode']}<br>"
                        f"Demand: {r['demand']} | {r['priority']}"
                    ),
                })

    map_lat = sum(all_lats) / len(all_lats)
    map_lon = sum(all_lons) / len(all_lons)
    n_vans = len(van_ids)

    polylines_json = json.dumps(polylines)
    markers_json = json.dumps(markers)
    van_meta_json = json.dumps(van_meta)
    pills_html = "".join(
        f'<span class="pill" style="background:{m["colour"]}">'
        f'Van {m["id"] + 1}: {m["stops"]}</span>'
        for m in van_meta
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Route map — {algo_label}</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <style>
    *{{margin:0;padding:0;box-sizing:border-box}}
    body{{font-family:Arial,sans-serif}}
    #header{{
      background:#1a237e;color:white;padding:10px 16px;
      display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px
    }}
    #header h1{{font-size:15px}}
    #pills{{display:flex;gap:6px;flex-wrap:wrap}}
    .pill{{padding:3px 10px;border-radius:12px;font-size:11px;font-weight:bold;color:white}}
    #map{{height:calc(100vh - 48px)}}
    #legend{{
      background:white;padding:10px 14px;border-radius:8px;font-size:12px;
      box-shadow:0 2px 8px rgba(0,0,0,0.2);line-height:1.9;max-height:70vh;overflow-y:auto
    }}
    #legend h4{{font-size:13px;margin-bottom:4px;border-bottom:1px solid #ddd;padding-bottom:3px}}
    .leg-row{{display:flex;align-items:center;gap:7px}}
    .leg-line{{width:18px;height:3px;flex-shrink:0}}
  </style>
</head>
<body>
<div id="header">
  <h1>Routes (routes3) — {algo_label} | {n_vans} vans</h1>
  <div id="pills">{pills_html}</div>
</div>
<div id="map"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const map = L.map("map").setView([{map_lat},{map_lon}], 9);
L.tileLayer("https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", {{
  attribution:"© OpenStreetMap", maxZoom:18
}}).addTo(map);

const polylines = {polylines_json};
const allMarkers = {markers_json};
const vanMeta = {van_meta_json};

const routeLayers = {{}};
const stopLayers = {{}};

polylines.forEach(pl => {{
  const latlngs = pl.coords.map(c => [c[0], c[1]]);
  const layer = L.polyline(latlngs, {{ color: pl.colour, weight: 4, opacity: 0.85 }})
    .bindPopup(pl.label);
  routeLayers["Van " + (pl.van + 1) + " route"] = layer;
  layer.addTo(map);
}});

const stopIcon = col => L.divIcon({{className:"",
  html:`<div style="width:10px;height:10px;background:${{col}};
    border:2px solid white;border-radius:50%;
    box-shadow:0 1px 3px rgba(0,0,0,0.4)"></div>`,
  iconSize:[10,10],iconAnchor:[5,5],popupAnchor:[0,-6]}});

const depotIcon = () => L.divIcon({{className:"",
  html:`<div style="width:20px;height:20px;background:#1a237e;border:3px solid white;
    border-radius:4px;box-shadow:0 2px 6px rgba(0,0,0,0.5);color:white;
    display:flex;align-items:center;justify-content:center;font-weight:bold;font-size:11px">D</div>`,
  iconSize:[20,20],iconAnchor:[10,10],popupAnchor:[0,-12]}});

allMarkers.forEach(m => {{
  let mk;
  if (m.type === "depot") {{
    mk = L.marker([m.lat, m.lon], {{ icon: depotIcon() }}).bindPopup(m.popup);
    const dk = "Depot";
    if (!stopLayers[dk]) stopLayers[dk] = L.layerGroup();
    stopLayers[dk].addLayer(mk);
  }} else {{
    mk = L.marker([m.lat, m.lon], {{ icon: stopIcon(m.colour) }}).bindPopup(m.popup);
    const sk = "Van " + (m.van + 1) + " stops";
    if (!stopLayers[sk]) stopLayers[sk] = L.layerGroup();
    stopLayers[sk].addLayer(mk);
  }}
}});

Object.values(stopLayers).forEach(lg => lg.addTo(map));

const overlays = Object.assign({{}}, routeLayers, stopLayers);
L.control.layers(null, overlays, {{ collapsed: false }}).addTo(map);

const legend = L.control({{ position: "bottomleft" }});
legend.onAdd = () => {{
  const div = L.DomUtil.create("div", "");
  div.id = "legend";
  let h = "<h4>Van routes</h4>";
  vanMeta.forEach(m => {{
    h += `<div class="leg-row"><span class="leg-line" style="background:${{m.colour}}"></span>`
       + " Van " + (m.id + 1) + " — " + m.stops + " stops, " + m.km + " km</div>";
  }});
  div.innerHTML = h;
  return div;
}};
legend.addTo(map);
</script>
</body>
</html>"""


    safe = algo_label.replace(" ", "_").replace("-", "").lower()
    out_file = os.path.join(HTML_DIR, f"route_map3_{safe}.html")
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(html)
    return out_file


def main():
    algo = sys.argv[1].strip().lower() if len(sys.argv) > 1 else "rr2opt"
    if algo not in ALGO_FILES:
        print(f"Unknown '{algo}'. Choose: {', '.join(ALGO_FILES)}")
        raise SystemExit(1)

    routes_path = os.path.join(DATA_DIR, ALGO_FILES[algo])
    label = ALGO_LABELS.get(algo, algo)

    print("=" * 56)
    print("  Route map visualizer (routes3)")
    print("=" * 56)
    print(f"  Input : {routes_path}")
    out = build_map(routes_path, label)
    print(f"  Saved : {out}")
    print("  Opening in browser…")
    webbrowser.open(f"file:///{os.path.abspath(out)}")
    print("=" * 56)


if __name__ == "__main__":
    main()
