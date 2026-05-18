"""OSRM /route geometry for ordered waypoints (lon,lat)."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional


def lonlat(lat: float, lon: float) -> str:
    return f"{lon},{lat}"


def fetch_route_geometry(
    osrm_base: str,
    profile: str,
    points: List[dict],
    timeout: int = 120,
) -> Optional[Dict[str, Any]]:
    """
    GET /route/v1/{profile}/{coords}?overview=full&geometries=geojson
    points: ordered list of {latitude, longitude}
    Returns GeoJSON geometry dict (LineString) or None.
    """
    if len(points) < 2:
        return None
    coord_str = ";".join(lonlat(p["latitude"], p["longitude"]) for p in points)
    path = f"/route/v1/{profile}/{coord_str}"
    params = {
        "overview": "full",
        "geometries": "geojson",
        "steps": "false",
        "continue_straight": "false",
    }
    url = f"{osrm_base.rstrip('/')}{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if data.get("code") != "Ok" or not data.get("routes"):
        return None
    geom = data["routes"][0].get("geometry")
    if geom and geom.get("type") == "LineString":
        return geom
    return None


def route_metrics(
    osrm_base: str,
    profile: str,
    points: List[dict],
    timeout: int = 120,
    include_steps: bool = False,
) -> tuple[Optional[float], Optional[float], Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    GET /route/v1/...
    Returns (distance_km, duration_s, geometry, turns).
    If include_steps=True, turns is a flat list of maneuver summaries for navigation UI.
    """
    if len(points) < 2:
        return 0.0, 0.0, None, []
    coord_str = ";".join(lonlat(p["latitude"], p["longitude"]) for p in points)
    path = f"/route/v1/{profile}/{coord_str}"
    params: Dict[str, str] = {
        "overview": "full",
        "geometries": "geojson",
        "steps": "true" if include_steps else "false",
    }
    url = f"{osrm_base.rstrip('/')}{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None, None, None, []
    if data.get("code") != "Ok" or not data.get("routes"):
        return None, None, None, []
    r0 = data["routes"][0]
    dist_km = float(r0.get("distance", 0)) / 1000.0
    dur_s = float(r0.get("duration", 0))
    geom = r0.get("geometry")
    if geom and geom.get("type") != "LineString":
        geom = None

    turns: List[Dict[str, Any]] = []
    if include_steps:
        idx = 0
        for leg in r0.get("legs") or []:
            for step in leg.get("steps") or []:
                m = step.get("maneuver") or {}
                loc = m.get("location")
                if not loc or len(loc) < 2:
                    continue
                lon_f, lat_f = float(loc[0]), float(loc[1])
                typ = str(m.get("type") or "")
                mod = str(m.get("modifier") or "")
                street = str(step.get("name") or "").strip()
                dist_m = float(step.get("distance", 0))
                dur_step = float(step.get("duration", 0))
                hint = " ".join(x for x in (mod.replace("_", " "), typ.replace("_", " ")) if x).strip()
                if street:
                    hint = f"{hint} — {street}".strip(" —") if hint else street
                elif not hint:
                    hint = typ or "continue"
                turns.append(
                    {
                        "index": idx,
                        "instruction": hint[:200],
                        "maneuverType": typ,
                        "modifier": mod,
                        "street": street[:120],
                        "distanceM": float(round(dist_m, 1)),
                        "durationS": float(round(dur_step, 1)),
                        "lon": lon_f,
                        "lat": lat_f,
                    }
                )
                idx += 1

    return dist_km, dur_s, geom, turns


def straight_line_geometry(points: List[dict]) -> Dict[str, Any]:
    """Fallback LineString WGS84 [lon, lat]."""
    coords: List[List[float]] = []
    for p in points:
        coords.append([float(p["longitude"]), float(p["latitude"])])
    return {"type": "LineString", "coordinates": coords}
