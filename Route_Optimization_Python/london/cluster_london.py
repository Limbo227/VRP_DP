"""
K-Means Clustering — DPD Hinckley Delivery Routes
--------------------------------------------------
Reads deliveries.csv and groups stops into K clusters.
Each cluster = one vehicle's delivery zone for the day.

No pip installs required. Uses only Python built-in libraries.

How it works:
    1. Pick K random stops as starting cluster centres
    2. Assign every stop to its nearest centre (by road distance)
    3. Recalculate each centre as the average lat/lon of its group
    4. Repeat steps 2-3 until nothing changes
    5. Save results to clusters.csv and generate a map

Run:
    python cluster.py

Output:
    clusters.csv        — original data + cluster column added
    cluster_map.html    — interactive map coloured by cluster
"""

import csv
import math
import random
import json
import os
import webbrowser

# ── Config ────────────────────────────────────────────────────────
K              = 11     # number of vehicles / clusters
MAX_ITERATIONS = 300   # safety cap — algorithm usually converges <20
RANDOM_SEED    = 42

random.seed(RANDOM_SEED)

# ── Cluster colours for the map (one per vehicle) ─────────────────
CLUSTER_COLOURS = [
    "#e53935",   # red
    "#1e88e5",   # blue
    "#43a047",   # green
    "#fb8c00",   # orange
    "#8e24aa",   # purple
    "#00acc1",   # cyan
    "#f4511e",   # deep orange
    "#6d4c41",   # brown
    "#546e7a",   # blue grey
    "#c0ca33",   # lime
]


# ── Distance function ─────────────────────────────────────────────
def haversine(lat1, lon1, lat2, lon2):
    """
    Straight-line distance between two lat/lon points in kilometres.
    Uses the Haversine formula — standard for geographic coordinates.
    Note: this is as-the-crow-flies, not road distance.
    Road distance is used in the routing stage (next step).
    """
    R = 6371.0  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


# ── Step 1: Load the dataset ──────────────────────────────────────
input_file = "deliveries_london.csv"

if not os.path.exists(input_file):
    print(f"ERROR: '{input_file}' not found.")
    print("Run generate_dataset.py first.")
    raise SystemExit(1)

depot     = None
stops     = []   # list of dicts, one per delivery stop

with open(input_file, newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        row["latitude"]  = float(row["latitude"])
        row["longitude"] = float(row["longitude"])
        row["demand"]    = int(row["demand"])
        if row["delivery_id"] == "DEPOT":
            depot = row
        else:
            stops.append(row)

n = len(stops)
print("=" * 56)
print("  K-Means Clustering — DPD Hinckley")
print("=" * 56)
print(f"\n  Depot     : {depot['postcode']}")
print(f"  Stops     : {n}")
print(f"  Vehicles  : {K}  (K = {K})")
print(f"  Seed      : {RANDOM_SEED}\n")

if K > n:
    print(f"ERROR: K ({K}) cannot be greater than number of stops ({n}).")
    raise SystemExit(1)


# ── Step 2: K-Means algorithm ─────────────────────────────────────

def assign_to_clusters(stops, centres):
    """
    Assign every stop to its nearest centre.
    Returns a list of cluster indices (one per stop).
    """
    assignments = []
    for stop in stops:
        distances = [
            haversine(stop["latitude"], stop["longitude"], c[0], c[1])
            for c in centres
        ]
        assignments.append(distances.index(min(distances)))
    return assignments


def recalculate_centres(stops, assignments, k):
    """
    Move each centre to the average lat/lon of all stops in its cluster.
    If a cluster ends up empty (rare), pick a random stop as its new centre
    to avoid a dead cluster.
    """
    new_centres = []
    for cluster_id in range(k):
        members = [stops[i] for i, a in enumerate(assignments) if a == cluster_id]
        if members:
            avg_lat = sum(s["latitude"]  for s in members) / len(members)
            avg_lon = sum(s["longitude"] for s in members) / len(members)
            new_centres.append((avg_lat, avg_lon))
        else:
            # Empty cluster — reinitialise to a random stop
            fallback = random.choice(stops)
            new_centres.append((fallback["latitude"], fallback["longitude"]))
    return new_centres


def kmeans(stops, k, max_iterations):
    """
    Full K-Means loop.
    Returns final assignments list and cluster centres.
    """
    # Initialise centres by picking K random stops (K-Means++ would be
    # better but plain random is fine for this project size)
    seed_stops   = random.sample(stops, k)
    centres      = [(s["latitude"], s["longitude"]) for s in seed_stops]
    assignments  = assign_to_clusters(stops, centres)

    for iteration in range(1, max_iterations + 1):
        new_centres    = recalculate_centres(stops, assignments, k)
        new_assignments = assign_to_clusters(stops, new_centres)

        if new_assignments == assignments:
            print(f"  Converged after {iteration} iteration(s).\n")
            return new_assignments, new_centres

        centres    = new_centres
        assignments = new_assignments

    print(f"  Reached max iterations ({max_iterations}) without full convergence.")
    print("  Result is still usable — try increasing MAX_ITERATIONS.\n")
    return assignments, centres


# Run it
assignments, centres = kmeans(stops, K, MAX_ITERATIONS)


# ── Step 3: Attach cluster IDs back to stops ──────────────────────
for i, stop in enumerate(stops):
    stop["cluster"] = assignments[i]


# ── Step 4: Print summary ─────────────────────────────────────────
cluster_stats = []
for c in range(K):
    members       = [s for s in stops if s["cluster"] == c]
    total_demand  = sum(s["demand"] for s in members)
    centre_lat, centre_lon = centres[c]

    # Average distance from depot to cluster centre — rough proxy
    # for how far this vehicle travels from base
    dist_from_depot = haversine(
        depot["latitude"], depot["longitude"],
        centre_lat, centre_lon
    )

    cluster_stats.append({
        "id":            c + 1,
        "stops":         len(members),
        "total_demand":  total_demand,
        "centre_lat":    round(centre_lat, 4),
        "centre_lon":    round(centre_lon, 4),
        "dist_depot_km": round(dist_from_depot, 1),
    })

print("  Cluster summary:")
print(f"  {'Van':<5} {'Stops':>6} {'Parcels':>8} {'Dist from depot':>16}")
print(f"  {'-'*40}")
for s in cluster_stats:
    bar = "█" * s["stops"]
    print(f"  Van {s['id']:<2} {s['stops']:>6} {s['total_demand']:>8} "
          f"  {s['dist_depot_km']:>8.1f} km    {bar}")

total_stops   = sum(s["stops"]        for s in cluster_stats)
total_parcels = sum(s["total_demand"] for s in cluster_stats)
print(f"  {'-'*40}")
print(f"  {'Total':<5} {total_stops:>6} {total_parcels:>8}\n")


# ── Step 5: Save clusters.csv ─────────────────────────────────────
output_csv = "clusters.csv"
fieldnames = ["delivery_id", "customer_name", "postcode",
              "latitude", "longitude", "demand", "priority", "cluster"]

# Write depot first (cluster = -1 means it belongs to no cluster)
depot["cluster"] = -1
all_rows = [depot] + stops

with open(output_csv, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(all_rows)

print(f"  Saved: {output_csv}")


# ── Step 6: Generate cluster_map.html ─────────────────────────────
# Build marker data for Leaflet
markers = []

# Depot marker
markers.append({
    "lat":    depot["latitude"],
    "lon":    depot["longitude"],
    "type":   "depot",
    "popup":  f"<b>DPD Hinckley Depot</b><br>Postcode: {depot['postcode']}<br>All vans start and end here.",
    "colour": "#333333",
})

# Cluster centre markers (shown as larger circles)
for c, (clat, clon) in enumerate(centres):
    markers.append({
        "lat":    clat,
        "lon":    clon,
        "type":   "centre",
        "label":  f"Van {c+1} zone centre",
        "colour": CLUSTER_COLOURS[c % len(CLUSTER_COLOURS)],
        "popup":  (f"<b>Van {c+1} zone centre</b><br>"
                   f"Stops: {cluster_stats[c]['stops']}<br>"
                   f"Parcels: {cluster_stats[c]['total_demand']}<br>"
                   f"Dist from depot: {cluster_stats[c]['dist_depot_km']} km"),
    })

# Delivery stop markers
for stop in stops:
    c      = stop["cluster"]
    colour = CLUSTER_COLOURS[c % len(CLUSTER_COLOURS)]
    markers.append({
        "lat":    stop["latitude"],
        "lon":    stop["longitude"],
        "type":   "stop",
        "colour": colour,
        "cluster": c + 1,
        "popup":  (f"<b>{stop['delivery_id']}</b> — Van {c+1}<br>"
                   f"Customer: {stop['customer_name']}<br>"
                   f"Postcode: {stop['postcode']}<br>"
                   f"Demand: {stop['demand']} parcel(s)<br>"
                   f"Priority: {stop['priority'].upper()}"),
    })

# Map centre
all_lats = [s["latitude"]  for s in stops]
all_lons = [s["longitude"] for s in stops]
map_lat  = sum(all_lats) / len(all_lats)
map_lon  = sum(all_lons) / len(all_lons)

markers_json = json.dumps(markers)
colours_json = json.dumps(
    {str(i+1): CLUSTER_COLOURS[i % len(CLUSTER_COLOURS)] for i in range(K)}
)

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Cluster Map — DPD Hinckley</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <style>
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{ font-family: Arial, sans-serif; }}
    #header {{
      background:#1a237e; color:white;
      padding:10px 18px;
      display:flex; align-items:center; justify-content:space-between;
    }}
    #header h1 {{ font-size:16px; }}
    #pills {{ display:flex; gap:8px; flex-wrap:wrap; }}
    .pill {{
      padding:3px 10px; border-radius:12px;
      font-size:12px; font-weight:bold; color:white;
    }}
    #map {{ height: calc(100vh - 46px); }}
    #legend {{
      background:white; padding:10px 14px;
      border-radius:8px; font-size:12px;
      box-shadow:0 2px 8px rgba(0,0,0,0.2);
      line-height:2;
    }}
    #legend h4 {{ font-size:13px; margin-bottom:4px;
                  border-bottom:1px solid #ddd; padding-bottom:3px; }}
    .leg-row {{ display:flex; align-items:center; gap:7px; }}
    .leg-dot {{ width:11px; height:11px; border-radius:50%;
                border:1.5px solid rgba(0,0,0,0.25); flex-shrink:0; }}
    .leg-sq  {{ width:11px; height:11px; border-radius:2px;
                border:1.5px solid rgba(0,0,0,0.25); flex-shrink:0; }}
  </style>
</head>
<body>
<div id="header">
  <h1>K-Means Clustering — DPD Hinckley &nbsp;|&nbsp; K = {K} vehicles</h1>
  <div id="pills">
    {''.join(
        f'<span class="pill" style="background:{CLUSTER_COLOURS[i % len(CLUSTER_COLOURS)]}">'
        f'Van {i+1}: {cluster_stats[i]["stops"]} stops</span>'
        for i in range(K)
    )}
  </div>
</div>
<div id="map"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const map = L.map("map").setView([{map_lat}, {map_lon}], 9);
L.tileLayer("https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", {{
  attribution: "© OpenStreetMap contributors", maxZoom: 18
}}).addTo(map);

const markers  = {markers_json};
const colours  = {colours_json};

function stopIcon(colour) {{
  return L.divIcon({{
    className: "",
    html: `<div style="width:12px;height:12px;background:${{colour}};
           border:2px solid white;border-radius:50%;
           box-shadow:0 1px 3px rgba(0,0,0,0.4)"></div>`,
    iconSize:[12,12], iconAnchor:[6,6], popupAnchor:[0,-8]
  }});
}}

function centreIcon(colour) {{
  return L.divIcon({{
    className: "",
    html: `<div style="width:18px;height:18px;background:${{colour}};
           border:3px solid white;border-radius:50%;
           box-shadow:0 2px 6px rgba(0,0,0,0.5);
           opacity:0.85"></div>`,
    iconSize:[18,18], iconAnchor:[9,9], popupAnchor:[0,-12]
  }});
}}

function depotIcon() {{
  return L.divIcon({{
    className: "",
    html: `<div style="width:22px;height:22px;background:#1a237e;
           border:3px solid white;border-radius:4px;
           box-shadow:0 2px 6px rgba(0,0,0,0.5);
           display:flex;align-items:center;justify-content:center;
           font-size:13px">D</div>`,
    iconSize:[22,22], iconAnchor:[11,11], popupAnchor:[0,-14]
  }});
}}

// Layer groups — one per van + depot + centres
const depotLayer   = L.layerGroup().addTo(map);
const centreLayer  = L.layerGroup().addTo(map);
const vanLayers    = {{}};
for (let i = 1; i <= {K}; i++) {{
  vanLayers[i] = L.layerGroup().addTo(map);
}}

markers.forEach(m => {{
  let marker;
  if (m.type === "depot") {{
    marker = L.marker([m.lat, m.lon], {{icon: depotIcon()}});
    marker.bindPopup(m.popup);
    depotLayer.addLayer(marker);
  }} else if (m.type === "centre") {{
    marker = L.marker([m.lat, m.lon], {{icon: centreIcon(m.colour)}});
    marker.bindPopup(m.popup);
    centreLayer.addLayer(marker);
  }} else {{
    marker = L.marker([m.lat, m.lon], {{icon: stopIcon(m.colour)}});
    marker.bindPopup(m.popup);
    vanLayers[m.cluster].addLayer(marker);
  }}
}});

// Layer control
const overlays = {{"Depot": depotLayer, "Cluster centres": centreLayer}};
for (let i = 1; i <= {K}; i++) {{
  overlays[`Van ${{i}} stops`] = vanLayers[i];
}}
L.control.layers(null, overlays, {{collapsed: false}}).addTo(map);

// Legend
const legend = L.control({{position:"bottomleft"}});
legend.onAdd = () => {{
  const div = L.DomUtil.create("div","");
  div.id = "legend";
  let html = "<h4>Vehicles</h4>";
  for (let i = 1; i <= {K}; i++) {{
    const col = colours[String(i)];
    html += `<div class="leg-row">
      <div class="leg-dot" style="background:${{col}}"></div>
      Van ${{i}}
    </div>`;
  }}
  html += `<div class="leg-row" style="margin-top:6px">
    <div class="leg-sq" style="background:#1a237e;border-radius:2px"></div>
    Depot
  </div>`;
  html += `<div class="leg-row">
    <div class="leg-dot" style="background:#aaa"></div>
    Zone centre
  </div>`;
  div.innerHTML = html;
  return div;
}};
legend.addTo(map);
</script>
</body>
</html>"""

map_file = "cluster_map.html"
with open(map_file, "w", encoding="utf-8") as f:
    f.write(html)

print(f"  Saved: {map_file}")
print()
print("=" * 56)
print("  Done. Next steps:")
print("  1. Open cluster_map.html in your browser")
print("  2. Each colour = one vehicle's delivery zone")
print("  3. Adjust K at the top of this file to try")
print("     different numbers of vehicles")
print("  4. Run cluster.py again — routing comes next")
print("=" * 56)

webbrowser.open(f"file:///{os.path.abspath(map_file)}")