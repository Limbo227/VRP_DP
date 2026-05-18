"""
K-means clustering (same logic as middlelands/cluster2.py) without import side effects.
"""
from __future__ import annotations

import math
from typing import List, Tuple

import numpy as np
from sklearn.cluster import KMeans

MAX_STOPS_PER_VEHICLE_DEFAULT = 20
RANDOM_SEED = 42


def run_kmeans(stops: List[dict], k: int) -> Tuple[List[int], list]:
    coords = np.array([[s["latitude"], s["longitude"]] for s in stops])
    if k == 1:
        return [0] * len(stops), coords.mean(axis=0).tolist()
    model = KMeans(
        n_clusters=k,
        n_init=10,
        random_state=RANDOM_SEED,
    )
    model.fit(coords)
    return model.labels_.tolist(), model.cluster_centers_.tolist()


def split_oversized(stops: List[dict], max_size: int) -> List[List[dict]]:
    k = math.ceil(len(stops) / max_size)
    if k <= 1:
        return [stops]
    assignments, _ = run_kmeans(stops, k)
    sub_clusters: dict[int, List[dict]] = {}
    for i, a in enumerate(assignments):
        sub_clusters.setdefault(a, []).append(stops[i])
    final: List[List[dict]] = []
    for sub in sub_clusters.values():
        if len(sub) > max_size:
            final.extend(split_oversized(sub, max_size))
        else:
            final.append(sub)
    return final


def cluster_deliveries(
    stops: List[dict], max_stops: int = MAX_STOPS_PER_VEHICLE_DEFAULT
) -> Tuple[List[List[dict]], float]:
    """Returns (list of cluster stop lists, inertia from KMeans with K=len(clusters))."""
    final = split_oversized(stops, max_stops)
    k = len(final)
    coords_all = np.array([[s["latitude"], s["longitude"]] for s in stops])
    full_model = KMeans(n_clusters=k, n_init=10, random_state=RANDOM_SEED)
    full_model.fit(coords_all)
    for cid, cluster_stops in enumerate(final):
        for s in cluster_stops:
            s["cluster"] = cid
    return final, float(full_model.inertia_)
