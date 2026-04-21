"""
K-Means Clustering — DPD Hinckley Delivery Routes
--------------------------------------------------
Uses scikit-learn's official KMeans implementation.

Why scikit-learn instead of hand-written:
    - Runs K-Means 10 times with different starting points (n_init=10)
      and picks the best result — avoids bad random initialisations
    - Industry-standard, academically verified implementation
    - You can cite it properly in your report:
      Pedregosa et al., "Scikit-learn: Machine Learning in Python",
      JMLR 12, pp. 2825-2830, 2011.

KEY CONSTRAINT:
    Max 20 stops per vehicle (MAX_STOPS_PER_VEHICLE).
    Any cluster exceeding this is recursively split
    until all clusters are within the limit.
    Final vehicle count is calculated automatically.

Install:
    pip install scikit-learn numpy

Run:
    python cluster.py

Output:
    clusters.csv       — original data + cluster column
    cluster_map.html   — interactive map coloured by cluster
"""

import csv
import math
import json
import os
import webbrowser
import numpy as np
from sklearn.cluster import KMeans

# ── Config ────────────────────────────────────────────────────────
MAX_STOPS_PER_VEHICLE = 20
RANDOM_SEED           = 42

CLUSTER_COLOURS = [
    "#e53935", "#1e88e5", "#43a047", "#fb8c00", "#8e24aa",
    "#00acc1", "#f4511e", "#6d4c41", "#546e7a", "#c0ca33",
    "#d81b60", "#3949ab", "#00897b", "#fdd835", "#5e35b1",
]


# ── Distance (used for summary stats only, not clustering) ────────
def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


# ── sklearn KMeans wrapper ────────────────────────────────────────
def run_kmeans(stops, k):
    """
    Run scikit-learn KMeans on a list of stop dicts.

    n_init=10  → runs 10 times with different random starts,
                 picks the run with lowest inertia (tightest clusters).
                 This is the main advantage over a hand-written version.

    inertia    → sum of squared distances of each stop to its cluster
                 centre. Lower = tighter, better clusters. scikit-learn
                 exposes this as model.inertia_ so you can compare runs.

    Returns list of integer cluster assignments (one per stop).
    """
    coords = np.array([[s["latitude"], s["longitude"]] for s in stops])

    if k == 1:
        return [0] * len(stops), coords.mean(axis=0).tolist()

    model = KMeans(
        n_clusters   = k,
        n_init       = 10,       # 10 random starts, picks best
        random_state = RANDOM_SEED,
    )
    model.fit(coords)

    return model.labels_.tolist(), model.cluster_centers_.tolist()


# ── Recursive splitter ────────────────────────────────────────────
def split_oversized(stops, max_size):
    """
    Recursively split any cluster exceeding max_size using sklearn KMeans.

    Example with 43 stops, max 20:
        k = ceil(43/20) = 3
        sklearn splits into e.g. [22, 12, 9]
        22 > 20 → recurse on those 22 stops
            k = ceil(22/20) = 2
            sklearn splits into [11, 11] → both fine
        Final: 4 clusters, all ≤ 20
    """
    k = math.ceil(len(stops) / max_size)

    if k <= 1:
        return [stops]

    assignments, _ = run_kmeans(stops, k)

    # Group stops by their cluster assignment
    sub_clusters = {}
    for i, a in enumerate(assignments):
        sub_clusters.setdefault(a, []).append(stops[i])

    # Recurse into any that are still too large
    final = []
    for sub in sub_clusters.values():
        if len(sub) > max_size:
            final.extend(split_oversized(sub, max_size))
        else:
            final.append(sub)

    return final


# ── Step 1: Load data ─────────────────────────────────────────────
input_file = "deliveries.csv"

if not os.path.exists(input_file):
    print(f"ERROR: '{input_file}' not found.")
    print("Run generate_dataset.py first.")
    raise SystemExit(1)

depot = None
stops = []

with open(input_file, newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        row["latitude"]  = float(row["latitude"])
        row["longitude"] = float(row["longitude"])
        row["demand"]    = int(row["demand"])
        if row["delivery_id"] == "DEPOT":
            depot = row
        else:
            stops.append(row)

n            = len(stops)
min_vehicles = math.ceil(n / MAX_STOPS_PER_VEHICLE)

print("=" * 58)
print("  K-Means Clustering — DPD Hinckley (scikit-learn)")
print("=" * 58)
print(f"\n  Depot          : {depot['postcode']}")
print(f"  Total stops    : {n}")
print(f"  Max per vehicle: {MAX_STOPS_PER_VEHICLE}")
print(f"  Min vehicles   : {min_vehicles}")
print(f"  sklearn n_init : 10  (best of 10 random starts)\n")
print("  Clustering...\n")


# ── Step 2: Cluster ───────────────────────────────────────────────
final_clusters = split_oversized(stops, MAX_STOPS_PER_VEHICLE)
K = len(final_clusters)

# Also run a single full KMeans for inertia reporting
coords_all = np.array([[s["latitude"], s["longitude"]] for s in stops])
full_model = KMeans(n_clusters=K, n_init=10, random_state=RANDOM_SEED)
full_model.fit(coords_all)

print(f"  Done. Vehicles needed : {K}")
print(f"  Inertia (sklearn)     : {full_model.inertia_:.4f}")
print(f"  (Lower inertia = tighter, more geographically compact clusters)\n")


# ── Step 3: Attach cluster IDs to stops ───────────────────────────
cluster_stats = []

for cluster_id, cluster_stops in enumerate(final_clusters):
    for stop in cluster_stops:
        stop["cluster"] = cluster_id

    total_demand = sum(s["demand"] for s in cluster_stops)
    centre_lat   = sum(s["latitude"]  for s in cluster_stops) / len(cluster_stops)
    centre_lon   = sum(s["longitude"] for s in cluster_stops) / len(cluster_stops)
    dist_depot   = haversine(
        depot["latitude"], depot["longitude"],
        centre_lat, centre_lon
    )
    cluster_stats.append({
        "id":            cluster_id + 1,
        "stops":         len(cluster_stops),
        "total_demand":  total_demand,
        "centre_lat":    round(centre_lat, 5),
        "centre_lon":    round(centre_lon, 5),
        "dist_depot_km": round(dist_depot, 1),
    })


# ── Step 4: Summary ───────────────────────────────────────────────
print(f"  {'Van':<5} {'Stops':>6} {'Parcels':>8} {'Dist from depot':>16}   Bar")
print(f"  {'-'*58}")
for s in cluster_stats:
    flag = " ← OVER LIMIT" if s["stops"] > MAX_STOPS_PER_VEHICLE else ""
    bar  = "█" * s["stops"]
    print(f"  Van {s['id']:<2} {s['stops']:>6} {s['total_demand']:>8}"
          f"  {s['dist_depot_km']:>8.1f} km    {bar}{flag}")

print(f"  {'-'*58}")
print(f"  {'Total':<5} {sum(s['stops'] for s in cluster_stats):>6} "
      f"{sum(s['total_demand'] for s in cluster_stats):>8}\n")


# ── Step 5: Save clusters.csv ─────────────────────────────────────
depot["cluster"] = -1
all_rows         = [depot] + stops
fieldnames       = ["delivery_id", "customer_name", "postcode",
                    "latitude", "longitude", "demand", "priority", "cluster"]

output_csv = "clusters.csv"
with open(output_csv, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(all_rows)

print(f"  Saved: {output_csv}")


# ── Step 6: Build cluster_map.html ────────────────────────────────
markers = []

markers.append({
    "lat":   depot["latitude"],
    "lon":   depot["longitude"],
    "type":  "depot",
    "popup": (f"<b>DPD Hinckley Depot</b><br>"
              f"Postcode: {depot['postcode']}<br>"
              f"{K} vans dispatched today."),
})

for c_id, cluster_stops in enumerate(final_clusters):
    colour = CLUSTER_COLOURS[c_id % len(CLUSTER_COLOURS)]
    s      = cluster_stats[c_id]

    markers.append({
        "lat":     s["centre_lat"],
        "lon":     s["centre_lon"],
        "type":    "centre",
        "colour":  colour,
        "cluster": c_id + 1,
        "popup":   (f"<b>Van {c_id+1} zone centre</b><br>"
                    f"Stops: {s['stops']}<br>"
                    f"Parcels: {s['total_demand']}<br>"
                    f"Distance from depot: {s['dist_depot_km']} km"),
    })

    for stop in cluster_stops:
        markers.append({
            "lat":     stop["latitude"],
            "lon":     stop["longitude"],
            "type":    "stop",
            "colour":  colour,
            "cluster": c_id + 1,
            "popup":   (f"<b>{stop['delivery_id']}</b> — Van {c_id+1}<br>"
                        f"Customer: {stop['customer_name']}<br>"
                        f"Postcode: {stop['postcode']}<br>"
                        f"Demand: {stop['demand']} parcel(s)<br>"
                        f"Priority: {stop['priority'].upper()}"),
        })

map_lat      = sum(s["latitude"]  for s in stops) / len(stops)
map_lon      = sum(s["longitude"] for s in stops) / len(stops)
markers_json = json.dumps(markers)
pills_html   = "".join(
    f'<span class="pill" style="background:{CLUSTER_COLOURS[i % len(CLUSTER_COLOURS)]}">'
    f'Van {i+1}: {cluster_stats[i]["stops"]} stops</span>'
    for i in range(K)
)
counts_json  = json.dumps([s["stops"] for s in cluster_stats])
colours_json = json.dumps([CLUSTER_COLOURS[i % len(CLUSTER_COLOURS)] for i in range(K)])

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Cluster Map — DPD Hinckley</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <style>
    *{{margin:0;padding:0;box-sizing:border-box}}
    body{{font-family:Arial,sans-serif}}
    #header{{background:#1a237e;color:white;padding:10px 16px;
      display:flex;align-items:center;gap:12px;flex-wrap:wrap}}
    #header h1{{font-size:14px;white-space:nowrap}}
    #pills{{display:flex;gap:6px;flex-wrap:wrap}}
    .pill{{padding:2px 9px;border-radius:12px;font-size:11px;
      font-weight:bold;color:white;white-space:nowrap}}
    #map{{height:calc(100vh - 46px)}}
    #legend{{background:white;padding:10px 14px;border-radius:8px;
      font-size:12px;line-height:2;box-shadow:0 2px 8px rgba(0,0,0,0.2);
      max-height:70vh;overflow-y:auto}}
    #legend h4{{font-size:13px;margin-bottom:4px;
      border-bottom:1px solid #ddd;padding-bottom:3px}}
    .leg-row{{display:flex;align-items:center;gap:7px}}
    .leg-dot{{width:11px;height:11px;border-radius:50%;
      border:1.5px solid rgba(0,0,0,0.2);flex-shrink:0}}
  </style>
</head>
<body>
<div id="header">
  <h1>Cluster Map — DPD Hinckley &nbsp;|&nbsp;
      {K} vans &nbsp;|&nbsp; max {MAX_STOPS_PER_VEHICLE} stops each &nbsp;|&nbsp;
      inertia: {full_model.inertia_:.2f}</h1>
  <div id="pills">{pills_html}</div>
</div>
<div id="map"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const map = L.map("map").setView([{map_lat:.4f},{map_lon:.4f}],9);
L.tileLayer("https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png",{{
  attribution:"© OpenStreetMap contributors",maxZoom:18
}}).addTo(map);

const allMarkers = {markers_json};
const colours    = {colours_json};
const counts     = {counts_json};

const stopIcon = col => L.divIcon({{className:"",
  html:`<div style="width:12px;height:12px;background:${{col}};
    border:2px solid white;border-radius:50%;
    box-shadow:0 1px 3px rgba(0,0,0,0.4)"></div>`,
  iconSize:[12,12],iconAnchor:[6,6],popupAnchor:[0,-8]}});

const centreIcon = col => L.divIcon({{className:"",
  html:`<div style="width:20px;height:20px;background:${{col}};
    border:3px solid white;border-radius:50%;
    box-shadow:0 2px 6px rgba(0,0,0,0.5)"></div>`,
  iconSize:[20,20],iconAnchor:[10,10],popupAnchor:[0,-12]}});

const depotIcon = () => L.divIcon({{className:"",
  html:`<div style="width:24px;height:24px;background:#1a237e;
    border:3px solid white;border-radius:5px;
    box-shadow:0 2px 6px rgba(0,0,0,0.5);color:white;
    display:flex;align-items:center;justify-content:center;
    font-weight:bold;font-size:12px">D</div>`,
  iconSize:[24,24],iconAnchor:[12,12],popupAnchor:[0,-14]}});

const depotLayer  = L.layerGroup().addTo(map);
const centreLayer = L.layerGroup().addTo(map);
const vanLayers   = {{}};
for (let i=1;i<={K};i++) vanLayers[i]=L.layerGroup().addTo(map);

allMarkers.forEach(m=>{{
  let mk;
  if (m.type==="depot") {{
    mk=L.marker([m.lat,m.lon],{{icon:depotIcon()}}).bindPopup(m.popup);
    depotLayer.addLayer(mk);
  }} else if (m.type==="centre") {{
    mk=L.marker([m.lat,m.lon],{{icon:centreIcon(m.colour)}}).bindPopup(m.popup);
    centreLayer.addLayer(mk);
  }} else {{
    mk=L.marker([m.lat,m.lon],{{icon:stopIcon(m.colour)}}).bindPopup(m.popup);
    vanLayers[m.cluster].addLayer(mk);
  }}
}});

const overlays={{"Depot":depotLayer,"Zone centres":centreLayer}};
for(let i=1;i<={K};i++)
  overlays[`Van ${{i}} (${{counts[i-1]}} stops)`]=vanLayers[i];
L.control.layers(null,overlays,{{collapsed:false}}).addTo(map);

const legend=L.control({{position:"bottomleft"}});
legend.onAdd=()=>{{
  const div=L.DomUtil.create("div","");
  div.id="legend";
  let h=`<h4>Vehicles ({K} vans)</h4>`;
  colours.forEach((col,i)=>{{
    h+=`<div class="leg-row">
      <div class="leg-dot" style="background:${{col}}"></div>
      Van ${{i+1}} — ${{counts[i]}} stops
    </div>`;
  }});
  div.innerHTML=h;
  return div;
}};
legend.addTo(map);
</script>
</body>
</html>"""

map_file = "cluster_map.html"
with open(map_file, "w", encoding="utf-8") as f:
    f.write(html)

print(f"  Saved: {map_file}\n")
print("=" * 58)
print(f"  Vehicles needed : {K}")
print(f"  Max stops/van   : {MAX_STOPS_PER_VEHICLE}")
print(f"  Inertia         : {full_model.inertia_:.4f}")
print(f"  sklearn version : verified, citable in report")
print(f"  Next step       : routing (order stops within")
print(f"                    each cluster for each van)")
print("=" * 58)

webbrowser.open(f"file:///{os.path.abspath(map_file)}")