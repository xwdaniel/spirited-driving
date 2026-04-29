"""
Apexline FastAPI backend

Endpoints:
  GET  /geocode?q=<place>                    — Nominatim geocoding → bounding box
  GET  /segments?south=&west=&north=&east=   — Run scoring pipeline for bbox
  GET  /segments/cached                      — Serve last-written geojson
  POST /route                                — Plan a spirited route

Usage:
    pip install fastapi uvicorn requests
    uvicorn apexline_server:app --reload --port 8000
"""

import json
import math
import os
from pathlib import Path
from typing import Optional

import requests as http
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

app = FastAPI(title="Apexline API", version="0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

CACHE_PATH = Path("apexline_segments.geojson")


# ─────────────────────────────────────────────
# GEOCODE
# ─────────────────────────────────────────────

@app.get("/geocode")
def geocode(q: str = Query(..., description="Place name to search, e.g. 'Peak District'")):
    """
    Geocode a place name via Nominatim and return a bounding box.
    Response: { name, bbox: { south, west, north, east } }
    """
    try:
        resp = http.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": q, "format": "json", "limit": 1},
            headers={"User-Agent": "Apexline/0.1 (spirited-driving)"},
            timeout=10,
        )
        resp.raise_for_status()
    except http.exceptions.RequestException as e:
        raise HTTPException(502, f"Nominatim request failed: {e}")

    results = resp.json()
    if not results:
        raise HTTPException(404, f"No place found for '{q}'")

    r = results[0]
    bb = r["boundingbox"]  # Nominatim: [minlat, maxlat, minlon, maxlon]

    return {
        "name": r["display_name"].split(",")[0].strip(),
        "full_name": r["display_name"],
        "bbox": {
            "south": float(bb[0]),
            "north": float(bb[1]),
            "west":  float(bb[2]),
            "east":  float(bb[3]),
        },
    }


# ─────────────────────────────────────────────
# SEGMENTS — live pipeline
# ─────────────────────────────────────────────

@app.get("/segments")
def get_segments(
    south: float = Query(53.30, description="South latitude"),
    west:  float = Query(-1.95, description="West longitude"),
    north: float = Query(53.50, description="North latitude"),
    east:  float = Query(-1.60, description="East longitude"),
):
    """
    Run the full scoring pipeline for the given bounding box.
    Results are also written to apexline_segments.geojson as a cache.

    Note: this may take 30–90 s on first run (Overpass API + processing).
    """
    # Basic sanity checks
    if south >= north:
        raise HTTPException(400, "south must be less than north")
    if west >= east:
        raise HTTPException(400, "west must be less than east")
    if (north - south) > 2.0 or (east - west) > 2.0:
        raise HTTPException(400, "Bounding box too large — max 2° per side")

    from apexline_pipeline import run_pipeline  # lazy import; heavy dependencies

    try:
        geojson = run_pipeline((south, west, north, east))
    except Exception as e:
        raise HTTPException(500, f"Pipeline error: {e}")

    return JSONResponse(content=geojson)


# ─────────────────────────────────────────────
# SEGMENTS — cached
# ─────────────────────────────────────────────

@app.get("/segments/cached")
def get_cached():
    """
    Return the last GeoJSON written to disk by the pipeline.
    Run generate_test_data.py or apexline_pipeline.py first.
    """
    if not CACHE_PATH.exists():
        raise HTTPException(
            404,
            "No cached data found. Run 'python generate_test_data.py' "
            "or 'python apexline_pipeline.py' first.",
        )
    return JSONResponse(content=json.loads(CACHE_PATH.read_text()))


# ─────────────────────────────────────────────
# HEALTH
# ─────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "cached": CACHE_PATH.exists()}


# ─────────────────────────────────────────────
# CONFIG — public client configuration
# ─────────────────────────────────────────────

@app.get("/config")
def config():
    """
    Return public client configuration.
    MAPBOX_TOKEN must be set in the environment before starting the server.
    """
    token = os.environ.get("MAPBOX_TOKEN", "")
    if not token:
        raise HTTPException(500, "MAPBOX_TOKEN environment variable is not set")
    return {"mapbox_token": token}


# ─────────────────────────────────────────────
# ROUTE — spirited route planner
# ─────────────────────────────────────────────

# Average speed assumption for time-budget → distance conversion (km/h)
_AVG_SPEED_KMH = 60

# Maximum waypoints passed to Mapbox Directions (API limit: 25)
_MAX_MAPBOX_WAYPOINTS = 25

# Maximum waypoints in the Google Maps URL (URL length limit)
_MAX_GMAPS_WAYPOINTS = 9


class RouteRequest(BaseModel):
    start_lon: float
    start_lat: float
    end_lon: Optional[float] = None   # None → loop (end = start)
    end_lat: Optional[float] = None
    hours: float                       # time budget in hours
    mapbox_token: str                  # passed from frontend; not stored


def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _segment_midpoint(coords: list) -> tuple:
    """Return the midpoint coordinate of a LineString coordinate list."""
    if len(coords) < 2:
        return coords[0]
    target = sum(
        _haversine_km(coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1])
        for i in range(len(coords) - 1)
    ) / 2
    cumulative = 0.0
    for i in range(len(coords) - 1):
        seg_len = _haversine_km(coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1])
        if cumulative + seg_len >= target:
            frac = (target - cumulative) / seg_len if seg_len > 0 else 0
            lon = coords[i][0] + frac * (coords[i + 1][0] - coords[i][0])
            lat = coords[i][1] + frac * (coords[i + 1][1] - coords[i][1])
            return (lon, lat)
        cumulative += seg_len
    return coords[-1]


def _greedy_waypoints(
    features: list,
    start: tuple,
    end: tuple,
    budget_km: float,
    max_waypoints: int,
) -> list:
    """
    Greedy selection of segment midpoints as waypoints.

    Iterates scored segments (descending drive_score). For each candidate,
    checks whether inserting its midpoint into the current ordered route
    stays within budget_km using straight-line distances as a proxy.

    Returns ordered list of (lon, lat) waypoints including start and end.
    """
    route = [start, end]  # current ordered waypoint list
    used_km = _haversine_km(*start, *end)

    for feat in features:
        if len(route) - 2 >= max_waypoints:
            break
        coords = feat["geometry"]["coordinates"]
        if not coords:
            continue
        mid = _segment_midpoint(coords)

        # Find best insertion position (minimises added distance)
        best_cost = float("inf")
        best_pos = 1
        for i in range(1, len(route)):
            prev, nxt = route[i - 1], route[i]
            added = (
                _haversine_km(*prev, *mid) +
                _haversine_km(*mid, *nxt) -
                _haversine_km(*prev, *nxt)
            )
            if added < best_cost:
                best_cost = added
                best_pos = i

        if used_km + best_cost <= budget_km:
            route.insert(best_pos, mid)
            used_km += best_cost

    return route


@app.post("/route")
def plan_route(req: RouteRequest):
    """
    Plan a spirited route.

    1. Expands a bounding box around start/end proportional to the time budget.
    2. Runs the scoring pipeline for that bbox.
    3. Greedily selects segment midpoints as waypoints within the budget.
    4. Stitches waypoints via Mapbox Directions API.
    5. Returns route GeoJSON, summary stats, and a Google Maps URL.
    """
    if req.hours <= 0 or req.hours > 24:
        raise HTTPException(400, "hours must be between 0 and 24")

    budget_km = req.hours * _AVG_SPEED_KMH

    # Loop if end not specified
    end_lon = req.end_lon if req.end_lon is not None else req.start_lon
    end_lat = req.end_lat if req.end_lat is not None else req.start_lat
    is_loop = (end_lon == req.start_lon and end_lat == req.start_lat)

    start = (req.start_lon, req.start_lat)
    end   = (end_lon, end_lat)

    # Bounding box: pad around start+end by half the budget radius
    # Budget radius ≈ budget_km / 2 (out-and-back), converted to degrees
    # 1° lat ≈ 111 km; 1° lon ≈ 111 km × cos(lat)
    pad_lat = (budget_km / 2) / 111.0
    mid_lat  = (req.start_lat + end_lat) / 2
    mid_lon  = (req.start_lon + end_lon) / 2
    pad_lon = (budget_km / 2) / (111.0 * max(math.cos(math.radians(mid_lat)), 0.1))

    south = min(req.start_lat, end_lat) - pad_lat
    north = max(req.start_lat, end_lat) + pad_lat
    west  = min(req.start_lon, end_lon) - pad_lon
    east  = max(req.start_lon, end_lon) + pad_lon

    # Cap bbox to avoid enormous pipeline runs
    if (north - south) > 3.0:
        north = mid_lat + 1.5
        south = mid_lat - 1.5
    if (east - west) > 3.0:
        east = mid_lon + 1.5
        west = mid_lon - 1.5

    from apexline_pipeline import run_pipeline
    try:
        geojson = run_pipeline((south, west, north, east))
    except Exception as e:
        raise HTTPException(500, f"Pipeline error: {e}")

    features = geojson.get("features", [])
    if not features:
        raise HTTPException(404, "No scored roads found in this area")

    # Greedy waypoint selection (pipeline already sorted by drive_score desc)
    waypoints = _greedy_waypoints(
        features, start, end, budget_km,
        max_waypoints=_MAX_MAPBOX_WAYPOINTS - 2,  # reserve slots for start/end
    )

    # Stitch with Mapbox Directions
    coords_str = ";".join(f"{lon},{lat}" for lon, lat in waypoints)
    mapbox_url = (
        f"https://api.mapbox.com/directions/v5/mapbox/driving/{coords_str}"
        f"?geometries=geojson&overview=full&access_token={req.mapbox_token}"
    )
    try:
        mb_resp = http.get(mapbox_url, timeout=15)
        mb_resp.raise_for_status()
        mb_data = mb_resp.json()
    except Exception as e:
        raise HTTPException(502, f"Mapbox Directions error: {e}")

    routes = mb_data.get("routes", [])
    if not routes:
        raise HTTPException(502, "Mapbox Directions returned no route")

    route_data = routes[0]
    route_geom = route_data["geometry"]          # GeoJSON LineString
    route_distance_km = route_data["distance"] / 1000
    route_duration_h  = route_data["duration"] / 3600

    # Identify which scored segments the route threads through
    # (those whose midpoints became waypoints, excluding start/end)
    selected_midpoints = set(
        (round(lon, 5), round(lat, 5))
        for lon, lat in waypoints[1:-1]
    )
    included_segments = []
    total_score = 0.0
    for feat in features:
        coords = feat["geometry"]["coordinates"]
        if not coords:
            continue
        mid = _segment_midpoint(coords)
        if (round(mid[0], 5), round(mid[1], 5)) in selected_midpoints:
            included_segments.append(feat)
            total_score += feat["properties"].get("drive_score", 0)

    avg_score = round(total_score / len(included_segments), 1) if included_segments else 0

    # Google Maps URL — top 9 waypoints by drive_score (excluding start/end)
    gmaps_waypoints = waypoints[1:-1][:_MAX_GMAPS_WAYPOINTS]
    gmaps_parts = [f"{req.start_lat},{req.start_lon}"]
    for lon, lat in gmaps_waypoints:
        gmaps_parts.append(f"{lat},{lon}")
    gmaps_parts.append(f"{end_lat},{end_lon}")
    gmaps_url = "https://www.google.com/maps/dir/" + "/".join(gmaps_parts)

    return {
        "route": {
            "type": "Feature",
            "geometry": route_geom,
            "properties": {
                "distance_km":       round(route_distance_km, 1),
                "duration_hours":    round(route_duration_h, 2),
                "segments_included": len(included_segments),
                "avg_drive_score":   avg_score,
                "is_loop":           is_loop,
            },
        },
        "included_segments": {
            "type": "FeatureCollection",
            "features": included_segments,
        },
        "google_maps_url": gmaps_url,
    }
