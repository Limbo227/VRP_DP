"""
Route optimisation with OSRM road distances (matrix) + same heuristics as routes.py
------------------------------------------------------------------------------------
Per cluster (van): build OSRM /table distance matrix for [depot + stops], then run
Nearest Neighbour, 2-opt (from NN), and Random-Restart 2-opt using those distances.

Coordinates: data/deliveries.csv
Clusters:     data/clusters2.csv (override with CLUSTERS_CSV env)

Outputs (same shape as routes.py):
  data/routes_osrm_nn.csv
  data/routes_osrm_2opt.csv
  data/routes_osrm_rr2opt.csv
  data/routing_summary_osrm_matrix.txt

Requires: OSRM HTTP server with /table (e.g. http://127.0.0.1:5000)

Usage:
  python osrm_matrix_routes.py
  set CLUSTERS_CSV=...  OSRM_BASE=...  (optional)
"""

from __future__ import annotations

import csv
import json
import math
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from typing import List

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA_DIR = os.path.join(REPO_ROOT, "data")

DELIVERIES_CSV = os.path.join(DATA_DIR, "deliveries.csv")
CLUSTERS_CSV = os.environ.get(
    "CLUSTERS_CSV", os.path.join(DATA_DIR, "clusters3.csv")
)

OSRM_BASE = os.environ.get("OSRM_BASE", "http://127.0.0.1:5000").rstrip("/")
PROFILE = os.environ.get("OSRM_PROFILE", "driving")
# OSRM rejects one /table request if coordinate count exceeds server limit (often 100).
OSRM_MAX_TABLE_COORDS = int(os.environ.get("OSRM_MAX_TABLE_COORDS", "100"))
RANDOM_SEED = 42
RR_RESTARTS = 50

random.seed(RANDOM_SEED)
R = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a))


def load_deliveries_by_id(path: str) -> dict:
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


def load_cluster_assignments(path: str) -> dict:
    m = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["delivery_id"] == "DEPOT":
                continue
            m[row["delivery_id"]] = int(row["cluster"])
    return m


def merge_stops(deliveries_by_id: dict, cluster_by_id: dict):
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


def lonlat(lat: float, lon: float) -> str:
    return f"{lon},{lat}"


def osrm_table_distances_km(points: List[dict]) -> List[List[float]]:
    """
    Full pairwise driving distance matrix (km). OSRM returns metres; null if no route.
    """
    coord_str = ";".join(lonlat(p["latitude"], p["longitude"]) for p in points)
    path = f"/table/v1/{PROFILE}/{coord_str}"
    params = {
        "annotations": "distance",
        "sources": "all",
        "destinations": "all",
    }
    url = f"{OSRM_BASE}{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=180) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if data.get("code") != "Ok":
        raise RuntimeError(f"OSRM table error: {data}")
    raw = data["distances"]
    n = len(points)
    mat: List[List[float]] = []
    for i in range(n):
        row: List[float] = []
        for j in range(n):
            m = raw[i][j]
            if m is None:
                row.append(
                    haversine_km(
                        points[i]["latitude"],
                        points[i]["longitude"],
                        points[j]["latitude"],
                        points[j]["longitude"],
                    )
                )
            else:
                row.append(float(m) / 1000.0)
        mat.append(row)
    return mat


def osrm_table_distances_km_tiled(points: List[dict]) -> List[List[float]]:
    """
    Full N×N driving-distance matrix when N exceeds OSRM's per-request coordinate cap.

    Builds overlapping block requests: consecutive index groups of size ≤ M//2 so that
    any union of two groups has at most M coordinates (default M = OSRM_MAX_TABLE_COORDS).
    """
    n = len(points)
    cap = OSRM_MAX_TABLE_COORDS
    if n <= cap:
        return osrm_table_distances_km(points)

    chunk = max(cap // 2, 1)
    groups: List[List[int]] = []
    i = 0
    while i < n:
        groups.append(list(range(i, min(i + chunk, n))))
        i += chunk

    mat = [[0.0] * n for _ in range(n)]
    for a in range(len(groups)):
        for b in range(a, len(groups)):
            idxs = groups[a] if a == b else groups[a] + groups[b]
            loc_points = [points[j] for j in idxs]
            sub = osrm_table_distances_km(loc_points)
            for li, gi in enumerate(idxs):
                for lj, gj in enumerate(idxs):
                    mat[gi][gj] = sub[li][lj]
    return mat


def pair_km(
    i: int, j: int, mat_km: List[List[float]], points: List[dict]
) -> float:
    v = mat_km[i][j]
    if v is not None and not math.isnan(v) and v >= 0:
        return v
    return haversine_km(
        points[i]["latitude"],
        points[i]["longitude"],
        points[j]["latitude"],
        points[j]["longitude"],
    )


def route_distance_idx(route_idx: List[int], mat_km: List[List[float]], points: List[dict]) -> float:
    total = 0.0
    for a in range(len(route_idx) - 1):
        i, j = route_idx[a], route_idx[a + 1]
        total += pair_km(i, j, mat_km, points)
    return total


def idx_route_to_stops(route_idx: List[int], points: List[dict]) -> List[dict]:
    return [points[i] for i in route_idx]


def nearest_neighbour_osrm(depot: dict, stops: List[dict], mat_km, points: List[dict]):
    """points[0] must be depot; stops are points[1:]. Returns list of dicts [depot,...,depot]."""
    id_to_idx = {points[i]["delivery_id"]: i for i in range(len(points))}
    start = id_to_idx[depot["delivery_id"]]
    unvisited = {id_to_idx[s["delivery_id"]] for s in stops}
    route_idx = [start]
    current = start
    while unvisited:
        best_j = min(unvisited, key=lambda j: pair_km(current, j, mat_km, points))
        route_idx.append(best_j)
        unvisited.remove(best_j)
        current = best_j
    route_idx.append(start)
    return idx_route_to_stops(route_idx, points)


def two_opt_osrm(route: List[dict], mat_km, points: List[dict]) -> List[dict]:
    id_to_idx = {points[i]["delivery_id"]: i for i in range(len(points))}
    route_idx = [id_to_idx[r["delivery_id"]] for r in route]
    best = list(route_idx)
    best_dist = route_distance_idx(best, mat_km, points)
    improved = True
    n = len(best)
    while improved:
        improved = False
        for i in range(1, n - 2):
            for j in range(i + 1, n - 1):
                cand = best[:i] + best[i : j + 1][::-1] + best[j + 1 :]
                d = route_distance_idx(cand, mat_km, points)
                if d < best_dist - 1e-9:
                    best = cand
                    best_dist = d
                    improved = True
    return idx_route_to_stops(best, points)


def random_restart_2opt_osrm(depot: dict, stops: List[dict], mat_km, points: List[dict], restarts=RR_RESTARTS):
    id_to_idx = {points[i]["delivery_id"]: i for i in range(len(points))}
    start = id_to_idx[depot["delivery_id"]]
    best_route = None
    best_dist = float("inf")
    stop_indices = [id_to_idx[s["delivery_id"]] for s in stops]

    for _ in range(restarts):
        shuffled = list(stop_indices)
        random.shuffle(shuffled)
        route_idx = [start] + shuffled + [start]
        improved = two_opt_osrm(idx_route_to_stops(route_idx, points), mat_km, points)
        idx2 = [id_to_idx[r["delivery_id"]] for r in improved]
        dist = route_distance_idx(idx2, mat_km, points)
        if dist < best_dist:
            best_dist = dist
            best_route = improved
    return best_route


def save_routes_csv(path: str, cluster_ids: list, results: dict, algo_key: str, mat_cache: dict):
    fieldnames = [
        "van",
        "stop_order",
        "delivery_id",
        "customer_name",
        "postcode",
        "latitude",
        "longitude",
        "demand",
        "priority",
        "dist_from_prev_km",
        "route_km_so_far",
    ]
    rows = []
    for cid in cluster_ids:
        route = results[cid][algo_key]["route"]
        points = mat_cache[cid]["points"]
        mat_km = mat_cache[cid]["mat"]
        id_to_idx = {points[i]["delivery_id"]: i for i in range(len(points))}
        cum = 0.0
        for order, stop in enumerate(route):
            if order == 0:
                dist_prev = 0.0
            else:
                ia = id_to_idx[route[order - 1]["delivery_id"]]
                ib = id_to_idx[stop["delivery_id"]]
                dist_prev = pair_km(ia, ib, mat_km, points)
                cum += dist_prev
            rows.append(
                {
                    "van": cid,
                    "stop_order": order,
                    "delivery_id": stop["delivery_id"],
                    "customer_name": stop["customer_name"],
                    "postcode": stop["postcode"],
                    "latitude": stop["latitude"],
                    "longitude": stop["longitude"],
                    "demand": stop["demand"],
                    "priority": stop["priority"],
                    "dist_from_prev_km": round(dist_prev, 4),
                    "route_km_so_far": round(cum, 4),
                }
            )
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def main():
    if not os.path.isfile(DELIVERIES_CSV):
        raise SystemExit(f"Missing {DELIVERIES_CSV}")
    if not os.path.isfile(CLUSTERS_CSV):
        raise SystemExit(f"Missing {CLUSTERS_CSV}")

    deliveries = load_deliveries_by_id(DELIVERIES_CSV)
    cluster_by_id = load_cluster_assignments(CLUSTERS_CSV)
    depot, stops, missing = merge_stops(deliveries, cluster_by_id)
    if missing:
        print("WARN: ids in clusters but not in deliveries:", missing[:5], "...")

    clusters = group_by_cluster(stops)
    cluster_ids = sorted(clusters.keys())

    print("=" * 62)
    print("  OSRM matrix + NN / 2-opt / RR-2-opt (road km)")
    print("=" * 62)
    print(f"  OSRM_BASE    : {OSRM_BASE}")
    print(f"  Clusters file: {CLUSTERS_CSV}")
    print(f"  Vans         : {len(cluster_ids)}")
    print()

    results = {}
    mat_cache = {}

    t_mat = 0.0
    t_nn = t_2 = t_rr = 0.0

    for cid in cluster_ids:
        cluster_stops = sorted(clusters[cid], key=lambda s: s["delivery_id"])
        points = [depot] + cluster_stops

        t0 = time.perf_counter()
        try:
            mat_km = osrm_table_distances_km(points)
        except (urllib.error.URLError, urllib.error.HTTPError, RuntimeError) as e:
            print(f"  Van {cid}: OSRM table failed: {e}")
            raise SystemExit(1) from e
        t_mat += time.perf_counter() - t0
        mat_cache[cid] = {"points": points, "mat": mat_km}

        t0 = time.perf_counter()
        route_nn = nearest_neighbour_osrm(depot, cluster_stops, mat_km, points)
        t_nn += time.perf_counter() - t0
        id_to_idx = {points[i]["delivery_id"]: i for i in range(len(points))}
        d_nn = route_distance_idx(
            [id_to_idx[r["delivery_id"]] for r in route_nn], mat_km, points
        )

        t0 = time.perf_counter()
        route_2 = two_opt_osrm(list(route_nn), mat_km, points)
        t_2 += time.perf_counter() - t0
        d_2 = route_distance_idx(
            [id_to_idx[r["delivery_id"]] for r in route_2], mat_km, points
        )

        t0 = time.perf_counter()
        route_rr = random_restart_2opt_osrm(depot, cluster_stops, mat_km, points)
        t_rr += time.perf_counter() - t0
        d_rr = route_distance_idx(
            [id_to_idx[r["delivery_id"]] for r in route_rr], mat_km, points
        )

        results[cid] = {
            "stops": len(cluster_stops),
            "nn": {"route": route_nn, "dist": d_nn},
            "2opt": {"route": route_2, "dist": d_2},
            "rr": {"route": route_rr, "dist": d_rr},
        }
        print(
            f"  Van {cid:<2}  stops={len(cluster_stops):>3}  "
            f"NN {d_nn:>8.2f}  2opt {d_2:>8.2f}  RR {d_rr:>8.2f} km (OSRM road)"
        )

    total_nn = sum(r["nn"]["dist"] for r in results.values())
    total_2 = sum(r["2opt"]["dist"] for r in results.values())
    total_rr = sum(r["rr"]["dist"] for r in results.values())

    print("-" * 62)
    print(
        f"  TOTAL road km  NN: {total_nn:>10.2f}  2opt: {total_2:>10.2f}  RR: {total_rr:>10.2f}"
    )
    print(f"  Table HTTP time: {t_mat:.2f}s  NN: {t_nn:.4f}s  2opt: {t_2:.4f}s  RR: {t_rr:.4f}s")

    out_nn = os.path.join(DATA_DIR, "routes_osrm_nn.csv")
    out_2 = os.path.join(DATA_DIR, "routes_osrm_2opt.csv")
    out_rr = os.path.join(DATA_DIR, "routes_osrm_rr2opt.csv")
    save_routes_csv(out_nn, cluster_ids, results, "nn", mat_cache)
    save_routes_csv(out_2, cluster_ids, results, "2opt", mat_cache)
    save_routes_csv(out_rr, cluster_ids, results, "rr", mat_cache)
    print(f"\n  Saved: {out_nn}")
    print(f"  Saved: {out_2}")
    print(f"  Saved: {out_rr}")

    summary_path = os.path.join(DATA_DIR, "routing_summary_osrm_matrix.txt")
    lines = [
        "=" * 62,
        "  ROUTING SUMMARY — OSRM road distance matrix + heuristics",
        "=" * 62,
        f"\n  Clusters file : {CLUSTERS_CSV}",
        f"  OSRM_BASE     : {OSRM_BASE}",
        f"  Total road km : NN {total_nn:.2f}  2opt {total_2:.2f}  RR {total_rr:.2f}",
        "",
    ]
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"  Saved: {summary_path}")


if __name__ == "__main__":
    main()
