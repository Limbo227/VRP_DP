"""
Benchmark Google OR-Tools vs existing route CSVs (no OSRM calls).

Uses:
  data/deliveries.csv   — depot + stop coordinates
  data/clusters3.csv    — fixed van assignments (same as routes3.py)

Solves one round-trip TSP per van with OR-Tools on a Haversine distance matrix
(same metric as routes3.py). Compares total distance and visit order against
finished CSV files already in data/ (does not re-run heuristics or OSRM).

Usage (from repo root or Or-Tools/):
  Or-Tools\\.venv\\Scripts\\python.exe Or-Tools\\benchmark.py
  Or-Tools\\.venv\\Scripts\\python.exe Or-Tools\\benchmark.py --time-limit 15

Outputs:
  data/ortools_benchmark_summary.csv
  data/ortools_benchmark_report.txt
  data/routes_ortools_hav_greedy.csv
  data/routes_ortools_hav_gls.csv
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import sys
import time
from collections import defaultdict
from typing import Dict, List, Optional, Sequence, Tuple

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(REPO_ROOT, "data")

DELIVERIES_CSV = os.path.join(DATA_DIR, "deliveries.csv")
CLUSTERS_CSV = os.path.join(DATA_DIR, "clusters3.csv")

OUT_GREEDY = os.path.join(DATA_DIR, "routes_ortools_hav_greedy.csv")
OUT_GLS = os.path.join(DATA_DIR, "routes_ortools_hav_gls.csv")
OUT_SUMMARY = os.path.join(DATA_DIR, "ortools_benchmark_summary.csv")
OUT_REPORT = os.path.join(DATA_DIR, "ortools_benchmark_report.txt")

# Finished route CSVs to compare (skip missing files)
REFERENCE_CSV = {
    "routes3_nn": "routes3_nn.csv",
    "routes3_2opt": "routes3_2opt.csv",
    "routes3_rr2opt": "routes3_rr2opt.csv",
    "routes_nn": "routes_nn.csv",
    "routes_2opt": "routes_2opt.csv",
    "routes_rr2opt": "routes_rr2opt.csv",
    "routes_osrm_nn": "routes_osrm_nn.csv",
    "routes_osrm_2opt": "routes_osrm_2opt.csv",
    "routes_osrm_rr2opt": "routes_osrm_rr2opt.csv",
}

ORTOOLS_TIME_LIMIT_DEFAULT = 10
FS = routing_enums_pb2.FirstSolutionStrategy
LS = routing_enums_pb2.LocalSearchMetaheuristic

ROUTE_FIELDS = [
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


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return r * 2 * math.asin(math.sqrt(a))


def build_matrix_km(points: Sequence[dict]) -> List[List[float]]:
    n = len(points)
    mat = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j:
                mat[i][j] = haversine_km(
                    points[i]["latitude"],
                    points[i]["longitude"],
                    points[j]["latitude"],
                    points[j]["longitude"],
                )
    return mat


def route_distance_km(route: Sequence[dict]) -> float:
    total = 0.0
    for i in range(1, len(route)):
        total += haversine_km(
            route[i - 1]["latitude"],
            route[i - 1]["longitude"],
            route[i]["latitude"],
            route[i]["longitude"],
        )
    return total


def solve_tsp_ortools(
    mat_km: List[List[float]],
    first_solution: int,
    local_search: Optional[int],
    time_limit_sec: int,
    solution_limit: Optional[int] = None,
) -> Tuple[Optional[List[int]], Optional[float]]:
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
    return route_idx, solution.ObjectiveValue() / 1000.0


def load_clusters(path: str) -> Tuple[dict, Dict[int, List[dict]]]:
    depot: Optional[dict] = None
    clusters: Dict[int, List[dict]] = defaultdict(list)
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["latitude"] = float(row["latitude"])
            row["longitude"] = float(row["longitude"])
            row["demand"] = int(float(row["demand"]))
            cid = int(row["cluster"])
            if row["delivery_id"].upper() == "DEPOT":
                depot = row
            elif cid >= 0:
                clusters[cid].append(row)
    if depot is None:
        raise SystemExit(f"No DEPOT in {path}")
    return depot, dict(clusters)


def load_routes_csv(path: str) -> Dict[int, List[dict]]:
    """van -> rows sorted by stop_order."""
    vans: Dict[int, List[dict]] = defaultdict(list)
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            van = int(row["van"])
            row["stop_order"] = int(row["stop_order"])
            row["latitude"] = float(row["latitude"])
            row["longitude"] = float(row["longitude"])
            vans[van].append(row)
    for van in vans:
        vans[van].sort(key=lambda r: r["stop_order"])
    return dict(vans)


def stop_sequence(rows: List[dict]) -> List[str]:
    """Delivery IDs in visit order, excluding depot duplicates."""
    seq: List[str] = []
    for r in rows:
        did = str(r["delivery_id"]).strip()
        if did.upper() == "DEPOT":
            continue
        seq.append(did)
    return seq


def csv_native_total_km(rows: List[dict]) -> float:
    if not rows:
        return 0.0
    return float(rows[-1].get("route_km_so_far") or 0)


def sequence_match_pct(a: Sequence[str], b: Sequence[str]) -> float:
    if not a and not b:
        return 100.0
    n = max(len(a), len(b))
    if n == 0:
        return 100.0
    matches = sum(1 for i in range(min(len(a), len(b))) if a[i] == b[i])
    return 100.0 * matches / n


def route_from_indices(
    indices: List[int], points: List[dict]
) -> Tuple[List[dict], float]:
    route = [points[i] for i in indices]
    return route, route_distance_km(route)


def save_routes_csv(path: str, van_routes: Dict[int, List[dict]]) -> None:
    rows: List[dict] = []
    for vid in sorted(van_routes.keys()):
        route = van_routes[vid]
        cum = 0.0
        for order, stop in enumerate(route):
            dist_prev = 0.0 if order == 0 else haversine_km(
                route[order - 1]["latitude"],
                route[order - 1]["longitude"],
                stop["latitude"],
                stop["longitude"],
            )
            if order > 0:
                cum += dist_prev
            rows.append(
                {
                    "van": vid,
                    "stop_order": order,
                    "delivery_id": stop["delivery_id"],
                    "customer_name": stop.get("customer_name", ""),
                    "postcode": stop.get("postcode", ""),
                    "latitude": stop["latitude"],
                    "longitude": stop["longitude"],
                    "demand": int(stop.get("demand", 0)),
                    "priority": stop.get("priority", "standard"),
                    "dist_from_prev_km": round(dist_prev, 4),
                    "route_km_so_far": round(cum, 4),
                }
            )
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=ROUTE_FIELDS)
        w.writeheader()
        w.writerows(rows)


def run_ortools_on_clusters(
    depot: dict,
    clusters: Dict[int, List[dict]],
    time_limit: int,
) -> Tuple[Dict[str, Dict[int, List[dict]]], Dict[str, float], Dict[str, float]]:
    """Returns routes per algo, total km, solve seconds."""
    configs = [
        ("ortools_hav_greedy", FS.PATH_CHEAPEST_ARC, None, 0, 1),
        ("ortools_hav_gls", FS.PATH_CHEAPEST_ARC, LS.GUIDED_LOCAL_SEARCH, time_limit, None),
    ]
    all_routes: Dict[str, Dict[int, List[dict]]] = {k: {} for k, *_ in configs}
    totals: Dict[str, float] = {k: 0.0 for k, *_ in configs}
    times: Dict[str, float] = {k: 0.0 for k, *_ in configs}

    van_ids = sorted(clusters.keys())
    for cid in van_ids:
        stops = sorted(clusters[cid], key=lambda s: s["delivery_id"])
        points = [depot] + stops
        mat = build_matrix_km(points)

        for key, fs, ls, tlim, slimit in configs:
            t0 = time.perf_counter()
            idx, _ = solve_tsp_ortools(mat, fs, ls, tlim, slimit)
            times[key] += time.perf_counter() - t0
            if idx is None:
                raise SystemExit(f"OR-Tools found no solution for van {cid} ({key})")
            route, dist = route_from_indices(idx, points)
            all_routes[key][cid] = route
            totals[key] += dist

    return all_routes, totals, times


def evaluate_reference(
    name: str,
    path: str,
    depot: dict,
    clusters: Dict[int, List[dict]],
    ortools_seq: Dict[int, List[str]],
) -> Optional[dict]:
    if not os.path.isfile(path):
        return None

    vans = load_routes_csv(path)
    total_hav = 0.0
    total_csv_native = 0.0
    order_pcts: List[float] = []

    for cid in sorted(clusters.keys()):
        rows = vans.get(cid)
        if not rows:
            return None
        seq = stop_sequence(rows)
        total_hav += route_distance_km(rows)
        total_csv_native += csv_native_total_km(rows)
        ref = ortools_seq.get(cid, [])
        order_pcts.append(sequence_match_pct(seq, ref))

    return {
        "label": name,
        "path": path,
        "total_hav_km": round(total_hav, 3),
        "total_csv_km": round(total_csv_native, 3),
        "avg_order_match_pct": round(sum(order_pcts) / len(order_pcts), 2),
        "per_van_order_pct": order_pcts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="OR-Tools benchmark vs route CSVs")
    parser.add_argument(
        "--time-limit",
        type=int,
        default=ORTOOLS_TIME_LIMIT_DEFAULT,
        help="GLS seconds per van (default 10)",
    )
    parser.add_argument(
        "--clusters",
        default=CLUSTERS_CSV,
        help="Cluster assignments CSV",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.clusters):
        raise SystemExit(f"Missing {args.clusters} — run cluster3.py first.")
    if not os.path.isfile(DELIVERIES_CSV):
        raise SystemExit(f"Missing {DELIVERIES_CSV}")

    depot, clusters = load_clusters(args.clusters)
    n_stops = sum(len(v) for v in clusters.values())
    n_vans = len(clusters)

    print("=" * 64)
    print("  OR-Tools benchmark (Haversine, fixed clusters3)")
    print("=" * 64)
    print(f"  Clusters : {args.clusters}")
    print(f"  Stops    : {n_stops}  |  Vans: {n_vans}")
    print(f"  Metric   : Haversine km (same as routes3.py)")
    print(f"  OSRM     : not called\n")

    print("  Solving OR-Tools per van …")
    ortools_routes, ortools_totals, ortools_times = run_ortools_on_clusters(
        depot, clusters, args.time_limit
    )
    save_routes_csv(OUT_GREEDY, ortools_routes["ortools_hav_greedy"])
    save_routes_csv(OUT_GLS, ortools_routes["ortools_hav_gls"])
    print(f"  Saved {OUT_GREEDY}")
    print(f"  Saved {OUT_GLS}")

    ortools_seq = {
        cid: stop_sequence(ortools_routes["ortools_hav_gls"][cid])
        for cid in clusters
    }

    rows_summary: List[dict] = []
    report: List[str] = [
        "=" * 64,
        "  OR-Tools benchmark report",
        "=" * 64,
        f"  clusters: {args.clusters}",
        f"  stops: {n_stops}  vans: {n_vans}",
        "",
        "  TOTAL DISTANCE (Haversine along each CSV visit order)",
        f"  {'Method':<22} {'km':>10}  {'vs GLS':>10}  {'solve/s':>8}",
        f"  {'-' * 54}",
    ]

    baseline_km = ortools_totals["ortools_hav_gls"]
    for key in ("ortools_hav_greedy", "ortools_hav_gls"):
        km = ortools_totals[key]
        vs = (km - baseline_km) / baseline_km * 100 if baseline_km else 0
        report.append(
            f"  {key:<22} {km:>10.2f}  {vs:>+9.1f}%  {ortools_times[key]:>8.2f}"
        )
        rows_summary.append(
            {
                "method": key,
                "total_haversine_km": round(km, 3),
                "total_csv_native_km": "",
                "vs_ortools_gls_pct": round(vs, 2),
                "solve_seconds": round(ortools_times[key], 2),
                "avg_order_match_vs_gls_pct": 100.0 if key == "ortools_hav_gls" else "",
            }
        )

    report.append("")
    report.append("  REFERENCE CSVs (existing pipeline outputs)")
    report.append(f"  {'Method':<22} {'Haversine km':>12}  {'CSV total km':>12}  {'order~GLS%':>12}")
    report.append(f"  {'-' * 62}")

    ref_results: List[dict] = []
    for label, fname in REFERENCE_CSV.items():
        path = os.path.join(DATA_DIR, fname)
        ev = evaluate_reference(label, path, depot, clusters, ortools_seq)
        if ev is None:
            print(f"  skip (missing): {fname}")
            continue
        ref_results.append(ev)
        vs = (ev["total_hav_km"] - baseline_km) / baseline_km * 100 if baseline_km else 0
        report.append(
            f"  {label:<22} {ev['total_hav_km']:>12.2f}  "
            f"{ev['total_csv_km']:>12.2f}  {ev['avg_order_match_pct']:>12.1f}"
        )
        rows_summary.append(
            {
                "method": label,
                "total_haversine_km": ev["total_hav_km"],
                "total_csv_native_km": ev["total_csv_km"],
                "vs_ortools_gls_pct": round(vs, 2),
                "solve_seconds": "",
                "avg_order_match_vs_gls_pct": ev["avg_order_match_pct"],
            }
        )

    report.append("")
    report.append("  ORDER vs OR-Tools GLS (per van, % positions with same delivery_id)")
    report.append(f"  {'Van':<5}  " + "  ".join(f"{r['label'][:12]:>12}" for r in ref_results))
    report.append(f"  {'-' * (5 + 14 * len(ref_results))}")
    for i, cid in enumerate(sorted(clusters.keys())):
        parts = [f"  {cid:<5}"]
        for r in ref_results:
            pct = r["per_van_order_pct"][i]
            parts.append(f"{pct:>12.1f}")
        report.append("".join(parts))

    report.append("")
    report.append("  Notes:")
    report.append("  - Haversine km recomputed from CSV lat/lon (fair compare).")
    report.append("  - CSV total km = last route_km_so_far (OSRM matrix for routes_osrm_*).")
    report.append("  - order~GLS% = same stop index vs OR-Tools GLS sequence.")
    report.append("=" * 64)

    text = "\n".join(report)
    with open(OUT_REPORT, "w", encoding="utf-8") as f:
        f.write(text)
    with open(OUT_SUMMARY, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "method",
                "total_haversine_km",
                "total_csv_native_km",
                "vs_ortools_gls_pct",
                "solve_seconds",
                "avg_order_match_vs_gls_pct",
            ],
        )
        w.writeheader()
        w.writerows(rows_summary)

    print()
    print(text)
    print(f"\n  Wrote {OUT_SUMMARY}")
    print(f"  Wrote {OUT_REPORT}")


if __name__ == "__main__":
    main()
