"""
Route Optimisation — DPD Hinckley
----------------------------------
Compares 3 routing algorithms on each cluster (van):

    1. Nearest Neighbour  (greedy baseline)
    2. 2-opt              (improvement on top of NN)
    3. Random Restart 2-opt (best of N random starting orders)

Each algorithm solves the Travelling Salesman Problem (TSP)
for each cluster independently.

All routes start AND end at the depot (LE10 3BQ).
Distance metric: Haversine (great-circle, in km).

Output:
    routes_nn.csv
    routes_2opt.csv
    routes_rr2opt.csv
    routing_summary.txt

Usage:
    python routing.py
"""

import csv
import math
import random
import time
import os
from collections import defaultdict
from itertools import combinations
from copy import deepcopy

# Repo root (so script works regardless of current working directory)
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA_DIR = os.path.join(REPO_ROOT, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# ── Config ─────────────────────────────────────────────────────────
INPUT_FILE    = os.path.join(DATA_DIR, "clusters.csv")
RANDOM_SEED   = 42
RR_RESTARTS   = 50        # how many random restarts for Algorithm 3

random.seed(RANDOM_SEED)


# ══════════════════════════════════════════════════════════════════
# STEP 1 — HAVERSINE DISTANCE
# ══════════════════════════════════════════════════════════════════
# Why Haversine and not Euclidean?
#   Latitude/longitude are on a sphere, not a flat plane.
#   Euclidean distance between two lat/lon pairs would be inaccurate
#   especially over larger distances (London to Nottingham etc).
#   Haversine gives us the great-circle distance in km — the shortest
#   path over the Earth's surface between two points.
#
# Formula:
#   a = sin²(Δlat/2) + cos(lat1)·cos(lat2)·sin²(Δlon/2)
#   d = 2R · arcsin(√a)     where R = 6371 km

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


# ══════════════════════════════════════════════════════════════════
# STEP 2 — ROUTE DISTANCE
# ══════════════════════════════════════════════════════════════════
# Given an ordered list of stops (including depot at start and end),
# calculate the total route distance in km by summing consecutive
# haversine distances.

def route_distance(stops):
    """
    Total km for an ordered list of stop dicts.
    Expects depot at index 0 and index -1 (round trip).
    """
    total = 0.0
    for i in range(len(stops) - 1):
        total += haversine(
            stops[i]["latitude"],  stops[i]["longitude"],
            stops[i+1]["latitude"], stops[i+1]["longitude"],
        )
    return total


# ══════════════════════════════════════════════════════════════════
# ALGORITHM 1 — NEAREST NEIGHBOUR (NN)
# ══════════════════════════════════════════════════════════════════
# This is the simplest greedy heuristic for TSP.
#
# How it works:
#   1. Start at the depot.
#   2. Look at all unvisited stops.
#   3. Go to the closest one (greedy choice).
#   4. Repeat until all stops are visited.
#   5. Return to depot.
#
# Time complexity: O(n²) — for each of n stops, scan all remaining.
# Quality: Often 20-25% worse than optimal. Good baseline.
#
# Why include it?
#   It's the industry starting point and many real systems still use it.
#   It also gives 2-opt something to improve upon.

def nearest_neighbour(depot, stops):
    """
    Returns ordered list: [depot, stop, stop, ..., depot]
    """
    unvisited = list(stops)
    route     = [depot]
    current   = depot

    while unvisited:
        # Find the closest unvisited stop to current position
        nearest = min(
            unvisited,
            key=lambda s: haversine(
                current["latitude"], current["longitude"],
                s["latitude"],       s["longitude"]
            )
        )
        route.append(nearest)
        unvisited.remove(nearest)
        current = nearest

    route.append(depot)   # return to depot
    return route


# ══════════════════════════════════════════════════════════════════
# ALGORITHM 2 — 2-OPT IMPROVEMENT
# ══════════════════════════════════════════════════════════════════
# 2-opt is a local search improvement algorithm.
# It starts with an existing route (we use NN output) and tries to
# improve it by reversing segments of the route.
#
# How it works:
#   Given a route [d, A, B, C, D, E, d]:
#   Pick two edges, e.g. A→B and D→E.
#   Remove them and reconnect by reversing the segment between them:
#   [d, A, D, C, B, E, d]
#   If this is shorter → keep it.
#   Repeat until no improvement can be found (local optimum).
#
# Time complexity per pass: O(n²) — try all pairs of edges.
#   Passes repeat until no improvement → typically fast in practice.
#
# Key point for dissertation:
#   2-opt guarantees a locally optimal solution (no single 2-edge swap
#   can improve it), but NOT globally optimal. A different starting
#   route might lead to a better local optimum — which is why
#   Algorithm 3 uses random restarts.

def two_opt(route):
    """
    Improve a route in-place using 2-opt swaps.
    Route must include depot at [0] and [-1].
    Returns improved route.
    """
    best       = list(route)
    best_dist  = route_distance(best)
    improved   = True

    # The inner stops are indices 1 to n-2 (exclude depot at 0 and -1)
    n = len(best)

    while improved:
        improved = False
        for i in range(1, n - 2):           # start of reversed segment
            for j in range(i + 1, n - 1):   # end of reversed segment
                # Reverse the segment between i and j (inclusive)
                new_route = best[:i] + best[i:j+1][::-1] + best[j+1:]
                new_dist  = route_distance(new_route)

                if new_dist < best_dist - 1e-10:   # small epsilon for float safety
                    best      = new_route
                    best_dist = new_dist
                    improved  = True   # found improvement → do another full pass

    return best


# ══════════════════════════════════════════════════════════════════
# ALGORITHM 3 — RANDOM RESTART + 2-OPT
# ══════════════════════════════════════════════════════════════════
# Problem with Algorithm 2: the quality of 2-opt depends heavily on
# the starting route. NN gives one specific starting order, which may
# lead to a local optimum that isn't very good globally.
#
# Solution: run 2-opt many times from DIFFERENT random starting orders.
# Keep the best result across all restarts.
#
# How it works:
#   For R restarts:
#       1. Shuffle the stops into a random order.
#       2. Build a route: [depot] + shuffled_stops + [depot]
#       3. Apply 2-opt to improve it.
#       4. If this is the best route seen so far → save it.
#   Return the best route found.
#
# Time complexity: O(R · n²) per cluster.
# Quality: Generally best of the three — more computation = better routes.
#
# Dissertation note:
#   This is a meta-heuristic: the outer random restart loop explores
#   different regions of the solution space, while 2-opt does local
#   search within each region. This trade-off between exploration and
#   exploitation is a core theme in combinatorial optimisation.

def random_restart_2opt(depot, stops, restarts=RR_RESTARTS):
    """
    Run 2-opt from `restarts` different random starting orders.
    Returns the best route found.
    """
    best_route = None
    best_dist  = float("inf")

    for _ in range(restarts):
        # Random shuffle of stops
        shuffled = list(stops)
        random.shuffle(shuffled)

        # Build initial route and apply 2-opt
        initial  = [depot] + shuffled + [depot]
        improved = two_opt(initial)
        dist     = route_distance(improved)

        if dist < best_dist:
            best_dist  = dist
            best_route = improved

    return best_route


# ══════════════════════════════════════════════════════════════════
# STEP 3 — LOAD DATA
# ══════════════════════════════════════════════════════════════════
print("=" * 62)
print("  Route Optimisation — DPD Hinckley")
print("  Comparing 3 TSP Heuristics Across All Clusters")
print("=" * 62)

depot  = None
stops  = []

with open(INPUT_FILE, newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        row["latitude"]  = float(row["latitude"])
        row["longitude"] = float(row["longitude"])
        row["demand"]    = int(row["demand"])
        row["cluster"]   = int(row["cluster"])
        if row["delivery_id"] == "DEPOT":
            depot = row
        else:
            stops.append(row)

# Group stops by cluster (van)
clusters = defaultdict(list)
for s in stops:
    clusters[s["cluster"]].append(s)

cluster_ids = sorted(clusters.keys())
print(f"\n  Depot   : {depot['postcode']}")
print(f"  Stops   : {len(stops)}")
print(f"  Vans    : {len(cluster_ids)}  (clusters {cluster_ids[0]}–{cluster_ids[-1]})")
print(f"  RR restarts per cluster: {RR_RESTARTS}\n")


# ══════════════════════════════════════════════════════════════════
# STEP 4 — RUN ALL 3 ALGORITHMS ON EVERY CLUSTER
# ══════════════════════════════════════════════════════════════════
results = {}   # cluster_id → {nn, opt2, rr} each containing route + dist

print(f"  {'Van':<5} {'Stops':>5}  "
      f"{'NN (km)':>10}  {'2-opt (km)':>10}  {'RR-2opt (km)':>12}  "
      f"{'NN→2opt':>8}  {'NN→RR':>8}")
print(f"  {'-' * 68}")

t_nn   = 0.0
t_2opt = 0.0
t_rr   = 0.0

for cid in cluster_ids:
    cluster_stops = clusters[cid]

    # ── Algorithm 1: Nearest Neighbour ───────────────────────────
    t0        = time.perf_counter()
    route_nn  = nearest_neighbour(depot, cluster_stops)
    t_nn     += time.perf_counter() - t0
    dist_nn   = route_distance(route_nn)

    # ── Algorithm 2: 2-opt starting from NN route ─────────────────
    t0         = time.perf_counter()
    route_2opt = two_opt(list(route_nn))   # copy so NN route is preserved
    t_2opt    += time.perf_counter() - t0
    dist_2opt  = route_distance(route_2opt)

    # ── Algorithm 3: Random Restart 2-opt ─────────────────────────
    t0        = time.perf_counter()
    route_rr  = random_restart_2opt(depot, cluster_stops)
    t_rr     += time.perf_counter() - t0
    dist_rr   = route_distance(route_rr)

    # Improvement percentages vs NN baseline
    imp_2opt = (dist_nn - dist_2opt) / dist_nn * 100
    imp_rr   = (dist_nn - dist_rr)   / dist_nn * 100

    results[cid] = {
        "stops":     len(cluster_stops),
        "nn":        {"route": route_nn,  "dist": dist_nn},
        "2opt":      {"route": route_2opt,"dist": dist_2opt},
        "rr":        {"route": route_rr,  "dist": dist_rr},
        "imp_2opt":  imp_2opt,
        "imp_rr":    imp_rr,
    }

    print(f"  Van {cid:<2} {len(cluster_stops):>5}  "
          f"{dist_nn:>10.2f}  {dist_2opt:>10.2f}  {dist_rr:>12.2f}  "
          f"{imp_2opt:>7.1f}%  {imp_rr:>7.1f}%")

# Totals
total_nn   = sum(r["nn"]["dist"]   for r in results.values())
total_2opt = sum(r["2opt"]["dist"] for r in results.values())
total_rr   = sum(r["rr"]["dist"]   for r in results.values())

print(f"  {'-' * 68}")
print(f"  {'TOTAL':<8} {'':>5}  "
      f"{total_nn:>10.2f}  {total_2opt:>10.2f}  {total_rr:>12.2f}  "
      f"{(total_nn-total_2opt)/total_nn*100:>7.1f}%  "
      f"{(total_nn-total_rr)/total_nn*100:>7.1f}%")
print(f"\n  Computation time:")
print(f"    Nearest Neighbour  : {t_nn:.4f}s")
print(f"    2-opt              : {t_2opt:.4f}s")
print(f"    Random Restart 2-opt: {t_rr:.4f}s  ({RR_RESTARTS} restarts/cluster)")


# ══════════════════════════════════════════════════════════════════
# STEP 5 — SAVE CSVs  (one per algorithm)
# ══════════════════════════════════════════════════════════════════
# Each CSV has one row per stop in route order.
# stop_order = 0 is always the depot (start), and the final row
# is also the depot (return). route_km_so_far accumulates distance.

def save_routes_csv(filename, algo_key):
    fieldnames = [
        "van", "stop_order", "delivery_id", "customer_name",
        "postcode", "latitude", "longitude",
        "demand", "priority", "dist_from_prev_km", "route_km_so_far",
    ]
    rows = []
    for cid in cluster_ids:
        route = results[cid][algo_key]["route"]
        cum   = 0.0
        for order, stop in enumerate(route):
            if order == 0:
                dist_prev = 0.0
            else:
                dist_prev = haversine(
                    route[order-1]["latitude"], route[order-1]["longitude"],
                    stop["latitude"],           stop["longitude"],
                )
                cum += dist_prev
            rows.append({
                "van":              cid,
                "stop_order":       order,
                "delivery_id":      stop["delivery_id"],
                "customer_name":    stop["customer_name"],
                "postcode":         stop["postcode"],
                "latitude":         stop["latitude"],
                "longitude":        stop["longitude"],
                "demand":           stop["demand"],
                "priority":         stop["priority"],
                "dist_from_prev_km": round(dist_prev, 4),
                "route_km_so_far":  round(cum, 4),
            })
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n  Saved: {filename}  ({len(rows)} rows)")

save_routes_csv(os.path.join(DATA_DIR, "routes_nn.csv"),    "nn")
save_routes_csv(os.path.join(DATA_DIR, "routes_2opt.csv"),  "2opt")
save_routes_csv(os.path.join(DATA_DIR, "routes_rr2opt.csv"),"rr")


# ══════════════════════════════════════════════════════════════════
# STEP 6 — SAVE SUMMARY TXT
# ══════════════════════════════════════════════════════════════════
summary_lines = []
summary_lines.append("=" * 62)
summary_lines.append("  ROUTING SUMMARY — DPD Hinckley")
summary_lines.append("=" * 62)
summary_lines.append(f"\n  Input file : {INPUT_FILE}")
summary_lines.append(f"  Depot      : {depot['postcode']}")
summary_lines.append(f"  Total stops: {len(stops)}")
summary_lines.append(f"  Vans       : {len(cluster_ids)}")
summary_lines.append(f"  RR restarts: {RR_RESTARTS}")
summary_lines.append("")
summary_lines.append("  ALGORITHM COMPARISON (total km across all vans)")
summary_lines.append(f"  {'Algorithm':<25} {'Total km':>10}  {'vs NN':>8}  {'Time':>8}")
summary_lines.append(f"  {'-'*55}")
summary_lines.append(f"  {'Nearest Neighbour':<25} {total_nn:>10.2f}  {'baseline':>8}  {t_nn:.4f}s")
summary_lines.append(f"  {'2-opt (from NN)':<25} {total_2opt:>10.2f}  {(total_nn-total_2opt)/total_nn*100:>7.1f}%  {t_2opt:.4f}s")
summary_lines.append(f"  {'Random Restart 2-opt':<25} {total_rr:>10.2f}  {(total_nn-total_rr)/total_nn*100:>7.1f}%  {t_rr:.4f}s")
summary_lines.append("")
summary_lines.append("  PER-VAN BREAKDOWN")
summary_lines.append(f"  {'Van':<5} {'Stops':>5}  {'NN':>8}  {'2-opt':>8}  {'RR-2opt':>8}  {'Best':>8}")
summary_lines.append(f"  {'-'*55}")
for cid in cluster_ids:
    r    = results[cid]
    best = min(r["nn"]["dist"], r["2opt"]["dist"], r["rr"]["dist"])
    winner = ("NN" if best == r["nn"]["dist"]
              else "2-opt" if best == r["2opt"]["dist"]
              else "RR-2opt")
    summary_lines.append(
        f"  Van {cid:<2} {r['stops']:>5}  "
        f"{r['nn']['dist']:>8.2f}  {r['2opt']['dist']:>8.2f}  "
        f"{r['rr']['dist']:>8.2f}  {winner:>8}"
    )
summary_lines.append("")
summary_lines.append("  ROUTE ORDER PER VAN (Random Restart 2-opt — best result)")
summary_lines.append("")
for cid in cluster_ids:
    route = results[cid]["rr"]["route"]
    summary_lines.append(f"  Van {cid}  ({results[cid]['stops']} stops, "
                         f"{results[cid]['rr']['dist']:.2f} km)")
    for order, stop in enumerate(route):
        arrow = "→" if order < len(route)-1 else ""
        summary_lines.append(f"    {order:>2}. {stop['delivery_id']:<8} "
                             f"{stop['postcode']:<10} {stop['customer_name']}")
    summary_lines.append("")
summary_lines.append("=" * 62)

summary_text = "\n".join(summary_lines)

with open("routing_summary.txt", "w", encoding="utf-8") as f:
    f.write(summary_text)

print("\n  Saved: routing_summary.txt")
print("\n" + summary_text)