"""
VRP frontend API: upload deliveries CSV → cluster → OSRM matrix heuristics → route geometry.
"""
from __future__ import annotations

import csv
import io
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parents[2]
MIDDLELANDS = ROOT / "Route_Optimization_Python" / "middlelands"
sys.path.insert(0, str(MIDDLELANDS))
import osrm_matrix_routes as mat  # noqa: E402

from clustering import cluster_deliveries  # noqa: E402
from osrm_routes import route_metrics, straight_line_geometry  # noqa: E402

CLUSTER_COLORS = [
    "#e53935",
    "#1e88e5",
    "#43a047",
    "#fb8c00",
    "#8e24aa",
    "#00acc1",
    "#f4511e",
    "#6d4c41",
    "#546e7a",
    "#c0ca33",
    "#d81b60",
    "#3949ab",
    "#00897b",
    "#fdd835",
    "#5e35b1",
]

app = FastAPI(title="VRP OSRM Frontend API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def parse_deliveries_csv(text: str) -> tuple[dict, List[dict]]:
    f = io.StringIO(text)
    reader = csv.DictReader(f)
    if not reader.fieldnames:
        raise ValueError("CSV has no header row")

    required = {"delivery_id", "latitude", "longitude", "demand"}
    header_set = {h.strip() for h in reader.fieldnames}
    missing = required - header_set
    if missing:
        raise ValueError(f"CSV missing columns: {sorted(missing)}")

    depot: Optional[dict] = None
    stops: List[dict] = []
    for raw in reader:
        row = {
            (k or "").strip(): (v.strip() if isinstance(v, str) else v)
            for k, v in raw.items()
        }
        did = str(row.get("delivery_id", "")).strip()
        if not did:
            continue
        if did.upper() == "DEPOT":
            rec = {
                "delivery_id": "DEPOT",
                "customer_name": row.get("customer_name") or "",
                "postcode": row.get("postcode") or "",
                "latitude": float(row["latitude"]),
                "longitude": float(row["longitude"]),
                "demand": int(float(row["demand"])),
                "priority": (row.get("priority") or "depot").strip() or "depot",
            }
            if depot is not None:
                raise ValueError("Multiple DEPOT rows; keep exactly one.")
            depot = rec
        else:
            stops.append(
                {
                    "delivery_id": did,
                    "customer_name": row.get("customer_name") or "",
                    "postcode": row.get("postcode") or "",
                    "latitude": float(row["latitude"]),
                    "longitude": float(row["longitude"]),
                    "demand": int(float(row["demand"])),
                    "priority": (row.get("priority") or "standard").strip()
                    or "standard",
                }
            )

    if depot is None:
        raise ValueError(
            "No DEPOT row found. Add one row with delivery_id=DEPOT (depot lat/lon, demand 0)."
        )
    if not stops:
        raise ValueError("No delivery stops after DEPOT.")
    return depot, stops


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/process")
async def process(
    file: UploadFile = File(...),
    osrm_base: str = Form("http://127.0.0.1:5000"),
    osrm_profile: str = Form("driving"),
    max_stops_per_vehicle: int = Form(20),
    include_turns: str = Form("true"),
) -> dict[str, Any]:
    want_turns = str(include_turns).strip().lower() in ("1", "true", "yes", "on")
    try:
        return await _process_impl(
            file, osrm_base, osrm_profile, max_stops_per_vehicle, want_turns
        )
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(
            500, f"{type(e).__name__}: {e}"
        ) from e


async def _process_impl(
    file: UploadFile,
    osrm_base: str,
    osrm_profile: str,
    max_stops_per_vehicle: int,
    include_turns: bool,
) -> dict[str, Any]:
    if max_stops_per_vehicle < 2 or max_stops_per_vehicle > 100:
        raise HTTPException(400, "max_stops_per_vehicle must be between 2 and 100")

    raw_bytes = await file.read()
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise HTTPException(400, f"File must be UTF-8: {e}") from e

    try:
        depot, stops = parse_deliveries_csv(text)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    clusters, inertia = cluster_deliveries(stops, max_stops_per_vehicle)
    osrm_base = osrm_base.rstrip("/")

    vans: List[dict] = []
    total_matrix_km = 0.0
    total_road_km = 0.0
    total_duration_s = 0.0
    warnings: List[str] = []

    for cid, cluster_stops in enumerate(clusters):
        color = CLUSTER_COLORS[cid % len(CLUSTER_COLORS)]
        sorted_stops = sorted(cluster_stops, key=lambda s: s["delivery_id"])
        points = [depot] + sorted_stops

        try:
            mat_km = mat.osrm_table_distances_km(points)
        except Exception as e:
            raise HTTPException(
                502,
                f"OSRM /table failed for van {cid}: {e}. Check OSRM_BASE and server.",
            ) from e

        route_nn = mat.nearest_neighbour_osrm(depot, sorted_stops, mat_km, points)
        route = mat.two_opt_osrm(list(route_nn), mat_km, points)

        id_to_idx = {points[i]["delivery_id"]: i for i in range(len(points))}
        matrix_km = mat.route_distance_idx(
            [id_to_idx[r["delivery_id"]] for r in route], mat_km, points
        )
        total_matrix_km += float(matrix_km)

        dist_km, dur_s, geom, turns = route_metrics(
            osrm_base, osrm_profile, route, include_steps=include_turns
        )
        turns_out: List[dict] = list(turns) if turns else []
        if geom is None:
            warnings.append(
                f"Van {cid}: OSRM /route geometry failed; using straight-line fallback."
            )
            geom = straight_line_geometry(route)
            turns_out = []
            if dist_km is None:
                dist_km = matrix_km
            if dur_s is None:
                dur_s = 0.0
        else:
            if dist_km is None:
                dist_km = matrix_km
            if dur_s is None:
                dur_s = 0.0

        total_road_km += float(dist_km)
        total_duration_s += float(dur_s)

        stop_payload = []
        for s in sorted_stops:
            stop_payload.append(
                {
                    "delivery_id": s["delivery_id"],
                    "customer_name": s["customer_name"],
                    "postcode": s["postcode"],
                    "latitude": float(s["latitude"]),
                    "longitude": float(s["longitude"]),
                    "demand": int(s["demand"]),
                    "priority": s["priority"],
                    "cluster": cid,
                }
            )

        order_ids = [r["delivery_id"] for r in route]
        vans.append(
            {
                "id": cid,
                "label": f"Van {cid + 1}",
                "color": color,
                "stops": stop_payload,
                "visitOrder": order_ids,
                "distanceMatrixKm": float(round(float(matrix_km), 3)),
                "distanceRouteKm": float(round(float(dist_km), 3)),
                "durationSec": float(round(float(dur_s), 1)),
                "geometry": geom,
                "turns": turns_out,
            }
        )

    return {
        "depot": {
            "delivery_id": depot["delivery_id"],
            "customer_name": depot["customer_name"],
            "postcode": depot["postcode"],
            "latitude": float(depot["latitude"]),
            "longitude": float(depot["longitude"]),
        },
        "vans": vans,
        "summary": {
            "totalStops": len(stops),
            "vehicleCount": len(vans),
            "kmeansInertia": float(round(float(inertia), 4)),
            "sumDistanceMatrixKm": float(round(float(total_matrix_km), 3)),
            "sumDistanceRouteKm": float(round(float(total_road_km), 3)),
            "sumDurationSec": float(round(float(total_duration_s), 1)),
            "osrmBase": osrm_base,
            "osrmProfile": osrm_profile,
            "maxStopsPerVehicle": max_stops_per_vehicle,
            "includeTurns": include_turns,
        },
        "warnings": warnings,
    }
