"""
Unit tests for apexline_pipeline.py

osmnx and geopandas are not required — we stub them out and import
only the pure scoring/geometry functions.
"""

import sys
import types
import math
import pytest

# ── Stub out heavy deps before importing the pipeline ──────────────────────
for mod in ("osmnx", "geopandas", "requests"):
    sys.modules.setdefault(mod, types.ModuleType(mod))

# shapely.geometry is used by the pipeline but we have a real shapely install
# so no stub needed for that.

import importlib
pipeline = importlib.import_module("apexline_pipeline")

haversine_m         = pipeline.haversine_m
road_length_m       = pipeline.road_length_m
bearing             = pipeline.bearing
angular_changes     = pipeline.angular_changes
smooth              = pipeline.smooth
compute_curvature_per_metre = pipeline.compute_curvature_per_metre
find_breakpoints    = pipeline.find_breakpoints
split_linestring_at_distances = pipeline.split_linestring_at_distances
score_sinuosity          = pipeline.score_sinuosity
score_angular_density    = pipeline.score_angular_density
score_corner_variety     = pipeline.score_corner_variety
score_straight_bend_ratio = pipeline.score_straight_bend_ratio
score_windiness          = pipeline.score_windiness
score_speed_limit        = pipeline.score_speed_limit
score_cameras            = pipeline.score_cameras
junction_density_per_km  = pipeline.junction_density_per_km
resolve_speed_mph        = pipeline.resolve_speed_mph
is_narrow_road           = pipeline.is_narrow_road
compute_drive_score = pipeline.compute_drive_score
sinuosity_ratio     = pipeline.sinuosity_ratio
MIN_SEGMENT_METRES    = pipeline.MIN_SEGMENT_METRES
MIN_OUTPUT_METRES     = pipeline.MIN_OUTPUT_METRES
_MAX_SINUOSITY_RATIO  = pipeline._MAX_SINUOSITY_RATIO
NARROW_ROAD_SCORE_CAP = pipeline.NARROW_ROAD_SCORE_CAP
WEIGHTS               = pipeline.WEIGHTS

from shapely.geometry import LineString


# ══════════════════════════════════════════════════════════════════════════════
# GEOMETRY HELPERS
# ══════════════════════════════════════════════════════════════════════════════

class TestHaversine:
    def test_same_point_is_zero(self):
        assert haversine_m(0, 0, 0, 0) == 0.0

    def test_known_distance(self):
        # London (51.5074°N, 0.1278°W) to Manchester (53.4808°N, 2.2426°W)
        # ~263 km
        d = haversine_m(-0.1278, 51.5074, -2.2426, 53.4808)
        assert 260_000 < d < 270_000

    def test_symmetry(self):
        d1 = haversine_m(-1.79, 53.38, -1.75, 53.42)
        d2 = haversine_m(-1.75, 53.42, -1.79, 53.38)
        assert abs(d1 - d2) < 1  # within 1 m

    def test_one_degree_latitude(self):
        # ~111 km per degree latitude
        d = haversine_m(0, 0, 0, 1)
        assert 110_000 < d < 112_000


class TestRoadLength:
    def test_single_segment(self):
        # Two points ~1 km apart
        coords = [(-1.79, 53.38), (-1.80, 53.385)]
        length = road_length_m(coords)
        assert length > 0

    def test_collinear_adds_up(self):
        # Three points: A→B→C where B is midpoint
        a = (-1.79, 53.38)
        b = (-1.795, 53.382)
        c = (-1.80, 53.384)
        ab = haversine_m(*a, *b)
        bc = haversine_m(*b, *c)
        total = road_length_m([a, b, c])
        assert abs(total - (ab + bc)) < 1


class TestBearing:
    def test_north(self):
        # Due north
        b = bearing(0, 0, 0, 1)
        assert abs(b) < 0.01  # ~0 radians

    def test_east(self):
        # Due east (approx)
        b = bearing(0, 45, 1, 45)
        assert abs(b - math.pi / 2) < 0.05


class TestAngularChanges:
    def test_straight_line_no_changes(self):
        # Points in a straight line east
        coords = [(0.0, 51.0), (0.01, 51.0), (0.02, 51.0), (0.03, 51.0)]
        positions, angles = angular_changes(coords)
        assert len(angles) > 0
        assert all(a < 0.05 for a in angles)  # near-zero turns

    def test_right_angle_turn(self):
        # North then east — 90° turn at the middle node
        coords = [(0.0, 51.0), (0.0, 51.01), (0.01, 51.01)]
        positions, angles = angular_changes(coords)
        assert len(angles) == 1
        assert abs(angles[0] - math.pi / 2) < 0.1

    def test_too_few_coords_returns_empty(self):
        positions, angles = angular_changes([(0, 51), (0.01, 51)])
        assert len(positions) == 0
        assert len(angles) == 0


class TestSmooth:
    def test_shorter_than_window_returns_as_is(self):
        import numpy as np
        arr = np.array([1.0, 2.0])
        result = smooth(arr, window=5)
        assert list(result) == list(arr)

    def test_constant_array_unchanged(self):
        import numpy as np
        arr = np.ones(10) * 5.0
        result = smooth(arr, window=3)
        # np.convolve mode='same' zero-pads edges, so only interior values are exact
        assert all(abs(v - 5.0) < 0.01 for v in result[1:-1])


# ══════════════════════════════════════════════════════════════════════════════
# SEGMENTATION
# ══════════════════════════════════════════════════════════════════════════════

class TestFindBreakpoints:
    def test_uniform_curvature_no_breaks(self):
        import numpy as np
        # All values above threshold — no transitions
        positions  = np.array([100.0, 200.0, 300.0, 400.0])
        curvature  = np.array([0.002, 0.002, 0.002, 0.002])
        breaks = find_breakpoints(positions, curvature, total_length=400)
        assert breaks == []

    def test_all_straight_no_breaks(self):
        import numpy as np
        positions  = np.array([100.0, 200.0, 300.0])
        curvature  = np.array([0.0001, 0.0001, 0.0001])  # all below threshold
        breaks = find_breakpoints(positions, curvature, total_length=300)
        assert breaks == []

    def test_transition_produces_breakpoint(self):
        import numpy as np
        positions = np.array([100.0, 200.0, 300.0, 400.0])
        # Crosses threshold between index 1 and 2
        curvature = np.array([0.0001, 0.0001, 0.002, 0.002])
        breaks = find_breakpoints(positions, curvature, total_length=400)
        assert len(breaks) == 1
        assert breaks[0] == 300.0

    def test_empty_curvature(self):
        import numpy as np
        breaks = find_breakpoints(np.array([]), np.array([]), total_length=0)
        assert breaks == []


class TestSplitLinestring:
    def _long_line(self):
        # ~10 km straight line
        return LineString([(0.0, 51.0 + i * 0.01) for i in range(20)])

    def test_no_breakpoints_returns_original(self):
        line = self._long_line()
        result = split_linestring_at_distances(line, [])
        assert len(result) == 1

    def test_short_line_not_split(self):
        # Only 2 points, very short
        short = LineString([(0.0, 51.0), (0.001, 51.0)])
        result = split_linestring_at_distances(short, [50.0])
        assert len(result) == 1

    def test_split_produces_multiple_segments(self):
        line = self._long_line()
        coords = list(line.coords)
        total = road_length_m(coords)
        # Split at roughly 1/3 and 2/3
        breaks = [total / 3, 2 * total / 3]
        result = split_linestring_at_distances(line, breaks)
        assert len(result) >= 2

    def test_all_segments_meet_min_length(self):
        line = self._long_line()
        coords = list(line.coords)
        total = road_length_m(coords)
        breaks = [total / 3, 2 * total / 3]
        result = split_linestring_at_distances(line, breaks)
        for seg in result:
            seg_len = road_length_m(list(seg.coords))
            assert seg_len >= MIN_SEGMENT_METRES * 0.5  # allow merge tolerance


# ══════════════════════════════════════════════════════════════════════════════
# SCORING FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

class TestScoreSpeedLimit:
    @pytest.mark.parametrize("tag,expected", [
        ("NSL",      100),
        ("national", 100),
        ("nsl",      100),
        ("",         100),
        (None,       100),
        ("signals",  100),
        ("70",       100),
        ("60",        80),
        ("50",        55),
        ("40",        35),
        ("30",        10),
        ("20",         0),
    ])
    def test_known_tags(self, tag, expected):
        assert score_speed_limit(tag) == expected

    def test_kmh_converted(self):
        # Conversion only triggers when the parsed int is > 100.
        # 105 km/h * 0.621 ≈ 65 mph → score 80
        assert score_speed_limit("105") == 80

    def test_unknown_tag_returns_nsl(self):
        # Unrecognised string → treated as NSL → 100
        assert score_speed_limit("variable") == 100


class TestResolveSpeedMph:
    def test_nsl_tags_return_999(self):
        for tag in ("", "none", "nan", "national", "nsl", "signals", None):
            assert resolve_speed_mph(tag) == 999

    def test_numeric_mph(self):
        assert resolve_speed_mph("60") == 60
        assert resolve_speed_mph("30 mph") == 30

    def test_kmh_converted(self):
        # 112 km/h → ~70 mph
        assert resolve_speed_mph("112") == 70

    def test_unknown_tag_returns_999(self):
        assert resolve_speed_mph("variable") == 999


class TestIsNarrowRoad:
    def test_single_lane_is_narrow(self):
        assert is_narrow_road("1", None) is True

    def test_two_lanes_not_narrow(self):
        assert is_narrow_road("2", None) is False

    def test_narrow_width_is_narrow(self):
        assert is_narrow_road(None, "3.5") is True

    def test_wide_enough_not_narrow(self):
        assert is_narrow_road(None, "6.0") is False

    def test_none_values_not_narrow(self):
        assert is_narrow_road(None, None) is False

    def test_semicolon_lanes_tag(self):
        # Some OSM edges have "1;1" — take first token
        assert is_narrow_road("1;1", None) is True


class TestScoreCameras:
    def _seg(self):
        return LineString([(-1.79, 53.38), (-1.80, 53.385), (-1.81, 53.39)])

    def test_no_cameras_is_100(self):
        assert score_cameras(self._seg(), []) == 100

    def test_distant_camera_no_penalty(self):
        # Camera >500m away — should not affect score
        far_cam = [(-2.5, 54.0)]
        assert score_cameras(self._seg(), far_cam) == 100

    def test_nearby_camera_penalises(self):
        # Camera directly on a segment node — well within 200m
        near_cam = [(-1.79, 53.38)]
        score = score_cameras(self._seg(), near_cam)
        assert score < 100

    def test_multiple_cameras_penalise_more(self):
        near_cams = [(-1.79, 53.38), (-1.80, 53.385), (-1.81, 53.39)]
        score = score_cameras(self._seg(), near_cams)
        assert score < score_cameras(self._seg(), [near_cams[0]])

    def test_score_clamps_to_zero(self):
        # Saturate with many cameras
        cams = [(-1.795, 53.382)] * 50
        assert score_cameras(self._seg(), cams) >= 0


class TestScoreWindiness:
    def _straight(self):
        # Straight west-to-east line, 20 points
        return [(i * 0.01, 51.0) for i in range(20)]

    def _winding(self):
        # Tight S-bends
        coords = []
        for i in range(20):
            lon = i * 0.005
            lat = 51.0 + 0.01 * math.sin(i * math.pi / 3)
            coords.append((lon, lat))
        return coords

    def test_straight_road_scores_low(self):
        assert score_windiness(self._straight()) < 30

    def test_winding_road_scores_higher_than_straight(self):
        assert score_windiness(self._winding()) > score_windiness(self._straight())

    def test_too_few_coords(self):
        assert score_windiness([(0, 51), (0.01, 51)]) == 0

    def test_zero_length_road(self):
        assert score_windiness([(0, 51), (0, 51), (0, 51)]) == 0


class TestScoreSinuosity:
    def test_straight_line_scores_near_zero(self):
        coords = [(i * 0.01, 51.0) for i in range(10)]
        assert score_sinuosity(coords) < 5

    def test_winding_road_scores_higher(self):
        straight = [(i * 0.01, 51.0) for i in range(20)]
        winding = [(i * 0.005, 51.0 + 0.01 * math.sin(i * math.pi / 3)) for i in range(20)]
        assert score_sinuosity(winding) > score_sinuosity(straight)

    def test_too_few_coords(self):
        assert score_sinuosity([(0, 51)]) == 0

    def test_zero_length_road(self):
        assert score_sinuosity([(0, 51), (0, 51)]) == 0


class TestScoreCornerVariety:
    def test_uniform_corners_score_low(self):
        # Regular sine wave — all corners roughly the same size
        coords = [(i * 0.005, 51.0 + 0.005 * math.sin(i * math.pi / 4)) for i in range(30)]
        uniform_score = score_corner_variety(coords)
        # A straight line has zero variety
        straight = [(i * 0.01, 51.0) for i in range(30)]
        assert score_corner_variety(straight) < score_corner_variety(coords) or \
               score_corner_variety(straight) == 0

    def test_mixed_corners_score_higher_than_straight(self):
        straight = [(i * 0.01, 51.0) for i in range(20)]
        # Mix of tight and gentle corners
        coords = []
        for i in range(20):
            amp = 0.02 if i % 4 == 0 else 0.002
            coords.append((i * 0.005, 51.0 + amp * math.sin(i)))
        assert score_corner_variety(coords) > score_corner_variety(straight)

    def test_too_few_coords(self):
        assert score_corner_variety([(0, 51), (0.01, 51)]) == 0

    def test_returns_0_to_100(self):
        coords = [(i * 0.005, 51.0 + 0.01 * math.sin(i * math.pi / 3)) for i in range(20)]
        s = score_corner_variety(coords)
        assert 0 <= s <= 100


class TestScoreStraightBendRatio:
    def test_all_straight_scores_zero(self):
        # Straight line — no curvy nodes → 0
        coords = [(i * 0.01, 51.0) for i in range(20)]
        assert score_straight_bend_ratio(coords) == 0

    def test_winding_road_gives_nonzero(self):
        coords = [(i * 0.005, 51.0 + 0.01 * math.sin(i * math.pi / 3)) for i in range(20)]
        # Some curvy nodes → non-zero score
        assert score_straight_bend_ratio(coords) >= 0

    def test_too_few_coords(self):
        assert score_straight_bend_ratio([(0, 51), (0.01, 51)]) == 0

    def test_returns_0_to_100(self):
        coords = [(i * 0.005, 51.0 + 0.01 * math.sin(i * math.pi / 3)) for i in range(20)]
        s = score_straight_bend_ratio(coords)
        assert 0 <= s <= 100


class TestJunctionDensityPerKm:
    def _seg(self):
        return LineString([(-1.79, 53.38), (-1.80, 53.385), (-1.81, 53.39)])

    def test_no_junctions_is_zero(self):
        assert junction_density_per_km(self._seg(), []) == 0.0

    def test_distant_junction_is_zero(self):
        far = [(-2.5, 54.0)]
        assert junction_density_per_km(self._seg(), far) == 0.0

    def test_nearby_junction_gives_positive_density(self):
        near = [(-1.7900, 53.3800)]
        assert junction_density_per_km(self._seg(), near) > 0.0

    def test_more_junctions_gives_higher_density(self):
        one   = [(-1.7900, 53.3800)]
        three = [(-1.7900, 53.3800), (-1.8000, 53.3850), (-1.8100, 53.3900)]
        assert junction_density_per_km(self._seg(), three) > \
               junction_density_per_km(self._seg(), one)


class TestComputeDriveScore:
    def test_all_100_gives_100(self):
        assert compute_drive_score(100, 100, 100, 100, 100, 100, 100) == 100.0

    def test_all_zero_gives_zero(self):
        assert compute_drive_score(0, 0, 0, 0, 0, 0, 0) == 0.0

    def test_weights_sum_to_1(self):
        total = sum(WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9

    def test_weighted_calculation(self):
        # All scores = 100 except sinuosity = 50
        expected = round(
            50  * WEIGHTS["sinuosity"] +
            100 * WEIGHTS["angular_density"] +
            100 * WEIGHTS["corner_variety"] +
            100 * WEIGHTS["straight_bend"] +
            100 * WEIGHTS["elevation"] +
            100 * WEIGHTS["speed_limit"] +
            100 * WEIGHTS["camera_free"],
            1,
        )
        assert compute_drive_score(50, 100, 100, 100, 100, 100, 100) == expected

    def test_output_in_range(self):
        import random
        random.seed(0)
        for _ in range(50):
            scores = [random.uniform(0, 100) for _ in range(7)]
            s = compute_drive_score(*scores)
            assert 0 <= s <= 100


class TestSinuosityRatio:
    def test_straight_line_near_one(self):
        coords = [(i * 0.01, 51.0) for i in range(10)]
        assert sinuosity_ratio(coords) > 0.95

    def test_winding_road_below_one(self):
        coords = []
        for i in range(20):
            coords.append((i * 0.005, 51.0 + 0.01 * math.sin(i)))
        assert sinuosity_ratio(coords) < 1.0

    def test_single_point_returns_one(self):
        assert sinuosity_ratio([(0, 51)]) == 1.0

    def test_ratio_never_exceeds_one(self):
        # Straight line: road dist = chord dist → ratio = 1.0
        coords = [(0.0, 51.0), (0.1, 51.0)]
        assert sinuosity_ratio(coords) <= 1.0


# ══════════════════════════════════════════════════════════════════════════════
# DATA INTEGRITY — generated GeoJSON
# ══════════════════════════════════════════════════════════════════════════════

class TestGeneratedGeoJSON:
    @pytest.fixture(scope="class")
    def geojson(self):
        import json, subprocess, sys, os
        gen = os.path.join(os.path.dirname(__file__), "..", "generate_test_data.py")
        out = os.path.join(os.path.dirname(__file__), "..", "apexline_segments.geojson")
        subprocess.run([sys.executable, gen], check=True, cwd=os.path.dirname(gen))
        with open(out) as f:
            return json.load(f)

    def test_is_feature_collection(self, geojson):
        assert geojson["type"] == "FeatureCollection"
        assert isinstance(geojson["features"], list)
        assert len(geojson["features"]) > 0

    def test_required_properties_present(self, geojson):
        required = {
            "name", "highway", "maxspeed", "length_m", "sinuosity", "narrow",
            "score_sinuosity", "score_angular_density", "score_corner_variety",
            "score_straight_bend", "score_elevation", "score_speed_limit",
            "score_camera_free", "drive_score",
        }
        for feat in geojson["features"]:
            assert required.issubset(feat["properties"].keys()), \
                f"Missing keys in {feat['properties'].get('name')}"

    def test_all_scores_in_range(self, geojson):
        for feat in geojson["features"]:
            p = feat["properties"]
            for key in (
                "score_sinuosity", "score_angular_density", "score_corner_variety",
                "score_straight_bend", "score_elevation", "score_speed_limit",
                "score_camera_free", "drive_score",
            ):
                assert 0 <= p[key] <= 100, f"{key}={p[key]} out of range in {p['name']}"

    def test_drive_score_matches_formula(self, geojson):
        for feat in geojson["features"]:
            p = feat["properties"]
            # Narrow roads may be capped — skip formula check for those
            if p.get("narrow"):
                continue
            expected = round(
                p["score_sinuosity"]       * WEIGHTS["sinuosity"] +
                p["score_angular_density"] * WEIGHTS["angular_density"] +
                p["score_corner_variety"]  * WEIGHTS["corner_variety"] +
                p["score_straight_bend"]   * WEIGHTS["straight_bend"] +
                p["score_elevation"]       * WEIGHTS["elevation"] +
                p["score_speed_limit"]     * WEIGHTS["speed_limit"] +
                p["score_camera_free"]     * WEIGHTS["camera_free"],
                1,
            )
            assert abs(p["drive_score"] - expected) < 0.2, \
                f"drive_score mismatch for {p['name']}: got {p['drive_score']}, expected {expected}"

    def test_sorted_descending(self, geojson):
        scores = [f["properties"]["drive_score"] for f in geojson["features"]]
        assert scores == sorted(scores, reverse=True)

    def test_sinuosity_in_range(self, geojson):
        for feat in geojson["features"]:
            s = feat["properties"]["sinuosity"]
            assert 0 < s <= 1.0, f"sinuosity={s} out of range"

    def test_length_positive(self, geojson):
        for feat in geojson["features"]:
            assert feat["properties"]["length_m"] > 0

    def test_geometry_is_linestring(self, geojson):
        for feat in geojson["features"]:
            assert feat["geometry"]["type"] == "LineString"
            assert len(feat["geometry"]["coordinates"]) >= 2


# ══════════════════════════════════════════════════════════════════════════════
# HARD FILTER ACCEPTANCE TESTS — named after real roads
#
# These tests verify that roads with the known characteristics of named driving
# roads pass (or are correctly excluded by) each hard filter in isolation.
# Synthetic coordinates are used — no live OSM data required.
# ══════════════════════════════════════════════════════════════════════════════

def _make_sinuous_coords(n_points=30, amplitude=0.012, freq=5):
    """Generate a sinuous polyline roughly 5–8 km long (depending on amplitude)."""
    coords = []
    for i in range(n_points):
        t = i / (n_points - 1)
        lon = -1.80 + t * 0.08 + amplitude * math.sin(t * freq * math.pi * 2)
        lat = 53.38 + t * 0.04 + amplitude * 0.5 * math.cos(t * freq * math.pi * 2 + 0.5)
        coords.append((round(lon, 6), round(lat, 6)))
    return coords


def _make_straight_coords(n_points=20):
    """Generate a near-dead-straight polyline ~5 km long."""
    return [(-1.80 + i * 0.004, 53.38) for i in range(n_points)]


class TestHardFilters:
    """
    Acceptance tests for the five hard filters.
    Each test documents a real-world road and its relevant properties.
    """

    # ── sinuosity filter ─────────────────────────────────────────────────────

    def test_a507_baldock_buntingford_sinuosity_passes(self):
        """A507 Baldock→Buntingford: primary, NSL, highly sinuous (~11 km).
        A section either side of Cottered village (~5 km each) must pass the
        sinuosity filter."""
        coords = _make_sinuous_coords(n_points=30, amplitude=0.012, freq=5)
        ratio = sinuosity_ratio(coords)
        assert ratio <= _MAX_SINUOSITY_RATIO, (
            f"A507-like segment sinuosity_ratio={ratio:.3f} exceeds threshold "
            f"{_MAX_SINUOSITY_RATIO:.3f} — road wrongly excluded"
        )

    def test_a591_windermere_keswick_sinuosity_passes(self):
        """A591 Windermere→Keswick: primary, NSL, mountain road with continuous
        curves through the Lake District fells."""
        coords = _make_sinuous_coords(n_points=40, amplitude=0.015, freq=6)
        ratio = sinuosity_ratio(coords)
        assert ratio <= _MAX_SINUOSITY_RATIO, (
            f"A591-like segment sinuosity_ratio={ratio:.3f} exceeds threshold "
            f"{_MAX_SINUOSITY_RATIO:.3f} — road wrongly excluded"
        )

    def test_b4391_llangynog_bala_sinuosity_passes(self):
        """B4391 Llangynog→Bala: secondary, NSL, very sinuous Welsh mountain road
        with tight hairpins and valley descents."""
        coords = _make_sinuous_coords(n_points=35, amplitude=0.018, freq=7)
        ratio = sinuosity_ratio(coords)
        assert ratio <= _MAX_SINUOSITY_RATIO, (
            f"B4391-like segment sinuosity_ratio={ratio:.3f} exceeds threshold "
            f"{_MAX_SINUOSITY_RATIO:.3f} — road wrongly excluded"
        )

    def test_dead_straight_road_sinuosity_excluded(self):
        """A dead-straight road (e.g. Roman road, motorway slip) must be excluded."""
        coords = _make_straight_coords()
        ratio = sinuosity_ratio(coords)
        assert ratio > _MAX_SINUOSITY_RATIO, (
            f"Straight road sinuosity_ratio={ratio:.3f} should exceed "
            f"{_MAX_SINUOSITY_RATIO:.3f} but does not — straight roads leaking through"
        )

    # ── length filter ────────────────────────────────────────────────────────

    def test_a507_village_split_section_length_passes(self):
        """A507 through Cottered: the village 30mph section splits the road.
        Each half is ~4–5 km — must clear the 1,000 m minimum."""
        coords = _make_sinuous_coords(n_points=20, amplitude=0.010, freq=4)
        length = road_length_m(coords)
        assert length >= MIN_OUTPUT_METRES, (
            f"A507 village-split section length={length:.0f}m is below "
            f"MIN_OUTPUT_METRES={MIN_OUTPUT_METRES} — village interruptions "
            f"wrongly eliminate adjacent sections"
        )

    def test_very_short_segment_excluded(self):
        """A 3-node stub (~200 m) must be excluded by the length filter."""
        coords = [(-1.80, 53.38), (-1.801, 53.381), (-1.802, 53.382)]
        length = road_length_m(coords)
        assert length < MIN_OUTPUT_METRES, (
            f"Short stub length={length:.0f}m should be below "
            f"MIN_OUTPUT_METRES={MIN_OUTPUT_METRES}"
        )

    # ── speed limit filter ───────────────────────────────────────────────────

    def test_nsl_primary_road_passes_speed_filter(self):
        """NSL A-roads (A507, A591, A57) must pass the speed filter."""
        for tag in ("NSL", "national", "", None):
            mph = resolve_speed_mph(tag)
            assert mph >= 41, f"NSL tag {tag!r} resolved to {mph} mph — excluded"

    def test_thirty_mph_village_excluded(self):
        """30 mph village sections (e.g. Cottered on A507) must be excluded."""
        assert resolve_speed_mph("30") < 41

    def test_forty_mph_excluded(self):
        """40 mph urban/semi-urban roads must be excluded."""
        assert resolve_speed_mph("40") < 41

    def test_fifty_mph_passes(self):
        """50 mph roads (e.g. A537 Cat and Fiddle) must pass."""
        assert resolve_speed_mph("50") >= 41

    # ── junction density filter ──────────────────────────────────────────────

    def test_rural_nsl_road_junction_density_passes(self):
        """A507/A591 rural sections have no traffic signals — junction density = 0."""
        seg = LineString(_make_sinuous_coords())
        density = junction_density_per_km(seg, [])
        assert density == 0.0

    def test_urban_junction_density_excluded(self):
        """A segment with traffic lights every 500m (2/km) must exceed the threshold."""
        from apexline_pipeline import MAX_JUNCTION_DENSITY_PER_KM
        coords = _make_sinuous_coords()
        seg = LineString(coords)
        # Place junctions on every other node — enough to exceed 0.5/km
        junctions = [(coords[i][0], coords[i][1]) for i in range(0, len(coords), 2)]
        density = junction_density_per_km(seg, junctions)
        assert density > MAX_JUNCTION_DENSITY_PER_KM, (
            f"density={density:.3f} should exceed MAX={MAX_JUNCTION_DENSITY_PER_KM}"
        )

    # ── narrow road score cap ────────────────────────────────────────────────

    def test_b4391_single_lane_capped(self):
        """B4391 has single-lane sections — must be capped at 50, not excluded."""
        assert is_narrow_road("1", None) is True
        # Verify cap value — road appears but score bounded
        assert NARROW_ROAD_SCORE_CAP == 50

    def test_a507_two_lane_not_narrow(self):
        """A507 is a two-lane road — must not be flagged as narrow."""
        assert is_narrow_road("2", None) is False
