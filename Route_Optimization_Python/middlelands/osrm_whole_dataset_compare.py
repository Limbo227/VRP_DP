"""
Whole dataset vs clustered: OSRM /trip + road-matrix heuristics
---------------------------------------------------------------
1) **Clustered** — same as `osrm_engine_compare.py`: each van’s cluster gets its own
   `/trip` and `/table`, then NN / 2-opt / RR on that matrix. We **sum** per-van km
   (multi-vehicle baseline).

2) **Whole dataset** — **no clusters**: one list `depot + all deliveries`. Driving
   distances use **tiled OSRM `/table`** when N exceeds the server coordinate cap (often
   100). **OSRM `/trip`** on the full waypoint list still needs a high server limit; if
   it returns `TooBig`, Trip is skipped and NN / 2-opt / RR are still reported from the
   tiled matrix.

Use this to see how total road km differs when you treat the problem as one TSP vs
twelve independent round trips from the same depot.

Outputs:
  data/osrm_whole_dataset_compare.csv   — one row of totals + whole-tour row
  data/osrm_whole_dataset_compare.txt   — human-readable summary

Env (shared with sibling scripts):
  OSRM_BASE, OSRM_PROFILE, CLUSTERS_CSV
  OSRM_MAX_TABLE_COORDS — per-request coordinate cap for tiling (default 100)
  RR_RESTARTS — used for clustered vans (default from osrm_matrix_routes, 50)
  WHOLE_RR_RESTARTS — RR restarts for the single mega-tour (default 25; 121 stops
                      makes each 2-opt expensive)

Usage:
  python Route_Optimization_Python/middlelands/osrm_whole_dataset_compare.py
"""

from __future__ import annotations

import csv
import json
import os
import time
import urllib.error
from collections import defaultdict

import osrm_matrix_routes as mat
import osrm_trip_compare as trip

DATA_DIR = mat.DATA_DIR
OUT_CSV = os.path.join(DATA_DIR, "osrm_whole_dataset_compare.csv")
OUT_TXT = os.path.join(DATA_DIR, "osrm_whole_dataset_compare.txt")


def load_depot_and_all_stops(deliveries_path: str):
    """All non-DEPOT rows from deliveries.csv, sorted by delivery_id."""
    by_id = mat.load_deliveries_by_id(deliveries_path)
    if "DEPOT" not in by_id:
        raise SystemExit("deliveries.csv must contain delivery_id DEPOT")
    depot = by_id["DEPOT"]
    stops = [dict(by_id[k]) for k in by_id if k != "DEPOT"]
    stops.sort(key=lambda s: s["delivery_id"])
    return depot, stops


def clustered_totals(depot, stops, cluster_by_id: dict):
    """Sum per-van Trip / NN / 2opt / RR road km (same logic as osrm_engine_compare)."""
    clusters = defaultdict(list)
    for s in stops:
        cid = cluster_by_id.get(s["delivery_id"])
        if cid is None:
            continue
        row = dict(s)
        row["cluster"] = cid
        clusters[cid].append(row)
    cluster_ids = sorted(clusters.keys())

    sum_trip = sum_nn = sum_2 = sum_rr = 0.0
    t_trip = t_table = 0.0

    for cid in cluster_ids:
        cluster_stops = sorted(clusters[cid], key=lambda x: x["delivery_id"])
        points = [depot] + cluster_stops
        coord_str = ";".join(
            mat.lonlat(p["latitude"], p["longitude"]) for p in points
        )

        t0 = time.perf_counter()
        trip_data = trip.osrm_trip_request(coord_str)
        dist_m, _, _, _, _ = trip.parse_trip_response(trip_data, points)
        sum_trip += dist_m / 1000.0
        t_trip += time.perf_counter() - t0

        t0 = time.perf_counter()
        mat_km = mat.osrm_table_distances_km(points)
        t_table += time.perf_counter() - t0

        route_nn = mat.nearest_neighbour_osrm(depot, cluster_stops, mat_km, points)
        route_2 = mat.two_opt_osrm(list(route_nn), mat_km, points)
        route_rr = mat.random_restart_2opt_osrm(
            depot, cluster_stops, mat_km, points, restarts=mat.RR_RESTARTS
        )
        id_to_idx = {points[i]["delivery_id"]: i for i in range(len(points))}
        sum_nn += mat.route_distance_idx(
            [id_to_idx[r["delivery_id"]] for r in route_nn], mat_km, points
        )
        sum_2 += mat.route_distance_idx(
            [id_to_idx[r["delivery_id"]] for r in route_2], mat_km, points
        )
        sum_rr += mat.route_distance_idx(
            [id_to_idx[r["delivery_id"]] for r in route_rr], mat_km, points
        )

    return {
        "vans": len(cluster_ids),
        "sum_trip_km": sum_trip,
        "sum_nn_km": sum_nn,
        "sum_2opt_km": sum_2,
        "sum_rr_km": sum_rr,
        "trip_http_s": t_trip,
        "table_http_s": t_table,
    }


def whole_dataset_totals(depot, all_stops: list, rr_restarts: int):
    """Single tour: depot + every stop."""
    points = [depot] + all_stops
    coord_str = ";".join(
        mat.lonlat(p["latitude"], p["longitude"]) for p in points
    )

    trip_km: float | None = None
    trip_min: float | None = None
    trip_err = ""
    t0 = time.perf_counter()
    try:
        trip_data = trip.osrm_trip_request(coord_str)
        dist_m, dur_s, _, _, _ = trip.parse_trip_response(trip_data, points)
        trip_km = dist_m / 1000.0
        trip_min = dur_s / 60.0
    except urllib.error.HTTPError as e:
        try:
            trip_err = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            trip_err = str(e)
        if e.code != 400:
            raise
    except (RuntimeError, KeyError, ValueError, json.JSONDecodeError) as e:
        trip_err = str(e)
    t_trip = time.perf_counter() - t0

    t0 = time.perf_counter()
    mat_km = mat.osrm_table_distances_km_tiled(points)
    t_table = time.perf_counter() - t0

    t0 = time.perf_counter()
    route_nn = mat.nearest_neighbour_osrm(depot, all_stops, mat_km, points)
    t_nn = time.perf_counter() - t0

    t0 = time.perf_counter()
    route_2 = mat.two_opt_osrm(list(route_nn), mat_km, points)
    t_2 = time.perf_counter() - t0

    t0 = time.perf_counter()
    route_rr = mat.random_restart_2opt_osrm(
        depot, all_stops, mat_km, points, restarts=rr_restarts
    )
    t_rr = time.perf_counter() - t0

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

    return {
        "n_stops": len(all_stops),
        "n_locations": len(points),
        "trip_km": trip_km,
        "trip_min": trip_min,
        "trip_err": trip_err,
        "nn_km": d_nn,
        "opt2_km": d_2,
        "rr_km": d_rr,
        "trip_http_s": t_trip,
        "table_http_s": t_table,
        "nn_s": t_nn,
        "opt2_s": t_2,
        "rr_s": t_rr,
        "rr_restarts_used": rr_restarts,
    }


def main() -> None:
    deliveries_path = mat.DELIVERIES_CSV
    clusters_path = mat.CLUSTERS_CSV
    whole_rr = int(os.environ.get("WHOLE_RR_RESTARTS", "25"))

    if not os.path.isfile(deliveries_path):
        raise SystemExit(f"Missing {deliveries_path}")
    if not os.path.isfile(clusters_path):
        raise SystemExit(f"Missing {clusters_path} (needed for clustered baseline)")

    depot, all_stops = load_depot_and_all_stops(deliveries_path)
    cluster_by_id = mat.load_cluster_assignments(clusters_path)
    _, clustered_stops, missing = mat.merge_stops(
        mat.load_deliveries_by_id(deliveries_path), cluster_by_id
    )
    if missing:
        print("WARN: cluster ids missing in deliveries:", missing[:8], "...")

    n_all = len(all_stops)
    n_clustered = len(clustered_stops)
    if n_all != n_clustered:
        print(
            f"WARN: whole dataset has {n_all} stops, cluster assignments cover "
            f"{n_clustered} — totals compare different stop sets."
        )

    print("=" * 72)
    print("  Whole dataset (1 tour) vs sum of clustered van tours")
    print("=" * 72)
    print(f"  OSRM_BASE           : {mat.OSRM_BASE}")
    print(f"  OSRM_PROFILE        : {mat.PROFILE}")
    print(f"  Deliveries          : {deliveries_path}")
    print(f"  Clusters (baseline) : {clusters_path}")
    print(f"  Stops (whole tour)  : {n_all}")
    print(f"  WHOLE_RR_RESTARTS   : {whole_rr}")
    print()

    print("  [1/2] Clustered baseline (per-van /trip + /table, summed km)…")
    try:
        c = clustered_totals(depot, clustered_stops, cluster_by_id)
    except urllib.error.URLError as e:
        raise SystemExit(f"OSRM unreachable: {e}") from e
    except (urllib.error.HTTPError, RuntimeError, KeyError, ValueError) as e:
        raise SystemExit(f"Clustered phase failed: {e}") from e

    print(
        f"        vans={c['vans']}  SUM Trip {c['sum_trip_km']:.2f}  "
        f"NN {c['sum_nn_km']:.2f}  2opt {c['sum_2opt_km']:.2f}  RR {c['sum_rr_km']:.2f} km"
    )
    print(
        f"        HTTP  Trip {c['trip_http_s']:.2f}s  Table {c['table_http_s']:.2f}s"
    )
    print()

    print("  [2/2] Whole dataset (single /trip + single /table, one mega-tour)…")
    try:
        w = whole_dataset_totals(depot, all_stops, whole_rr)
    except urllib.error.URLError as e:
        raise SystemExit(f"OSRM unreachable: {e}") from e
    except (urllib.error.HTTPError, RuntimeError, KeyError, ValueError) as e:
        raise SystemExit(
            f"Whole-dataset phase failed: {e}\n"
            "If OSRM returned TooBig, raise max_locations_trip / table limits "
            "in osrm-routed."
        ) from e

    trip_s = f"{w['trip_km']:.2f}" if w["trip_km"] is not None else "— (skipped)"
    print(
        f"        locations={w['n_locations']}  Trip {trip_s:>14}  "
        f"NN {w['nn_km']:.2f}  2opt {w['opt2_km']:.2f}  RR {w['rr_km']:.2f} km"
    )
    if w["trip_km"] is None and w.get("trip_err"):
        err_short = w["trip_err"].replace("\n", " ")[:220]
        print(f"        /trip reason: {err_short}")
        print(
            "        Hint: raise OSRM trip coordinate limit (e.g. osrm-routed "
            "`--max-table-size` / trip size flags for your build) to get whole-dataset Trip."
        )
    trip_min_s = (
        f"{w['trip_min']:.1f} min" if w["trip_min"] is not None else "—"
    )
    print(
        f"        Trip {trip_min_s}  |  HTTP Trip {w['trip_http_s']:.2f}s  "
        f"Table {w['table_http_s']:.2f}s  |  CPU NN {w['nn_s']:.3f}s  "
        f"2opt {w['opt2_s']:.3f}s  RR {w['rr_s']:.2f}s ({w['rr_restarts_used']} restarts)"
    )
    print()

    diff_trip: float | str = ""
    if w["trip_km"] is not None:
        diff_trip = w["trip_km"] - c["sum_trip_km"]
    diff_rr = w["rr_km"] - c["sum_rr_km"]
    print("  --- Difference (whole single tour MINUS sum of clustered tours) ---")
    if w["trip_km"] is not None:
        print(f"        Trip: {diff_trip:+.2f} km   RR: {diff_rr:+.2f} km")
    else:
        print(f"        Trip: (n/a — whole /trip unavailable)   RR: {diff_rr:+.2f} km")
    print(
        "        (Negative whole−clustered usually means one vehicle looping "
        "everywhere beats many depot round-trips on total km.)"
    )
    print()

    trip_whole_val = round(w["trip_km"], 4) if w["trip_km"] is not None else ""
    trip_delta_val = round(diff_trip, 4) if isinstance(diff_trip, float) else ""
    notes_whole = (
        f"one depot+all stops; tiled /table cap={mat.OSRM_MAX_TABLE_COORDS}; "
        f"WHOLE_RR_RESTARTS={w['rr_restarts_used']}"
    )
    if w["trip_km"] is None:
        notes_whole += "; /trip skipped (server TooBig or error)"

    rows = [
        {
            "scenario": "clustered_sum",
            "vans_or_locations": c["vans"],
            "osrm_trip_km": round(c["sum_trip_km"], 4),
            "road_nn_km": round(c["sum_nn_km"], 4),
            "road_2opt_km": round(c["sum_2opt_km"], 4),
            "road_rr_km": round(c["sum_rr_km"], 4),
            "notes": "sum over independent van tours from CLUSTERS_CSV",
        },
        {
            "scenario": "whole_single_tour",
            "vans_or_locations": w["n_locations"],
            "osrm_trip_km": trip_whole_val,
            "road_nn_km": round(w["nn_km"], 4),
            "road_2opt_km": round(w["opt2_km"], 4),
            "road_rr_km": round(w["rr_km"], 4),
            "notes": notes_whole,
        },
        {
            "scenario": "delta_whole_minus_clustered_sum",
            "vans_or_locations": "",
            "osrm_trip_km": trip_delta_val,
            "road_nn_km": round(w["nn_km"] - c["sum_nn_km"], 4),
            "road_2opt_km": round(w["opt2_km"] - c["sum_2opt_km"], 4),
            "road_rr_km": round(diff_rr, 4),
            "notes": "whole minus clustered_sum",
        },
    ]
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        wcsv = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        wcsv.writeheader()
        wcsv.writerows(rows)
    print(f"  Saved: {OUT_CSV}")

    trip_km_txt = (
        f"{w['trip_km']:.4f}  ({w['trip_min']:.2f} min)"
        if w["trip_km"] is not None
        else "(skipped — raise OSRM trip size limit or see notes in CSV)"
    )
    delta_trip_txt = (
        f"{diff_trip:+.4f} km"
        if isinstance(diff_trip, float)
        else "n/a (whole /trip unavailable)"
    )
    txt = "\n".join(
        [
            "=" * 72,
            "Whole dataset vs clustered (road km)",
            "=" * 72,
            "",
            f"Deliveries : {deliveries_path}",
            f"Clusters   : {clusters_path}",
            f"OSRM_BASE  : {mat.OSRM_BASE}",
            f"Table cap  : OSRM_MAX_TABLE_COORDS={mat.OSRM_MAX_TABLE_COORDS} (tiling)",
            "",
            "Clustered — sum of per-van tours (multi-vehicle model)",
            f"  vans              : {c['vans']}",
            f"  sum OSRM Trip km  : {c['sum_trip_km']:.4f}",
            f"  sum NN / 2opt / RR: {c['sum_nn_km']:.4f}  {c['sum_2opt_km']:.4f}  {c['sum_rr_km']:.4f}",
            "",
            "Whole — one tour visiting every stop once (single-vehicle model)",
            f"  stops (+ depot)   : {w['n_stops']} + 1 = {w['n_locations']} locations",
            f"  OSRM Trip km      : {trip_km_txt}",
            f"  NN / 2opt / RR km : {w['nn_km']:.4f}  {w['opt2_km']:.4f}  {w['rr_km']:.4f}",
            f"  RR restarts       : {w['rr_restarts_used']}",
            "",
            "Delta (whole − clustered sum)",
            f"  Trip              : {delta_trip_txt}",
            f"  RR                : {diff_rr:+.4f} km",
            "",
            f"CSV: {OUT_CSV}",
            "",
        ]
    )
    with open(OUT_TXT, "w", encoding="utf-8") as f:
        f.write(txt)
    print(f"  Saved: {OUT_TXT}")


if __name__ == "__main__":
    main()
