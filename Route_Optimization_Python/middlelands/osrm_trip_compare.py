"""
OSRM Trip vs Haversine heuristics (NN / 2-opt / RR-2-opt)
--------------------------------------------------------
Loads coordinates from data/deliveries.csv and cluster IDs from
data/clusters2.csv, then for each van (cluster):

  1) Calls OSRM /trip/v1/driving/... (round trip, start at depot) to get
     road-optimised visit order + OSRM distance/duration.
  2) Computes the same three TSP heuristics as routes.py on the same stops
     using Haversine (great-circle km).

Writes:
  data/trip_osrm_vs_heuristics.csv   — per-van metrics
  data/trip_osrm_visit_order.csv    — OSRM waypoint order per van

Requires: OSRM HTTP server (e.g. http://127.0.0.1:5000) with /trip enabled.

Usage:
  set OSRM_BASE=http://127.0.0.1:5000   (optional, default below)
  python osrm_trip_compare.py
"""

from __future__ import annotations

import csv
import json
import math
import os
import random
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from typing import List, Tuple

# ── Paths (repo root) ─────────────────────────────────────────────
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA_DIR = os.path.join(REPO_ROOT, "data")
DELIVERIES_CSV = os.path.join(DATA_DIR, "deliveries.csv")
CLUSTERS2_CSV = os.path.join(DATA_DIR, "clusters3.csv")
OUT_COMPARE_CSV = os.path.join(DATA_DIR, "trip_osrm_vs_heuristics.csv")
OUT_ORDER_CSV = os.path.join(DATA_DIR, "trip_osrm_visit_order.csv")

OSRM_BASE = os.environ.get("OSRM_BASE", "http://127.0.0.1:5000").rstrip("/")
PROFILE = os.environ.get("OSRM_PROFILE", "driving")
RANDOM_SEED = 42
RR_RESTARTS = 50

random.seed(RANDOM_SEED)

# ── Haversine + heuristics (same logic as routes.py) ───────────────
R = 6371.0


def haversine(lat1, lon1, lat2, lon2):
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a))


def route_distance(stops):
    total = 0.0
    for i in range(len(stops) - 1):
        total += haversine(
            stops[i]["latitude"],
            stops[i]["longitude"],
            stops[i + 1]["latitude"],
            stops[i + 1]["longitude"],
        )
    return total


def nearest_neighbour(depot, stops):
    unvisited = list(stops)
    route = [depot]
    current = depot
    while unvisited:
        nearest = min(
            unvisited,
            key=lambda s: haversine(
                current["latitude"],
                current["longitude"],
                s["latitude"],
                s["longitude"],
            ),
        )
        route.append(nearest)
        unvisited.remove(nearest)
        current = nearest
    route.append(depot)
    return route


def two_opt(route):
    best = list(route)
    best_dist = route_distance(best)
    improved = True
    n = len(best)
    while improved:
        improved = False
        for i in range(1, n - 2):
            for j in range(i + 1, n - 1):
                new_route = best[:i] + best[i : j + 1][::-1] + best[j + 1 :]
                new_dist = route_distance(new_route)
                if new_dist < best_dist - 1e-10:
                    best = new_route
                    best_dist = new_dist
                    improved = True
    return best


def random_restart_2opt(depot, stops, restarts=RR_RESTARTS):
    best_route = None
    best_dist = float("inf")
    for _ in range(restarts):
        shuffled = list(stops)
        random.shuffle(shuffled)
        initial = [depot] + shuffled + [depot]
        improved = two_opt(initial)
        dist = route_distance(improved)
        if dist < best_dist:
            best_dist = dist
            best_route = improved
    return best_route


# ── Data load: deliveries coords + clusters2 ids ───────────────────
def load_deliveries_by_id(path):
    by_id = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            by_id[row["delivery_id"]] = {
                "delivery_id": row["delivery_id"],
                "customer_name": row.get("customer_name", ""),
                "postcode": row.get("postcode", ""),
                "latitude": float(row["latitude"]),
                "longitude": float(row["longitude"]),
                "demand": int(row["demand"]),
                "priority": row.get("priority", "standard"),
            }
    return by_id


def load_cluster_assignments(path):
    """delivery_id -> cluster int (excludes DEPOT)."""
    m = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["delivery_id"] == "DEPOT":
                continue
            m[row["delivery_id"]] = int(row["cluster"])
    return m


def merge_stops(deliveries_by_id, cluster_by_id):
    depot = deliveries_by_id["DEPOT"]
    stops = []
    missing = []
    for did, cid in cluster_by_id.items():
        if did not in deliveries_by_id:
            missing.append(did)
            continue
        row = dict(deliveries_by_id[did])
        row["cluster"] = cid
        stops.append(row)
    return depot, stops, missing


def group_by_cluster(stops):
    clusters = defaultdict(list)
    for s in stops:
        clusters[s["cluster"]].append(s)
    return clusters


def lonlat(lat, lon):
    return f"{lon},{lat}"


def osrm_trip_request(coordinates_lonlat_semicolon: str) -> dict:
    """GET /trip/v1/{profile}/{coords}?roundtrip=true&source=first"""
    path = f"/trip/v1/{PROFILE}/{coordinates_lonlat_semicolon}"
    params = {
        "roundtrip": "true",
        "source": "first",
        "overview": "false",
        "steps": "false",
    }
    q = urllib.parse.urlencode(params)
    url = f"{OSRM_BASE}{path}?{q}"
    with urllib.request.urlopen(url, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_trip_response(
    data: dict, request_points: List[dict]
) -> Tuple[float, float, List[dict], List[int], float]:
    """
    request_points[0] must be depot; order matches coordinate string.
    Returns (distance_m, duration_s, visit_order_rows, waypoint_indices).
    """
    if data.get("code") != "Ok":
        raise RuntimeError(f"OSRM trip error: {data}")

    trip = data["trips"][0]
    distance_m = trip["distance"]
    duration_s = trip["duration"]

    # Waypoints appear in visit order along the trip; waypoint_index maps to request index.
    visit_indices = [wp["waypoint_index"] for wp in data["waypoints"]]
    visit_order = [request_points[i] for i in visit_indices]

    # Closed tour for Haversine along OSRM order: ... -> back to depot
    depot = request_points[0]
    if visit_indices[0] != 0:
        # rotate so depot first if API ever permutes start
        k = visit_indices.index(0)
        visit_indices = visit_indices[k:] + visit_indices[:k]
        visit_order = [request_points[i] for i in visit_indices]

    haversine_tour = visit_order + [depot]
    haversine_km = route_distance(haversine_tour)

    return distance_m, duration_s, visit_order, visit_indices, haversine_km


def main():
    if not os.path.isfile(DELIVERIES_CSV):
        raise SystemExit(f"Missing {DELIVERIES_CSV}")
    if not os.path.isfile(CLUSTERS2_CSV):
        raise SystemExit(f"Missing {CLUSTERS2_CSV}")

    deliveries = load_deliveries_by_id(DELIVERIES_CSV)
    cluster_by_id = load_cluster_assignments(CLUSTERS2_CSV)
    depot, stops, missing = merge_stops(deliveries, cluster_by_id)
    if missing:
        print("WARN: delivery_ids in clusters2 but not in deliveries.csv:", missing[:10], "...")

    clusters = group_by_cluster(stops)
    cluster_ids = sorted(clusters.keys())

    print("=" * 72)
    print("  OSRM /trip vs Haversine heuristics (NN / 2-opt / RR-2-opt)")
    print("=" * 72)
    print(f"  OSRM_BASE   : {OSRM_BASE}")
    print(f"  PROFILE     : {PROFILE}")
    print(f"  Deliveries  : {DELIVERIES_CSV}")
    print(f"  Clusters    : {CLUSTERS2_CSV}")
    print(f"  Vans        : {len(cluster_ids)}")
    print()

    compare_rows = []
    order_rows = []

    total_osrm_km = 0.0
    total_haversine_osrm_order = 0.0
    total_nn = 0.0
    total_2opt = 0.0
    total_rr = 0.0

    for cid in cluster_ids:
        cluster_stops = clusters[cid]
        # Stable coordinate order for request: depot then stops sorted by id
        ordered = [depot] + sorted(cluster_stops, key=lambda s: s["delivery_id"])
        coord_str = ";".join(lonlat(p["latitude"], p["longitude"]) for p in ordered)

        try:
            data = osrm_trip_request(coord_str)
        except urllib.error.HTTPError as e:
            print(f"  Van {cid}: HTTP error {e.code} — {e.reason}")
            compare_rows.append(
                {
                    "van": cid,
                    "stops": len(cluster_stops),
                    "osrm_ok": False,
                    "osrm_error": str(e),
                    "osrm_distance_km": "",
                    "osrm_duration_min": "",
                    "haversine_along_osrm_order_km": "",
                    "haversine_nn_km": "",
                    "haversine_2opt_km": "",
                    "haversine_rr2opt_km": "",
                }
            )
            continue
        except urllib.error.URLError as e:
            print(f"  Van {cid}: cannot reach OSRM ({e}). Is the server running?")
            raise SystemExit(1) from e
        except Exception as e:
            print(f"  Van {cid}: {e}")
            compare_rows.append(
                {
                    "van": cid,
                    "stops": len(cluster_stops),
                    "osrm_ok": False,
                    "osrm_error": str(e),
                    "osrm_distance_km": "",
                    "osrm_duration_min": "",
                    "haversine_along_osrm_order_km": "",
                    "haversine_nn_km": "",
                    "haversine_2opt_km": "",
                    "haversine_rr2opt_km": "",
                }
            )
            continue

        try:
            dist_m, dur_s, visit_order, visit_idx, hav_osrm_order = parse_trip_response(
                data, ordered
            )
        except RuntimeError as e:
            print(f"  Van {cid}: {e}")
            compare_rows.append(
                {
                    "van": cid,
                    "stops": len(cluster_stops),
                    "osrm_ok": False,
                    "osrm_error": str(e),
                    "osrm_distance_km": "",
                    "osrm_duration_min": "",
                    "haversine_along_osrm_order_km": "",
                    "haversine_nn_km": "",
                    "haversine_2opt_km": "",
                    "haversine_rr2opt_km": "",
                }
            )
            continue

        route_nn = nearest_neighbour(depot, list(cluster_stops))
        route_2opt = two_opt(list(route_nn))
        route_rr = random_restart_2opt(depot, cluster_stops)

        d_nn = route_distance(route_nn)
        d_2 = route_distance(route_2opt)
        d_rr = route_distance(route_rr)

        osrm_km = dist_m / 1000.0
        total_osrm_km += osrm_km
        total_haversine_osrm_order += hav_osrm_order
        total_nn += d_nn
        total_2opt += d_2
        total_rr += d_rr

        compare_rows.append(
            {
                "van": cid,
                "stops": len(cluster_stops),
                "osrm_ok": True,
                "osrm_error": "",
                "osrm_distance_km": round(osrm_km, 3),
                "osrm_duration_min": round(dur_s / 60.0, 2),
                "haversine_along_osrm_order_km": round(hav_osrm_order, 3),
                "haversine_nn_km": round(d_nn, 3),
                "haversine_2opt_km": round(d_2, 3),
                "haversine_rr2opt_km": round(d_rr, 3),
            }
        )

        for seq, row in enumerate(visit_order):
            order_rows.append(
                {
                    "van": cid,
                    "trip_sequence": seq,
                    "waypoint_index_in_request": visit_idx[seq],
                    "delivery_id": row["delivery_id"],
                    "postcode": row.get("postcode", ""),
                }
            )

        print(
            f"  Van {cid:>2}  stops={len(cluster_stops):>3}  "
            f"OSRM {osrm_km:>8.2f} km  {dur_s/60:>6.1f} min  |  "
            f"Hav@OSRM-order {hav_osrm_order:>8.2f} km  |  "
            f"NN {d_nn:>8.2f}  2opt {d_2:>8.2f}  RR {d_rr:>8.2f} km"
        )

    print("-" * 72)
    print(
        f"  TOTAL        OSRM road km: {total_osrm_km:>10.2f}  |  "
        f"Haversine along OSRM order: {total_haversine_osrm_order:>10.2f} km"
    )
    print(
        f"               Haversine NN: {total_nn:>10.2f}  2opt: {total_2opt:>10.2f}  "
        f"RR-2opt: {total_rr:>10.2f} km"
    )
    print()
    print("  Notes:")
    print("    - OSRM km = driving distance on the road network (trip optimisation).")
    print("    - Haversine km = straight-line great-circle (same formulas as routes.py).")
    print("    - 'Haversine along OSRM order' = sum of straight segments in OSRM visit order.")
    print()

    fieldnames = [
        "van",
        "stops",
        "osrm_ok",
        "osrm_error",
        "osrm_distance_km",
        "osrm_duration_min",
        "haversine_along_osrm_order_km",
        "haversine_nn_km",
        "haversine_2opt_km",
        "haversine_rr2opt_km",
    ]
    with open(OUT_COMPARE_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(compare_rows)
    print(f"  Saved: {OUT_COMPARE_CSV}")

    with open(OUT_ORDER_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "van",
                "trip_sequence",
                "waypoint_index_in_request",
                "delivery_id",
                "postcode",
            ],
        )
        w.writeheader()
        w.writerows(order_rows)
    print(f"  Saved: {OUT_ORDER_CSV}")


if __name__ == "__main__":
    main()
