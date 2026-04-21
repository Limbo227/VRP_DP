"""
Delivery Map Visualizer
-----------------------
Reads deliveries.csv and generates an interactive HTML map
using Leaflet.js (loaded from CDN — no pip install needed).

Requirements:
    - Python 3.x  (no installs)
    - deliveries.csv in the same folder
    - A browser to open the output file

Run:
    python visualize_map.py

Output:
    delivery_map.html  — open this in any browser
"""

import csv
import json
import webbrowser
import os

# ── Read the CSV ──────────────────────────────────────────────────
input_file = "deliveries_london.csv"

if not os.path.exists(input_file):
    print(f"ERROR: '{input_file}' not found.")
    print("Run generate_dataset.py first to create it.")
    raise SystemExit(1)

depot     = None
deliveries = []

with open(input_file, newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        row["latitude"]  = float(row["latitude"])
        row["longitude"] = float(row["longitude"])
        row["demand"]    = int(row["demand"])
        if row["delivery_id"] == "DEPOT":
            depot = row
        else:
            deliveries.append(row)

print(f"Loaded {len(deliveries)} delivery stops + depot.")

# ── Map centre — average of all points ───────────────────────────
all_lats = [r["latitude"]  for r in deliveries] + [depot["latitude"]]
all_lons = [r["longitude"] for r in deliveries] + [depot["longitude"]]
centre_lat = sum(all_lats) / len(all_lats)
centre_lon = sum(all_lons) / len(all_lons)

# ── Build marker data for JavaScript ─────────────────────────────
# Each marker: [lat, lon, label, colour, popup_html]
markers = []

# Depot — red star marker
markers.append({
    "lat":   depot["latitude"],
    "lon":   depot["longitude"],
    "label": "DEPOT",
    "type":  "depot",
    "popup": f"""
        <b>🏭 Main Warehouse (Depot)</b><br>
        Postcode: {depot['postcode']}<br>
        All vehicles start and end here.
    """,
})

# Delivery stops — blue for standard, orange for express
for d in deliveries:
    colour = "orange" if d["priority"] == "express" else "blue"
    markers.append({
        "lat":    d["latitude"],
        "lon":    d["longitude"],
        "label":  d["delivery_id"],
        "type":   d["priority"],
        "colour": colour,
        "popup":  f"""
            <b>{d['delivery_id']}</b><br>
            Customer: {d['customer_name']}<br>
            Postcode: {d['postcode']}<br>
            Demand: {d['demand']} parcel(s)<br>
            Priority: <b>{d['priority'].upper()}</b>
        """,
    })

markers_json = json.dumps(markers)

# ── Build the HTML ────────────────────────────────────────────────
# Leaflet.js is loaded from unpkg CDN — no install needed.
# The user's browser fetches it once when they open the file.

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Delivery Map — West Midlands</title>

  <!-- Leaflet CSS -->
  <link rel="stylesheet"
        href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>

  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}

    body {{
      font-family: Arial, sans-serif;
      background: #f4f4f4;
    }}

    #header {{
      background: #1a73e8;
      color: white;
      padding: 12px 20px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      box-shadow: 0 2px 6px rgba(0,0,0,0.2);
    }}

    #header h1 {{ font-size: 18px; font-weight: bold; }}

    #stats {{
      display: flex;
      gap: 20px;
      font-size: 13px;
    }}

    #stats span {{
      background: rgba(255,255,255,0.2);
      padding: 4px 10px;
      border-radius: 12px;
    }}

    #map {{
      height: calc(100vh - 90px);
      width: 100%;
    }}

    #legend {{
      background: white;
      padding: 12px 16px;
      border-radius: 8px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.2);
      font-size: 13px;
      line-height: 1.8;
      min-width: 160px;
    }}

    #legend h4 {{
      margin-bottom: 6px;
      font-size: 14px;
      border-bottom: 1px solid #ddd;
      padding-bottom: 4px;
    }}

    .legend-row {{
      display: flex;
      align-items: center;
      gap: 8px;
    }}

    .legend-dot {{
      width: 12px;
      height: 12px;
      border-radius: 50%;
      border: 2px solid rgba(0,0,0,0.3);
      flex-shrink: 0;
    }}
  </style>
</head>
<body>

<div id="header">
  <h1>📦 Delivery Map — West Midlands</h1>
  <div id="stats">
    <span>🏭 1 Depot</span>
    <span>📍 {len(deliveries)} Stops</span>
    <span>🔵 Standard &amp; 🟠 Express</span>
  </div>
</div>

<div id="map"></div>

<!-- Leaflet JS -->
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>

<script>
  // ── Initialise map ──────────────────────────────────────────────
  const map = L.map("map").setView([{centre_lat}, {centre_lon}], 11);

  // OpenStreetMap tiles — completely free, no API key needed
  L.tileLayer("https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", {{
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 18,
  }}).addTo(map);

  // ── Marker icon factory ─────────────────────────────────────────
  function makeIcon(colour) {{
    // Uses Leaflet's built-in coloured circle markers
    return L.divIcon({{
      className: "",
      html: `<div style="
        width:14px; height:14px;
        background:${{colour}};
        border:2px solid white;
        border-radius:50%;
        box-shadow:0 1px 4px rgba(0,0,0,0.4);
      "></div>`,
      iconSize:   [14, 14],
      iconAnchor: [7, 7],
      popupAnchor:[0, -10],
    }});
  }}

  function makeDepotIcon() {{
    return L.divIcon({{
      className: "",
      html: `<div style="
        width:22px; height:22px;
        background:#e53935;
        border:3px solid white;
        border-radius:4px;
        box-shadow:0 2px 6px rgba(0,0,0,0.5);
        display:flex; align-items:center; justify-content:center;
        font-size:12px;
      ">🏭</div>`,
      iconSize:   [22, 22],
      iconAnchor: [11, 11],
      popupAnchor:[0, -14],
    }});
  }}

  // ── Place markers ───────────────────────────────────────────────
  const markers = {markers_json};

  const deliveryLayer = L.layerGroup();
  const expressLayer  = L.layerGroup();
  const depotLayer    = L.layerGroup();

  markers.forEach(m => {{
    let marker;
    if (m.type === "depot") {{
      marker = L.marker([m.lat, m.lon], {{ icon: makeDepotIcon() }});
      marker.bindPopup(m.popup);
      depotLayer.addLayer(marker);
    }} else if (m.type === "express") {{
      marker = L.marker([m.lat, m.lon], {{ icon: makeIcon("#f57c00") }});
      marker.bindPopup(m.popup);
      expressLayer.addLayer(marker);
    }} else {{
      marker = L.marker([m.lat, m.lon], {{ icon: makeIcon("#1a73e8") }});
      marker.bindPopup(m.popup);
      deliveryLayer.addLayer(marker);
    }}
  }});

  deliveryLayer.addTo(map);
  expressLayer.addTo(map);
  depotLayer.addTo(map);

  // ── Layer toggle control ────────────────────────────────────────
  L.control.layers(null, {{
    "Standard deliveries": deliveryLayer,
    "Express deliveries":  expressLayer,
    "Depot":               depotLayer,
  }}, {{ collapsed: false }}).addTo(map);

  // ── Legend ──────────────────────────────────────────────────────
  const legend = L.control({{ position: "bottomleft" }});
  legend.onAdd = () => {{
    const div = L.DomUtil.create("div", "");
    div.id = "legend";
    div.innerHTML = `
      <h4>Legend</h4>
      <div class="legend-row">
        <div class="legend-dot" style="background:#e53935"></div>
        Depot (warehouse)
      </div>
      <div class="legend-row">
        <div class="legend-dot" style="background:#1a73e8"></div>
        Standard delivery
      </div>
      <div class="legend-row">
        <div class="legend-dot" style="background:#f57c00"></div>
        Express delivery
      </div>
    `;
    return div;
  }};
  legend.addTo(map);

</script>
</body>
</html>
"""

# ── Write the HTML file ───────────────────────────────────────────
output_file = "delivery_map.html"
with open(output_file, "w", encoding="utf-8") as f:
    f.write(html)

print(f"Map saved to: {output_file}")
print("Opening in your browser...\n")
print("What you will see:")
print("  🔴 Red square  = Depot (warehouse)")
print("  🔵 Blue dot    = Standard delivery stop")
print("  🟠 Orange dot  = Express delivery stop")
print("  Click any marker for customer details.")
print("  Use the top-right toggle to show/hide layers.")

# Try to open automatically — works on most machines
webbrowser.open(f"file:///{os.path.abspath(output_file)}")
