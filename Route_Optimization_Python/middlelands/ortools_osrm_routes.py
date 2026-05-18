"""
OR-Tools routing on OSRM road-distance matrix (per van / cluster)
-----------------------------------------------------------------
For each van: fetch OSRM /table (driving distance km), then solve a one-vehicle
round-trip TSP with Google OR-Tools.

  1) greedy  — PATH_CHEAPEST_ARC, first solution only (NN-like baseline)
  2) gls     — + GUIDED_LOCAL_SEARCH
  3) sa      — + SIMULATED_ANNEALING
  4) tabu    — + TABU_SEARCH

Requires: OSRM on OSRM_BASE (default http://127.0.0.1:5000), ortools package.

Usage (repo root, OSRM running):
  python Route_Optimization_Python/middlelands/ortools_osrm_routes.py

Env:
  CLUSTERS_CSV, OSRM_BASE, ORTOOLS_TIME_LIMIT (seconds per van for metaheuristics, default 10)
"""

from __future__ import annotations

import csv
import os
import time
import urllib.error
from typing import List, Optional, Tuple

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

import osrm_matrix_routes as mat

REPO_ROOT = mat.REPO_ROOT
DATA_DIR = mat.DATA_DIR

DELIVERIES_CSV = mat.DELIVERIES_CSV
CLUSTERS_CSV = os.environ.get(
    "CLUSTERS_CSV", os.path.join(DATA_DIR, "clusters3.csv")
)

ORTOOLS_TIME_LIMIT = int(os.environ.get("ORTOOLS_TIME_LIMIT", "10"))

# Output CSVs (same columns as routes_osrm_*.csv)
OUT_GREEDY = os.path.join(DATA_DIR, "routes_ortools_greedy.csv")
OUT_GLS = os.path.join(DATA_DIR, "routes_ortools_gls.csv")
OUT_SA = os.path.join(DATA_DIR, "routes_ortools_sa.csv")
OUT_TABU = os.path.join(DATA_DIR, "routes_ortools_tabu.csv")
OUT_COMPARE = os.path.join(DATA_DIR, "ortools_osrm_summary.csv")
OUT_TXT = os.path.join(DATA_DIR, "routing_summary_ortools.txt")

FS = routing_enums_pb2.FirstSolutionStrategy
LS = routing_enums_pb2.LocalSearchMetaheuristic

CONFIGS = [
    ("greedy", FS.PATH_CHEAPEST_ARC, None, 0, 1),
    ("gls", FS.PATH_CHEAPEST_ARC, LS.GUIDED_LOCAL_SEARCH, ORTOOLS_TIME_LIMIT, None),
    ("sa", FS.PATH_CHEAPEST_ARC, LS.SIMULATED_ANNEALING, ORTOOLS_TIME_LIMIT, None),
    ("tabu", FS.PATH_CHEAPEST_ARC, LS.TABU_SEARCH, ORTOOLS_TIME_LIMIT, None),
]


def solve_tsp_ortools(
    mat_km: List[List[float]],
    first_solution: int,
    local_search: Optional[int],
    time_limit_sec: int,
    solution_limit: Optional[int],
) -> Tuple[Optional[List[int]], Optional[float]]:
    """
    Single-vehicle round trip; node 0 = depot.
    Returns (node indices in visit order including return to depot, total km).
    """
    n = len(mat_km)
    if n < 2:
        return [0, 0], 0.0

    manager = pywrapcp.RoutingIndexManager(n, 1, 0)
    routing = pywrapcp.RoutingModel(manager)

    def distance_callback(from_index: int, to_index: int) -> int:
        i = manager.IndexToNode(from_index)
        j = manager.IndexToNode(to_index)
        return int(round(mat_km[i][j] * 1000))

    cb_idx = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(cb_idx)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = first_solution
    if local_search is not None:
        params.local_search_metaheuristic = local_search
    if time_limit_sec > 0:
        params.time_limit.seconds = time_limit_sec
    if solution_limit is not None:
        params.solution_limit = solution_limit

    solution = routing.SolveWithParameters(params)
    if solution is None:
        return None, None

    route_idx: List[int] = []
    index = routing.Start(0)
    while not routing.IsEnd(index):
        route_idx.append(manager.IndexToNode(index))
        index = solution.Value(routing.NextVar(index))
    route_idx.append(manager.IndexToNode(index))

    total_km = solution.ObjectiveValue() / 1000.0
    return route_idx, total_km


def route_idx_to_stops(route_idx: List[int], points: List[dict]) -> List[dict]:
    return [points[i] for i in route_idx]


def save_routes_csv(
    path: str,
    cluster_ids: list,
    results: dict,
    algo_key: str,
    mat_cache: dict,
) -> None:
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
                dist_prev = mat.pair_km(ia, ib, mat_km, points)
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


def main() -> None:
    if not os.path.isfile(DELIVERIES_CSV):
        raise SystemExit(f"Missing {DELIVERIES_CSV}")
    if not os.path.isfile(CLUSTERS_CSV):
        raise SystemExit(f"Missing {CLUSTERS_CSV}")

    deliveries = mat.load_deliveries_by_id(DELIVERIES_CSV)
    cluster_by_id = mat.load_cluster_assignments(CLUSTERS_CSV)
    depot, stops, missing = mat.merge_stops(deliveries, cluster_by_id)
    if missing:
        print("WARN: ids in clusters but not in deliveries:", missing[:5], "...")

    clusters = mat.group_by_cluster(stops)
    cluster_ids = sorted(clusters.keys())

    print("=" * 72)
    print("  OR-Tools on OSRM road matrix (PATH_CHEAPEST_ARC + metaheuristics)")
    print("=" * 72)
    print(f"  OSRM_BASE           : {mat.OSRM_BASE}")
    print(f"  Clusters file       : {CLUSTERS_CSV}")
    print(f"  Vans                : {len(cluster_ids)}")
    print(f"  Meta time limit/van : {ORTOOLS_TIME_LIMIT}s")
    print()

    results: dict = {}
    mat_cache: dict = {}
    t_mat = 0.0
    t_solve = {name: 0.0 for name, *_ in CONFIGS}

    for cid in cluster_ids:
        cluster_stops = sorted(clusters[cid], key=lambda s: s["delivery_id"])
        points = [depot] + cluster_stops

        t0 = time.perf_counter()
        try:
            if len(points) > mat.OSRM_MAX_TABLE_COORDS:
                mat_km = mat.osrm_table_distances_km_tiled(points)
            else:
                mat_km = mat.osrm_table_distances_km(points)
        except (urllib.error.URLError, urllib.error.HTTPError, RuntimeError) as e:
            print(f"  Van {cid}: OSRM table failed: {e}")
            raise SystemExit(1) from e
        t_mat += time.perf_counter() - t0
        mat_cache[cid] = {"points": points, "mat": mat_km}

        results[cid] = {"stops": len(cluster_stops)}
        line_parts = [f"  Van {cid:<2}  stops={len(cluster_stops):>3}"]

        for name, fs, ls, tlim, slimit in CONFIGS:
            t0 = time.perf_counter()
            route_idx, dist_km = solve_tsp_ortools(mat_km, fs, ls, tlim, slimit)
            t_solve[name] += time.perf_counter() - t0

            if route_idx is None:
                print(f"  Van {cid}: OR-Tools ({name}) found no solution")
                raise SystemExit(1)

            route = route_idx_to_stops(route_idx, points)
            results[cid][name] = {"route": route, "dist": dist_km}
            line_parts.append(f"  {name} {dist_km:>8.2f}")

        print("".join(line_parts) + " km")

    totals = {name: sum(results[c][name]["dist"] for c in cluster_ids) for name, *_ in CONFIGS}

    print("-" * 72)
    print(
        "  TOTAL road km  "
        + "  ".join(f"{name}: {totals[name]:>10.2f}" for name, *_ in CONFIGS)
    )
    print(f"  OSRM table HTTP : {t_mat:.2f}s")
    for name, *_ in CONFIGS:
        print(f"  OR-Tools {name:<6}: {t_solve[name]:.2f}s")

    save_routes_csv(OUT_GREEDY, cluster_ids, results, "greedy", mat_cache)
    save_routes_csv(OUT_GLS, cluster_ids, results, "gls", mat_cache)
    save_routes_csv(OUT_SA, cluster_ids, results, "sa", mat_cache)
    save_routes_csv(OUT_TABU, cluster_ids, results, "tabu", mat_cache)

    compare_rows = []
    for cid in cluster_ids:
        row = {"van": cid, "stops": results[cid]["stops"]}
        for name, *_ in CONFIGS:
            row[f"road_{name}_km"] = round(results[cid][name]["dist"], 4)
        compare_rows.append(row)

    with open(OUT_COMPARE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(compare_rows[0].keys()))
        w.writeheader()
        w.writerows(compare_rows)

    greedy = totals["greedy"]
    txt = [
        "=" * 72,
        "  ROUTING SUMMARY — OSRM matrix + OR-Tools",
        "=" * 72,
        "",
        f"  Clusters file       : {CLUSTERS_CSV}",
        f"  OSRM_BASE           : {mat.OSRM_BASE}",
        f"  First solution      : PATH_CHEAPEST_ARC (greedy / NN-like)",
        f"  Meta time limit/van : {ORTOOLS_TIME_LIMIT}s",
        "",
        f"  Total road km  greedy: {totals['greedy']:.2f}",
        f"  Total road km  gls   : {totals['gls']:.2f}  ({(greedy - totals['gls']) / greedy * 100:+.1f}% vs greedy)",
        f"  Total road km  sa    : {totals['sa']:.2f}  ({(greedy - totals['sa']) / greedy * 100:+.1f}% vs greedy)",
        f"  Total road km  tabu  : {totals['tabu']:.2f}  ({(greedy - totals['tabu']) / greedy * 100:+.1f}% vs greedy)",
        "",
        f"  Per-van: {OUT_COMPARE}",
        "",
    ]
    with open(OUT_TXT, "w", encoding="utf-8") as f:
        f.write("\n".join(txt))

    print(f"\n  Saved: {OUT_GREEDY}")
    print(f"  Saved: {OUT_GLS}")
    print(f"  Saved: {OUT_SA}")
    print(f"  Saved: {OUT_TABU}")
    print(f"  Saved: {OUT_COMPARE}")
    print(f"  Saved: {OUT_TXT}")


if __name__ == "__main__":
    main()
