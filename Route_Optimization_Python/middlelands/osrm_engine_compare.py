"""
OSRM native /trip vs our heuristics on road distances
----------------------------------------------------
For each van (cluster), same stop set and depot:

  * **OSRM /trip** — built-in round-trip optimiser (visit order + driving distance/duration).
  * **NN / 2-opt / RR-2-opt** — same logic as routes.py, but leg costs from **OSRM /table**
    (see osrm_matrix_routes.py).

This is the single place to compare “OSRM engine” vs “our three algorithms on the road network”.

Outputs:
  data/osrm_engine_compare.csv
  data/osrm_engine_compare_summary.txt

Requires: OSRM with /trip and /table (e.g. http://127.0.0.1:5000).

Usage (from repo root or middlelands):
  python Route_Optimization_Python/middlelands/osrm_engine_compare.py

Env (same as sibling scripts):
  OSRM_BASE, OSRM_PROFILE, CLUSTERS_CSV
"""

from __future__ import annotations

import csv
import os
import time
import urllib.error

import osrm_matrix_routes as mat
import osrm_trip_compare as trip

REPO_ROOT = mat.REPO_ROOT
DATA_DIR = mat.DATA_DIR
OUT_CSV = os.path.join(DATA_DIR, "osrm_engine_compare.csv")
OUT_TXT = os.path.join(DATA_DIR, "osrm_engine_compare_summary.txt")


def main() -> None:
    deliveries_path = mat.DELIVERIES_CSV
    clusters_path = mat.CLUSTERS_CSV

    if not os.path.isfile(deliveries_path):
        raise SystemExit(f"Missing {deliveries_path}")
    if not os.path.isfile(clusters_path):
        raise SystemExit(f"Missing {clusters_path}")

    deliveries = mat.load_deliveries_by_id(deliveries_path)
    cluster_by_id = mat.load_cluster_assignments(clusters_path)
    depot, stops, missing = mat.merge_stops(deliveries, cluster_by_id)
    if missing:
        print("WARN: ids in clusters but not in deliveries:", missing[:8], "...")

    clusters = mat.group_by_cluster(stops)
    cluster_ids = sorted(clusters.keys())

    print("=" * 70)
    print("  OSRM /trip  vs  NN / 2-opt / RR-2-opt (all distances = road km)")
    print("=" * 70)
    print(f"  OSRM_BASE      : {mat.OSRM_BASE}")
    print(f"  OSRM_PROFILE   : {mat.PROFILE}")
    print(f"  Clusters file  : {clusters_path}")
    print(f"  Vans           : {len(cluster_ids)}")
    print()

    rows: list[dict] = []
    t_trip = t_table = 0.0
    total_trip = total_nn = total_2 = total_rr = 0.0
    trip_failures = 0

    for cid in cluster_ids:
        cluster_stops = sorted(clusters[cid], key=lambda s: s["delivery_id"])
        points = [depot] + cluster_stops
        coord_str = ";".join(
            mat.lonlat(p["latitude"], p["longitude"]) for p in points
        )

        trip_km: float | None = None
        trip_min: float | None = None
        trip_ok = False
        trip_err = ""

        t0 = time.perf_counter()
        try:
            trip_data = trip.osrm_trip_request(coord_str)
            dist_m, dur_s, _, _, _ = trip.parse_trip_response(trip_data, points)
            trip_km = dist_m / 1000.0
            trip_min = dur_s / 60.0
            trip_ok = True
        except urllib.error.URLError as e:
            trip_err = f"URLError: {e}"
            print(f"  Van {cid}: Trip failed ({trip_err}). Is OSRM running?")
            raise SystemExit(1) from e
        except (urllib.error.HTTPError, RuntimeError, KeyError, ValueError) as e:
            trip_err = str(e)
            trip_failures += 1
            print(f"  Van {cid}: Trip error — {trip_err}")
        t_trip += time.perf_counter() - t0

        t0 = time.perf_counter()
        try:
            mat_km = mat.osrm_table_distances_km(points)
        except (urllib.error.URLError, urllib.error.HTTPError, RuntimeError) as e:
            print(f"  Van {cid}: OSRM table failed: {e}")
            raise SystemExit(1) from e
        t_table += time.perf_counter() - t0

        route_nn = mat.nearest_neighbour_osrm(depot, cluster_stops, mat_km, points)
        route_2 = mat.two_opt_osrm(list(route_nn), mat_km, points)
        route_rr = mat.random_restart_2opt_osrm(depot, cluster_stops, mat_km, points)

        id_to_idx = {points[i]["delivery_id"]: i for i in range(len(points))}
        d_nn = mat.route_distance_idx(
            [id_to_idx[r["delivery_id"]] for r in route_nn], mat_km, points
        )
        d_2 = mat.route_distance_idx(
            [id_to_idx[r["delivery_id"]] for r in route_2], mat_km, points
        )
        d_rr = mat.route_distance_idx(
            [id_to_idx[r["delivery_id"]] for r in route_rr], mat_km, points
        )

        total_nn += d_nn
        total_2 += d_2
        total_rr += d_rr
        if trip_km is not None:
            total_trip += trip_km

        gap_nn = gap_2 = gap_rr = ""
        if trip_ok and trip_km is not None:
            gap_nn = round(d_nn - trip_km, 4)
            gap_2 = round(d_2 - trip_km, 4)
            gap_rr = round(d_rr - trip_km, 4)

        rows.append(
            {
                "van": cid,
                "stops": len(cluster_stops),
                "osrm_trip_ok": trip_ok,
                "osrm_trip_error": trip_err,
                "osrm_trip_distance_km": round(trip_km, 4) if trip_km is not None else "",
                "osrm_trip_duration_min": round(trip_min, 2) if trip_min is not None else "",
                "road_nn_km": round(d_nn, 4),
                "road_2opt_km": round(d_2, 4),
                "road_rr_km": round(d_rr, 4),
                "gap_nn_minus_trip_km": gap_nn,
                "gap_2opt_minus_trip_km": gap_2,
                "gap_rr_minus_trip_km": gap_rr,
            }
        )

        trip_s = f"{trip_km:.2f}" if trip_km is not None else "—"
        print(
            f"  Van {cid:<2}  stops={len(cluster_stops):>3}  "
            f"Trip {trip_s:>8}  NN {d_nn:>8.2f}  2opt {d_2:>8.2f}  RR {d_rr:>8.2f} km"
        )

    print("-" * 70)
    print(
        f"  TOTAL road km  Trip: {total_trip:>10.2f}  "
        f"NN: {total_nn:>10.2f}  2opt: {total_2:>10.2f}  RR: {total_rr:>10.2f}"
    )
    print(
        f"  HTTP time  Trip: {t_trip:.2f}s  Table: {t_table:.2f}s  "
        f"(trip failures: {trip_failures})"
    )

    fieldnames = list(rows[0].keys()) if rows else []
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"\n  Saved: {OUT_CSV}")

    gap_nn_tot = total_nn - total_trip
    gap_rr_tot = total_rr - total_trip
    txt_lines = [
        "=" * 70,
        "  OSRM /trip vs matrix heuristics (road km)",
        "=" * 70,
        "",
        f"  Clusters file : {clusters_path}",
        f"  OSRM_BASE     : {mat.OSRM_BASE}",
        f"  Profile       : {mat.PROFILE}",
        "",
        f"  Sum OSRM Trip distance (km)     : {total_trip:.4f}",
        f"  Sum NN / 2-opt / RR (matrix km) : {total_nn:.4f}  {total_2:.4f}  {total_rr:.4f}",
        f"  Total gap NN − Trip (km)        : {gap_nn_tot:.4f}",
        f"  Total gap RR − Trip (km)        : {gap_rr_tot:.4f}",
        "",
        f"  Trip HTTP time (s) : {t_trip:.4f}",
        f"  Table HTTP time (s): {t_table:.4f}",
        f"  Trip failures      : {trip_failures}",
        "",
        f"  Per-van table: {OUT_CSV}",
        "",
    ]
    with open(OUT_TXT, "w", encoding="utf-8") as f:
        f.write("\n".join(txt_lines))
    print(f"  Saved: {OUT_TXT}")


if __name__ == "__main__":
    main()
