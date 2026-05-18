# VRP OSRM map UI

Upload `deliveries.csv`, cluster with k-means (same idea as `Route_Optimization_Python/middlelands/cluster2.py`), build per-van routes using OSRM `/table` + NN → 2-opt (`osrm_matrix_routes.py`), then draw **OSRM `/route`** polylines on a Leaflet map.

## Prerequisites

- **Python 3.10+** with `numpy`, `scikit-learn`, FastAPI stack (see `server/requirements.txt`).
- **Node.js 18+** for the Vite UI.
- **OSRM HTTP server** reachable from the browser host (usually `http://127.0.0.1:5000`). CORS is enabled on the API for local dev; OSRM itself must allow your origin if you call it from the browser (the UI only talks to this Python API; the API calls OSRM).

## 1) Backend (FastAPI)

```powershell
cd d:\VS-Projects\VRP\frontend\server
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

## 2) Frontend (Vite)

```powershell
cd d:\VS-Projects\VRP\frontend
npm install
npm run dev
```

Open the URL Vite prints (e.g. `http://127.0.0.1:5173`). The dev server proxies `/api` to `http://127.0.0.1:8000`.

**If the UI shows an error when you click “Cluster & build routes”:** the API must be running **before** Vite; otherwise the proxy cannot connect and you will see **503** (with a clear JSON message) or an older **500** from the proxy. Start `uvicorn` first, then `npm run dev`.

## CSV format

Same shape as `data/deliveries.csv`:

- Header: at least `delivery_id`, `latitude`, `longitude`, `demand` (optional: `customer_name`, `postcode`, `priority`, `quality`).
- Exactly one row with `delivery_id` = `DEPOT` (case-insensitive), depot coordinates, `demand` 0.

## Turn-by-turn (OSRM)

The UI can request OSRM **`/route` with `steps=true`**. Each leg’s **steps** include `maneuver` (type, modifier, location), street `name`, distance, and duration — the same kind of data real navigation stacks use; voice prompts and rerouting would be extra layers on top.

- Leave **“Request OSRM steps=true”** checked (default) to fill the per-van turn list. Click any step to **pan/zoom** the map to that maneuver point.
- Uncheck it for a slightly smaller OSRM response when you only care about the line on the map.

## Production build

```powershell
cd frontend
npm run build
```

Static files land in `frontend/dist`. Serve them behind any static host; keep the API on the same origin or set a full `VITE_API_BASE` if you add that later.
