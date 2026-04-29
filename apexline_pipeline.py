"""
Apexline - Spirited Driving Road Scorer
Pipeline v0.2

Steps:
  1. Fetch road network for a bounding box via osmnx (Overpass API)
  2. Fetch speed cameras and junction/interruption nodes from Overpass
  3. Compute per-edge sinuosity + angular density
  4. Segment roads by curvature character (breakpoint detection)
  5. Score each segment across 9 factors: sinuosity, angular density, corner
     variety, straight-to-bend ratio, elevation change, speed limit, camera
     density, junction density, road surface
  6. Output scored GeoJSON ready for Mapbox
"""

import json
import math
import warnings
import numpy as np
import osmnx as ox
import geopandas as gpd
from shapely.geometry import LineString, mapping
from shapely.ops import split, snap
import requests

warnings.filterwarnings("ignore")

# Optional SRTM elevation library — gracefully absent
try:
    import srtm as _srtm_lib
    _srtm_data = _srtm_lib.get_data()
    _ELEVATION_AVAILABLE = True
except Exception:
    _ELEVATION_AVAILABLE = False
    _srtm_data = None

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

# Peak District bounding box (south, west, north, east)
BBOX = (53.30, -1.95, 53.50, -1.60)

# Road types to include — no motorways, no country lanes
ROAD_TYPES = ["primary", "secondary", "tertiary", "trunk",
              "primary_link", "secondary_link", "trunk_link"]

# Scoring weights (must sum to 1.0)
WEIGHTS = {
    "sinuosity":       0.10,  # inverted sinuosity ratio
    "angular_density": 0.10,  # turns per metre
    "corner_variety":  0.10,  # std dev of angular changes
    "straight_bend":   0.10,  # straight-to-bend ratio vs ~14:3 optimal (Tilke)
    "elevation":       0.30,  # elevation gain+loss per km (SRTM)
    "speed_limit":     0.20,  # OSM maxspeed tag
    "camera_free":     0.10,  # absence of speed cameras
}

# Segmentation: minimum segment length in metres before merging
MIN_SEGMENT_METRES = 2000

# Hard filter: minimum output segment length in metres
MIN_OUTPUT_METRES = 1000

# Hard filter: sinuosity. sinuosity_ratio() returns straight/road (≤ 1.0).
# Exclude segments where straight/road > threshold (i.e. too straight).
# 1/1.05 ≈ 0.952: road must be at least 5% longer than straight-line distance.
_MAX_SINUOSITY_RATIO = 1.0 / 1.05  # ≈ 0.952

# Hard filter: maximum junction density (junctions per km)
MAX_JUNCTION_DENSITY_PER_KM = 0.5

# Hard filter: minimum resolved speed limit in mph to include a segment
MIN_SPEED_LIMIT_MPH = 41  # excludes ≤ 40 mph (urban roads)

# Score cap for narrow roads (lanes=1 or width < 4.5m)
NARROW_ROAD_SCORE_CAP = 50

# Narrow road width threshold in metres
NARROW_WIDTH_M = 4.5

# Angular smoothing window (number of nodes)
SMOOTH_WINDOW = 5

# Curvature breakpoint threshold (radians per metre — drop below this = "straight")
BREAKPOINT_THRESHOLD = 0.0008

# Camera influence radius in metres
CAMERA_RADIUS_M = 500


# ─────────────────────────────────────────────
# STEP 1: FETCH ROAD NETWORK
# ─────────────────────────────────────────────

def fetch_roads(bbox):
    print(f"  Fetching road network for bbox {bbox}...")
    south, west, north, east = bbox

    cf = '["highway"~"' + "|".join(ROAD_TYPES) + '"]["junction"!="roundabout"]'
    try:
        # osmnx >= 1.7: bbox as positional tuple (left, bottom, right, top) i.e. (west, south, east, north)
        G = ox.graph_from_bbox(
            (west, south, east, north),
            custom_filter=cf,
            simplify=True,
            retain_all=False,
        )
    except TypeError:
        # osmnx < 1.7: separate positional args (north, south, east, west)
        G = ox.graph_from_bbox(
            north, south, east, west,
            custom_filter=cf,
            simplify=True,
            retain_all=False,
        )

    # Convert to GeoDataFrame of edges
    _, edges = ox.graph_to_gdfs(G)
    edges = edges.reset_index()
    print(f"  → {len(edges)} road edges fetched")
    return edges


# ─────────────────────────────────────────────
# STEP 2: FETCH SPEED CAMERAS (OSM Overpass)
# ─────────────────────────────────────────────

def fetch_cameras(bbox):
    print("  Fetching speed cameras from Overpass...")
    south, west, north, east = bbox
    query = f"""
    [out:json][timeout:30];
    node["highway"="speed_camera"]({south},{west},{north},{east});
    out body;
    """
    try:
        resp = requests.post(
            "https://overpass-api.de/api/interpreter",
            data={"data": query},
            timeout=30
        )
        resp.raise_for_status()
        elements = resp.json().get("elements", [])
        cameras = [(el["lon"], el["lat"]) for el in elements]
        print(f"  → {len(cameras)} speed cameras found")
        return cameras
    except Exception as e:
        print(f"  ⚠ Camera fetch failed ({e}), continuing without camera data")
        return []


def fetch_junctions(bbox):
    """Fetch traffic signals and stop signs — used as interruption penalty."""
    print("  Fetching junction/interruption nodes from Overpass...")
    south, west, north, east = bbox
    query = f"""
    [out:json][timeout:30];
    (
      node["highway"="traffic_signals"]({south},{west},{north},{east});
      node["highway"="stop"]({south},{west},{north},{east});
    );
    out body;
    """
    try:
        resp = requests.post(
            "https://overpass-api.de/api/interpreter",
            data={"data": query},
            timeout=30
        )
        resp.raise_for_status()
        elements = resp.json().get("elements", [])
        junctions = [(el["lon"], el["lat"]) for el in elements]
        print(f"  → {len(junctions)} junction/interruption nodes found")
        return junctions
    except Exception as e:
        print(f"  ⚠ Junction fetch failed ({e}), continuing without junction data")
        return []


# ─────────────────────────────────────────────
# STEP 3: GEOMETRY HELPERS
# ─────────────────────────────────────────────

def haversine_m(lon1, lat1, lon2, lat2):
    """Distance in metres between two lon/lat points."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def road_length_m(coords):
    """Total length of a polyline in metres."""
    return sum(
        haversine_m(coords[i][0], coords[i][1], coords[i+1][0], coords[i+1][1])
        for i in range(len(coords) - 1)
    )


def bearing(lon1, lat1, lon2, lat2):
    """Initial bearing in radians from point 1 to point 2."""
    dlon = math.radians(lon2 - lon1)
    lat1r, lat2r = math.radians(lat1), math.radians(lat2)
    x = math.sin(dlon) * math.cos(lat2r)
    y = math.cos(lat1r)*math.sin(lat2r) - math.sin(lat1r)*math.cos(lat2r)*math.cos(dlon)
    return math.atan2(x, y)


def angular_changes(coords):
    """
    Returns array of (position_m, abs_angular_change_rad) for each interior node.
    position_m is cumulative distance from start.
    """
    if len(coords) < 3:
        return np.array([]), np.array([])

    positions = [0.0]
    for i in range(1, len(coords)):
        positions.append(positions[-1] + haversine_m(
            coords[i-1][0], coords[i-1][1], coords[i][0], coords[i][1]
        ))

    angles = []
    pos_out = []
    for i in range(1, len(coords) - 1):
        b_in  = bearing(coords[i-1][0], coords[i-1][1], coords[i][0],   coords[i][1])
        b_out = bearing(coords[i][0],   coords[i][1],   coords[i+1][0], coords[i+1][1])
        delta = abs(b_out - b_in)
        if delta > math.pi:
            delta = 2*math.pi - delta
        angles.append(delta)
        pos_out.append(positions[i])

    return np.array(pos_out), np.array(angles)


def smooth(arr, window):
    """Simple rolling average."""
    if len(arr) < window:
        return arr
    kernel = np.ones(window) / window
    return np.convolve(arr, kernel, mode='same')


# ─────────────────────────────────────────────
# STEP 4: SINUOSITY-BASED SEGMENTATION
# ─────────────────────────────────────────────

def compute_curvature_per_metre(coords):
    """Returns curvature signal: radians per metre at each interior node."""
    positions, angles = angular_changes(coords)
    if len(positions) == 0:
        return np.array([]), np.array([])

    # Segment lengths between nodes
    seg_lengths = np.diff([0.0] + list(positions))
    seg_lengths = np.where(seg_lengths < 0.1, 0.1, seg_lengths)  # avoid div/0

    curvature = angles / seg_lengths
    smoothed  = smooth(curvature, SMOOTH_WINDOW)
    return positions, smoothed


def find_breakpoints(positions, curvature, total_length):
    """
    Identify indices where road transitions from twisty ↔ straight.
    Returns list of split distances (metres from start).
    """
    if len(curvature) == 0:
        return []

    # Binary: is this node in a "curvy" zone?
    is_curvy = curvature >= BREAKPOINT_THRESHOLD
    breakpoints_m = []

    for i in range(1, len(is_curvy)):
        if is_curvy[i] != is_curvy[i-1]:
            breakpoints_m.append(positions[i])

    return breakpoints_m


def split_linestring_at_distances(linestring, distances_m):
    """
    Split a LineString at given cumulative distances (metres).
    Returns list of LineString segments.
    """
    coords = list(linestring.coords)
    total = road_length_m(coords)

    if not distances_m or total < MIN_SEGMENT_METRES * 2:
        return [linestring]

    # Build cumulative distance array for each node
    cum = [0.0]
    for i in range(1, len(coords)):
        cum.append(cum[-1] + haversine_m(
            coords[i-1][0], coords[i-1][1], coords[i][0], coords[i][1]
        ))

    segments = []
    current_start = 0

    for split_dist in sorted(distances_m):
        # Find the node just before the split point
        split_idx = next((i for i, c in enumerate(cum) if c >= split_dist), len(cum)-1)

        seg_coords = coords[current_start:split_idx+1]
        if len(seg_coords) >= 2:
            seg_len = road_length_m(seg_coords)
            if seg_len >= MIN_SEGMENT_METRES:
                segments.append(LineString(seg_coords))
                current_start = split_idx

    # Add remainder
    remainder = coords[current_start:]
    if len(remainder) >= 2:
        rem_len = road_length_m(remainder)
        if rem_len >= MIN_SEGMENT_METRES and segments:
            segments.append(LineString(remainder))
        elif segments:
            # Merge short remainder into last segment
            last = list(segments[-1].coords)
            segments[-1] = LineString(last + remainder[1:])
        else:
            segments.append(LineString(remainder))

    return segments if segments else [linestring]


# ─────────────────────────────────────────────
# STEP 5: SCORING
# ─────────────────────────────────────────────

# ── Windiness sub-scores ────────────────────

def score_sinuosity(coords):
    """0–100. Higher score for more winding roads (lower straight-line ratio)."""
    if len(coords) < 2:
        return 0
    straight = haversine_m(coords[0][0], coords[0][1], coords[-1][0], coords[-1][1])
    road_dist = road_length_m(coords)
    if road_dist < 1:
        return 0
    sinuosity = straight / road_dist  # 1.0 = dead straight
    return round((1 - sinuosity) * 100, 1)


def score_angular_density(coords):
    """0–100. Higher score for denser angular change per metre."""
    if len(coords) < 3:
        return 0
    road_dist = road_length_m(coords)
    if road_dist < 1:
        return 0
    _, angles = angular_changes(coords)
    total_turn = float(np.sum(angles)) if len(angles) else 0.0
    ang_density = total_turn / road_dist  # radians/metre
    return round(min(ang_density / 0.004, 1.0) * 100, 1)


def score_corner_variety(coords):
    """0–100. Higher score for greater variety in corner sizes (std dev of angular changes).
    A road mixing hairpins with fast sweepers scores higher than one with uniform bends."""
    if len(coords) < 3:
        return 0
    _, angles = angular_changes(coords)
    if len(angles) < 2:
        return 0
    std_dev = float(np.std(angles))
    # 0.3 rad std dev represents good variety (hairpins mixed with sweepers)
    return round(min(std_dev / 0.3, 1.0) * 100, 1)


def score_straight_bend_ratio(coords):
    """0–100. Peaks at ~14:3 straight-to-bend ratio per Tilke/Hadley study of A591.
    Scores 0 for all-straight roads; uses Gaussian centred on the optimal ratio."""
    if len(coords) < 3:
        return 0
    positions, curvature = compute_curvature_per_metre(coords)
    if len(curvature) == 0:
        return 0
    is_curvy = curvature >= BREAKPOINT_THRESHOLD
    curvy_count = int(np.sum(is_curvy))
    if curvy_count == 0:
        return 0  # entirely straight = no rhythmic engagement
    straight_count = len(is_curvy) - curvy_count
    ratio = straight_count / curvy_count
    optimal = 14 / 3  # ~4.67 per Tilke study
    # Gaussian: 100 at optimal, sigma = 3 so it's permissive either side
    score = 100 * math.exp(-0.5 * ((ratio - optimal) / 3.0) ** 2)
    return round(score, 1)


def score_windiness(coords):
    """0–100. Combined windiness score (equal-weighted average of 4 sub-scores).
    Kept as a convenience function; in the final composite each sub-score is
    weighted independently via WEIGHTS."""
    if len(coords) < 3:
        return 0
    road_dist = road_length_m(coords)
    if road_dist < 1:
        return 0
    sin = score_sinuosity(coords)
    ang = score_angular_density(coords)
    var = score_corner_variety(coords)
    stb = score_straight_bend_ratio(coords)
    return round((sin + ang + var + stb) / 4, 1)


# ── Elevation ───────────────────────────────

def score_elevation(coords):
    """0–100. Scores cumulative elevation change (gain + loss) per km using SRTM data.
    Returns 50 (neutral) when SRTM is unavailable so missing data doesn't crater scores."""
    if not _ELEVATION_AVAILABLE or _srtm_data is None:
        return 50
    if len(coords) < 2:
        return 0

    elevations = []
    for lon, lat in coords:
        try:
            elev = _srtm_data.get_elevation(lat, lon)
        except Exception:
            elev = None
        elevations.append(elev)

    valid_pairs = [
        (elevations[i], elevations[i + 1])
        for i in range(len(elevations) - 1)
        if elevations[i] is not None and elevations[i + 1] is not None
    ]
    if not valid_pairs:
        return 50

    total_change = sum(abs(b - a) for a, b in valid_pairs)
    road_dist = road_length_m(coords)
    if road_dist < 1:
        return 0
    change_per_km = (total_change / road_dist) * 1000
    # 30 m/km is a very hilly road (e.g. A537 Cat and Fiddle ≈ 33 m/km)
    return round(min(change_per_km / 30.0, 1.0) * 100, 1)


# ── Speed limit ─────────────────────────────

def score_speed_limit(maxspeed_tag):
    """0–100. NSL/national = 100, 60 = 80, 50 = 55, 40 = 35, 30 = 10, 20 = 0."""
    mph = resolve_speed_mph(maxspeed_tag)
    if mph == 999:
        return 100
    speed_map = {70: 100, 60: 80, 50: 55, 40: 35, 30: 10, 20: 0}
    for threshold in sorted(speed_map.keys(), reverse=True):
        if mph >= threshold:
            return speed_map[threshold]
    return 0


# ── Cameras ─────────────────────────────────

def score_cameras(segment_geom, camera_coords, radius_m=200):
    """0–100. Penalises camera density along the segment."""
    if not camera_coords:
        return 100

    coords = list(segment_geom.coords)
    length = road_length_m(coords)
    if length < 1:
        return 100

    count = 0
    for cam_lon, cam_lat in camera_coords:
        for lon, lat in coords:
            if haversine_m(lon, lat, cam_lon, cam_lat) <= radius_m:
                count += 1
                break

    cameras_per_km = (count / length) * 1000
    # 0 = 100, 0.5/km = 50, 1/km+ = 0
    return round(max(0, 100 - cameras_per_km * 100), 1)


# ── Hard filter helpers ───────────────────────

def junction_density_per_km(segment_geom, junction_coords, radius_m=100):
    """Returns junctions per km along the segment (traffic signals + stop signs)."""
    if not junction_coords:
        return 0.0
    coords = list(segment_geom.coords)
    length = road_length_m(coords)
    if length < 1:
        return 0.0
    count = 0
    for junc_lon, junc_lat in junction_coords:
        for lon, lat in coords:
            if haversine_m(lon, lat, junc_lon, junc_lat) <= radius_m:
                count += 1
                break
    return (count / length) * 1000


def resolve_speed_mph(maxspeed_tag):
    """Returns resolved speed in mph. NSL/national tags return 999."""
    tag = str(maxspeed_tag).lower().strip() if maxspeed_tag else ""
    if tag in ("", "none", "nan", "national", "nsl", "signals"):
        return 999
    try:
        mph = int(tag.replace("mph", "").replace("kmh", "").replace(" ", "").strip())
        if mph > 100:
            mph = round(mph * 0.621371)
        return mph
    except Exception:
        return 999


def is_narrow_road(lanes_tag, width_tag):
    """Returns True if the road is narrow (lanes=1 or width < NARROW_WIDTH_M)."""
    if lanes_tag is not None:
        try:
            lanes = int(str(lanes_tag).strip().split(";")[0])
            if lanes == 1:
                return True
        except Exception:
            pass
    if width_tag is not None:
        try:
            w = float(str(width_tag).strip().replace("m", ""))
            if w < NARROW_WIDTH_M:
                return True
        except Exception:
            pass
    return False


# ── Composite ────────────────────────────────

def compute_drive_score(sin, ang, var, stb, elev, spd, cam):
    """Weighted composite score from 7 sub-scores (each 0–100)."""
    return round(
        sin  * WEIGHTS["sinuosity"] +
        ang  * WEIGHTS["angular_density"] +
        var  * WEIGHTS["corner_variety"] +
        stb  * WEIGHTS["straight_bend"] +
        elev * WEIGHTS["elevation"] +
        spd  * WEIGHTS["speed_limit"] +
        cam  * WEIGHTS["camera_free"],
        1
    )


def sinuosity_ratio(coords):
    if len(coords) < 2:
        return 1.0
    straight = haversine_m(coords[0][0], coords[0][1], coords[-1][0], coords[-1][1])
    road     = road_length_m(coords)
    return round(straight / road, 3) if road > 0 else 1.0


# ─────────────────────────────────────────────
# STEP 6: MAIN PIPELINE
# ─────────────────────────────────────────────

def run_pipeline(bbox):
    print("\n=== Apexline Pipeline ===\n")

    print("[1/4] Fetching data...")
    edges     = fetch_roads(bbox)
    cameras   = fetch_cameras(bbox)
    junctions = fetch_junctions(bbox)

    print("\n[2/4] Computing curvature and segmenting roads...")
    all_segments = []

    for _, row in edges.iterrows():
        geom = row.get("geometry")
        if geom is None or geom.is_empty:
            continue

        coords = list(geom.coords)
        if len(coords) < 2:
            continue

        # Compute curvature signal
        positions, curvature = compute_curvature_per_metre(coords)

        # Find breakpoints
        total_len = road_length_m(coords)
        breakpoints = find_breakpoints(positions, curvature, total_len)

        # Split geometry
        sub_segments = split_linestring_at_distances(geom, breakpoints)

        highway = row.get("highway", "secondary")
        if isinstance(highway, list):
            highway = highway[0]
        if not isinstance(highway, str):
            highway = "secondary"

        maxspeed = row.get("maxspeed", None)
        if isinstance(maxspeed, list):
            # osmnx simplification merges edges with different speed limits into
            # a list. Take the most permissive value so a road that is NSL for
            # most of its length isn't downgraded by a short village 30mph section.
            def _mph_val(tag):
                t = str(tag).lower().strip()
                if t in ("", "none", "nan", "national", "nsl", "signals"):
                    return 999  # NSL beats any numeric value
                try:
                    return int(t.replace("mph", "").replace(" mph", "").strip())
                except ValueError:
                    return 0
            maxspeed = max(maxspeed, key=_mph_val)

        # Hard filter: speed limit ≤ 40 mph
        resolved_mph = resolve_speed_mph(maxspeed)
        if resolved_mph < MIN_SPEED_LIMIT_MPH:
            continue

        lanes = row.get("lanes", None)
        if isinstance(lanes, list):
            lanes = lanes[0]

        width = row.get("width", None)
        if isinstance(width, list):
            width = width[0]

        narrow = is_narrow_road(lanes, width)

        name = row.get("name", "Unnamed road")
        if isinstance(name, list):
            name = name[0]
        if not isinstance(name, str):
            name = "Unnamed road"

        for seg in sub_segments:
            seg_coords = list(seg.coords)

            # Skip segments with non-finite coordinates (can occur in degenerate OSM edges)
            if not all(math.isfinite(c) for pt in seg_coords for c in pt):
                continue

            seg_len = road_length_m(seg_coords)

            # Hard filter: minimum output length
            if seg_len < MIN_OUTPUT_METRES:
                continue

            # Hard filter: sinuosity ratio (straight/road — lower = more winding)
            sin_ratio = sinuosity_ratio(seg_coords)
            if sin_ratio > _MAX_SINUOSITY_RATIO:
                continue

            # Hard filter: junction density
            junc_density = junction_density_per_km(seg, junctions)
            if junc_density > MAX_JUNCTION_DENSITY_PER_KM:
                continue

            sin  = score_sinuosity(seg_coords)
            ang  = score_angular_density(seg_coords)
            var  = score_corner_variety(seg_coords)
            stb  = score_straight_bend_ratio(seg_coords)
            elev = score_elevation(seg_coords)
            sp   = score_speed_limit(maxspeed)
            cam  = score_cameras(seg, cameras)
            ds   = compute_drive_score(sin, ang, var, stb, elev, sp, cam)

            if not math.isfinite(ds):
                continue

            # Score cap for narrow roads
            if narrow:
                ds = min(ds, NARROW_ROAD_SCORE_CAP)

            all_segments.append({
                "geometry": seg,
                "name":     name,
                "highway":  highway,
                "maxspeed": str(maxspeed) if maxspeed and str(maxspeed).lower().strip() not in ("nan", "none", "") else "NSL",
                "length_m": round(seg_len),
                "sinuosity": sin_ratio,
                "narrow":   narrow,
                "score_sinuosity":       sin,
                "score_angular_density": ang,
                "score_corner_variety":  var,
                "score_straight_bend":   stb,
                "score_elevation":       elev,
                "score_speed_limit":     sp,
                "score_camera_free":     cam,
                "drive_score":           ds,
            })

    print(f"  → {len(all_segments)} segments produced from {len(edges)} edges")

    print("\n[3/4] Building GeoJSON...")
    features = []
    for seg in all_segments:
        features.append({
            "type": "Feature",
            "geometry": mapping(seg["geometry"]),
            "properties": {k: v for k, v in seg.items() if k != "geometry"}
        })

    # Sort by drive score descending
    features.sort(key=lambda f: f["properties"]["drive_score"], reverse=True)

    geojson = {"type": "FeatureCollection", "features": features}

    output_path = "apexline_segments.geojson"
    with open(output_path, "w") as f:
        json.dump(geojson, f, indent=2)

    print(f"  → Saved to {output_path}")

    print("\n[4/4] Summary stats...")
    scores = [f["properties"]["drive_score"] for f in features]
    top10  = [f["properties"] for f in features[:10]]

    print(f"  Total segments : {len(scores)}")
    print(f"  Mean score     : {round(sum(scores)/len(scores), 1)}")
    print(f"  Max score      : {max(scores)}")
    print(f"  Min score      : {min(scores)}")
    print(f"  Elevation data : {'available' if _ELEVATION_AVAILABLE else 'unavailable (install srtm.py)'}")
    print(f"\n  Top 5 segments:")
    for i, p in enumerate(top10[:5], 1):
        print(f"  {i}. {p['name']:<35} score={p['drive_score']:>5}  "
              f"elev={p['score_elevation']:>5}  "
              f"speed={p['score_speed_limit']:>3}  "
              f"cam={p['score_camera_free']:>5}  "
              f"len={p['length_m']:>5}m  "
              f"sinuosity={p['sinuosity']}  "
              f"narrow={p['narrow']}")

    print("\n=== Done ===\n")
    return geojson


if __name__ == "__main__":
    run_pipeline(BBOX)
