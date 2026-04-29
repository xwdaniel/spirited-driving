"""
Generates realistic synthetic GeoJSON for the Peak District bounding box,
mimicking what the real pipeline would produce from OSM data.
Used for local UI testing without needing live Overpass access.
"""

import json
import math
import random
import numpy as np

random.seed(42)

BBOX = (53.30, -1.95, 53.50, -1.60)  # south, west, north, east

ROAD_TEMPLATES = [
    {"name": "A537 Cat and Fiddle",         "highway": "primary",   "maxspeed": "NSL",  "style": "mountain"},
    {"name": "A54 Congleton to Buxton",     "highway": "primary",   "maxspeed": "NSL",  "style": "ridge"},
    {"name": "B5053 Onecote to Waterhouses","highway": "secondary", "maxspeed": "NSL",  "style": "valley"},
    {"name": "A515 Ashbourne to Buxton",    "highway": "primary",   "maxspeed": "NSL",  "style": "straight"},
    {"name": "B5054 Hartington to Hulme",   "highway": "secondary", "maxspeed": "NSL",  "style": "mountain"},
    {"name": "A623 Chapel to Baslow",       "highway": "primary",   "maxspeed": "NSL",  "style": "ridge"},
    {"name": "B6012 Matlock to Bakewell",   "highway": "secondary", "maxspeed": "60",   "style": "valley"},
    {"name": "A619 Bakewell to Chesterfield","highway":"primary",   "maxspeed": "NSL",  "style": "rolling"},
    {"name": "B5056 Ashbourne to Youlgreave","highway":"secondary", "maxspeed": "NSL",  "style": "mountain"},
    {"name": "A6 Buxton to Bakewell",       "highway": "trunk",     "maxspeed": "NSL",  "style": "straight"},
    {"name": "B6049 Great Hucklow Loop",    "highway": "secondary", "maxspeed": "NSL",  "style": "mountain"},
    {"name": "A625 Hathersage to Sheffield","highway": "primary",   "maxspeed": "60",   "style": "ridge"},
    {"name": "B6521 Baslow Edge Road",      "highway": "secondary", "maxspeed": "NSL",  "style": "mountain"},
    {"name": "A57 Snake Pass",              "highway": "trunk",     "maxspeed": "NSL",  "style": "mountain"},
    {"name": "B6105 Glossop to Woodhead",   "highway": "secondary", "maxspeed": "NSL",  "style": "ridge"},
    {"name": "A628 Woodhead Pass",          "highway": "trunk",     "maxspeed": "NSL",  "style": "mountain"},
    {"name": "B6013 Crich to Ambergate",    "highway": "secondary", "maxspeed": "60",   "style": "valley"},
    {"name": "A6187 Hope Valley",           "highway": "primary",   "maxspeed": "60",   "style": "valley"},
]

CAMERA_POSITIONS = [
    (-1.76, 53.33), (-1.82, 53.41), (-1.68, 53.47),
    (-1.90, 53.38), (-1.72, 53.35), (-1.65, 53.43),
]

def make_winding_coords(start_lon, start_lat, length_deg, style, n_points=20):
    """Generate a winding polyline based on road style."""
    coords = [(start_lon, start_lat)]

    style_params = {
        "mountain": {"amp": 0.012, "freq": 6, "drift": (0.008, 0.006)},
        "ridge":    {"amp": 0.008, "freq": 4, "drift": (0.010, 0.004)},
        "valley":   {"amp": 0.006, "freq": 5, "drift": (0.009, 0.005)},
        "rolling":  {"amp": 0.005, "freq": 3, "drift": (0.010, 0.005)},
        "straight": {"amp": 0.002, "freq": 2, "drift": (0.012, 0.003)},
    }
    p = style_params.get(style, style_params["rolling"])

    for i in range(1, n_points):
        t = i / n_points
        lon = start_lon + t * p["drift"][0] + p["amp"] * math.sin(t * p["freq"] * math.pi * 2)
        lat = start_lat + t * p["drift"][1] + p["amp"] * 0.6 * math.cos(t * p["freq"] * math.pi * 2 + 0.8)
        # Small random jitter for realism
        lon += random.uniform(-0.001, 0.001)
        lat += random.uniform(-0.001, 0.001)
        coords.append((round(lon, 6), round(lat, 6)))

    return coords


def haversine_m(lon1, lat1, lon2, lat2):
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def road_length_m(coords):
    return sum(haversine_m(coords[i][0], coords[i][1], coords[i+1][0], coords[i+1][1])
               for i in range(len(coords)-1))


def bearing(lon1, lat1, lon2, lat2):
    dlon = math.radians(lon2 - lon1)
    lat1r, lat2r = math.radians(lat1), math.radians(lat2)
    x = math.sin(dlon) * math.cos(lat2r)
    y = math.cos(lat1r)*math.sin(lat2r) - math.sin(lat1r)*math.cos(lat2r)*math.cos(dlon)
    return math.atan2(x, y)


BREAKPOINT_THRESHOLD = 0.0008  # must match pipeline constant

WEIGHTS = {
    "sinuosity":       0.10,
    "angular_density": 0.10,
    "corner_variety":  0.10,
    "straight_bend":   0.10,
    "elevation":       0.30,
    "speed_limit":     0.20,
    "camera_free":     0.10,
}

# Synthetic elevation scores by road style (no real DEM in test data)
_ELEVATION_BY_STYLE = {
    "mountain": 90,
    "ridge":    70,
    "valley":   35,
    "rolling":  50,
    "straight": 10,
}


def angular_changes_list(coords):
    """Returns list of absolute angular change values (radians) at each interior node."""
    angles = []
    for i in range(1, len(coords) - 1):
        b_in  = bearing(coords[i-1][0], coords[i-1][1], coords[i][0], coords[i][1])
        b_out = bearing(coords[i][0], coords[i][1], coords[i+1][0], coords[i+1][1])
        delta = abs(b_out - b_in)
        if delta > math.pi:
            delta = 2 * math.pi - delta
        angles.append(delta)
    return angles


def compute_curvature_per_node(coords):
    """Returns smoothed curvature (rad/m) at each interior node."""
    if len(coords) < 3:
        return []
    positions = [0.0]
    for i in range(1, len(coords)):
        positions.append(positions[-1] + haversine_m(
            coords[i-1][0], coords[i-1][1], coords[i][0], coords[i][1]
        ))
    angles = angular_changes_list(coords)
    curvature = []
    for i, angle in enumerate(angles):
        seg_len = positions[i + 1] - positions[i]
        seg_len = max(seg_len, 0.1)
        curvature.append(angle / seg_len)
    return curvature


def compute_scores(coords, highway, maxspeed, camera_positions, style="rolling"):
    road_len  = road_length_m(coords)
    if road_len == 0:
        road_len = 1e-6
    straight  = haversine_m(coords[0][0], coords[0][1], coords[-1][0], coords[-1][1])
    sinuosity = straight / road_len

    angles = angular_changes_list(coords)
    total_angle = sum(angles)
    ang_density = total_angle / road_len

    # score_sinuosity
    sin_score = round((1 - sinuosity) * 100, 1)

    # score_angular_density
    ang_score = round(min(ang_density / 0.004, 1.0) * 100, 1)

    # score_corner_variety (std dev of angular changes)
    if len(angles) >= 2:
        std_dev = float(np.std(angles))
        var_score = round(min(std_dev / 0.3, 1.0) * 100, 1)
    else:
        var_score = 0.0

    # score_straight_bend_ratio
    curvature = compute_curvature_per_node(coords)
    curvy_count = sum(1 for c in curvature if c >= BREAKPOINT_THRESHOLD)
    if curvy_count == 0:
        stb_score = 0.0
    else:
        straight_count = len(curvature) - curvy_count
        ratio   = straight_count / curvy_count
        optimal = 14 / 3
        stb_score = round(100 * math.exp(-0.5 * ((ratio - optimal) / 3.0) ** 2), 1)

    # score_elevation (synthetic — no DEM in test generator)
    elev_score = float(_ELEVATION_BY_STYLE.get(style, 50))

    # score_speed_limit
    tag = str(maxspeed).lower().strip()
    if tag in ("", "none", "nan", "national", "nsl"):
        sp_score = 100
    else:
        try:
            mph = int(tag)
            mp = {70: 100, 60: 80, 50: 55, 40: 35, 30: 10, 20: 0}
            sp_score = next((mp[s] for s in sorted(mp.keys(), reverse=True) if mph >= s), 0)
        except Exception:
            sp_score = 80

    # score_camera_free (radius 200m)
    camera_count = 0
    for cam_lon, cam_lat in camera_positions:
        for lon, lat in coords:
            if haversine_m(lon, lat, cam_lon, cam_lat) <= 200:
                camera_count += 1
                break
    cam_per_km = (camera_count / road_len) * 1000
    cam_score = round(max(0, 100 - cam_per_km * 100), 1)

    drive_score = round(
        sin_score  * WEIGHTS["sinuosity"] +
        ang_score  * WEIGHTS["angular_density"] +
        var_score  * WEIGHTS["corner_variety"] +
        stb_score  * WEIGHTS["straight_bend"] +
        elev_score * WEIGHTS["elevation"] +
        sp_score   * WEIGHTS["speed_limit"] +
        cam_score  * WEIGHTS["camera_free"],
        1,
    )

    return {
        "sinuosity":             round(sinuosity, 3),
        "narrow":                False,  # synthetic data — no lane/width tags
        "score_sinuosity":       sin_score,
        "score_angular_density": ang_score,
        "score_corner_variety":  var_score,
        "score_straight_bend":   stb_score,
        "score_elevation":       elev_score,
        "score_speed_limit":     sp_score,
        "score_camera_free":     cam_score,
        "drive_score":           drive_score,
    }


def generate():
    south, west, north, east = BBOX
    features = []

    lon_range = east - west
    lat_range = north - south

    for i, tmpl in enumerate(ROAD_TEMPLATES):
        # Spread roads across the bbox
        start_lon = west  + (i % 5)  * (lon_range / 5)  + random.uniform(0, lon_range/6)
        start_lat = south + (i // 5) * (lat_range / 3.5) + random.uniform(0, lat_range/5)
        start_lon = min(start_lon, east  - 0.05)
        start_lat = min(start_lat, north - 0.03)

        coords = make_winding_coords(start_lon, start_lat, 0.1, tmpl["style"])

        # Split each road into 2–3 segments to mimic real segmentation
        n_splits = random.randint(1, 3)
        split_points = sorted(random.sample(range(3, len(coords)-3), min(n_splits, len(coords)-6)))
        split_points = [0] + split_points + [len(coords)]

        for j in range(len(split_points)-1):
            seg_coords = coords[split_points[j]:split_points[j+1]+1]
            if len(seg_coords) < 3:
                continue

            scores = compute_scores(seg_coords, tmpl["highway"], tmpl["maxspeed"], CAMERA_POSITIONS, tmpl["style"])
            length_m = road_length_m(seg_coords)

            seg_name = tmpl["name"]
            if n_splits > 1:
                seg_name += f" (section {j+1})"

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": seg_coords
                },
                "properties": {
                    "name":               seg_name,
                    "highway":            tmpl["highway"],
                    "maxspeed":           tmpl["maxspeed"],
                    "length_m":           round(length_m),
                    **scores
                }
            })

    features.sort(key=lambda f: f["properties"]["drive_score"], reverse=True)

    geojson = {"type": "FeatureCollection", "features": features}

    out = "apexline_segments.geojson"
    with open(out, "w") as f:
        json.dump(geojson, f, indent=2)

    print(f"Generated {len(features)} segments → {out}")
    print(f"\nTop 5:")
    for feat in features[:5]:
        p = feat["properties"]
        print(f"  {p['name']:<40} score={p['drive_score']:>5}  sinuosity={p['sinuosity']}  len={p['length_m']}m")

    return geojson


if __name__ == "__main__":
    generate()
