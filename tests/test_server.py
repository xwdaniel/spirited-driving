"""
API tests for apexline_server.py

Uses FastAPI's TestClient (no live server needed — runs in-process).
osmnx/geopandas are stubbed so the /segments endpoint can be tested
without the full pipeline running; a separate live-pipeline test is
skipped when osmnx is unavailable.
"""

import sys
import types
import json
import pytest
from pathlib import Path

# ── Stub heavy deps before any pipeline import happens ────────────────────
for mod in ("osmnx", "geopandas", "requests"):
    sys.modules.setdefault(mod, types.ModuleType(mod))

from fastapi.testclient import TestClient

# Import the server — pipeline is imported lazily inside route handlers
import importlib
server = importlib.import_module("apexline_server")
app    = server.app

client = TestClient(app, raise_server_exceptions=True)

GEOJSON_PATH = Path(__file__).parent.parent / "apexline_segments.geojson"

# ── Minimal valid GeoJSON fixture ─────────────────────────────────────────
MINIMAL_GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[-1.79, 53.38], [-1.80, 53.39]]},
            "properties": {
                "name": "Test Road", "highway": "primary", "maxspeed": "NSL",
                "length_m": 1500, "sinuosity": 0.9,
                "score_windiness": 60.0, "score_speed_limit": 100,
                "score_camera_free": 100.0, "score_road_width": 85,
                "drive_score": 83.5,
            },
        }
    ],
}


# ══════════════════════════════════════════════════════════════════════════════
# /health
# ══════════════════════════════════════════════════════════════════════════════

class TestHealth:
    def test_returns_200(self):
        r = client.get("/health")
        assert r.status_code == 200

    def test_status_ok(self):
        r = client.get("/health")
        assert r.json()["status"] == "ok"

    def test_cached_field_present(self):
        r = client.get("/health")
        assert "cached" in r.json()


# ══════════════════════════════════════════════════════════════════════════════
# /geocode
# ══════════════════════════════════════════════════════════════════════════════

class TestGeocode:
    def test_missing_q_param_is_422(self):
        r = client.get("/geocode")
        assert r.status_code == 422

    def test_nominatim_called(self, monkeypatch):
        # Monkeypatch the http.get inside apexline_server
        class FakeResp:
            def raise_for_status(self): pass
            def json(self):
                return [{
                    "display_name": "Peak District, Derbyshire, England",
                    "boundingbox": ["53.27", "53.62", "-1.95", "-1.54"],
                }]

        monkeypatch.setattr(server.http, "get", lambda *a, **kw: FakeResp(), raising=False)
        r = client.get("/geocode?q=Peak+District")
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "Peak District"
        assert data["bbox"]["south"] == pytest.approx(53.27)
        assert data["bbox"]["north"] == pytest.approx(53.62)
        assert data["bbox"]["west"]  == pytest.approx(-1.95)
        assert data["bbox"]["east"]  == pytest.approx(-1.54)

    def test_no_results_returns_404(self, monkeypatch):
        class FakeResp:
            def raise_for_status(self): pass
            def json(self): return []

        monkeypatch.setattr(server.http, "get", lambda *a, **kw: FakeResp(), raising=False)
        r = client.get("/geocode?q=xyzthisdoesnotexist")
        assert r.status_code == 404

    def test_nominatim_failure_returns_502(self, monkeypatch):
        import requests as req_mod

        def boom(*a, **kw):
            raise req_mod.exceptions.RequestException("timeout")

        # Ensure requests has an exceptions attr with RequestException
        if not hasattr(req_mod, "exceptions"):
            exc_mod = types.ModuleType("requests.exceptions")
            exc_mod.RequestException = Exception
            req_mod.exceptions = exc_mod

        monkeypatch.setattr(server.http, "get", boom, raising=False)
        monkeypatch.setattr(server.http, "exceptions",
                            type("E", (), {"RequestException": Exception})(),
                            raising=False)
        r = client.get("/geocode?q=anywhere")
        assert r.status_code == 502


# ══════════════════════════════════════════════════════════════════════════════
# /segments  (validation only — pipeline mocked)
# ══════════════════════════════════════════════════════════════════════════════

class TestSegmentsValidation:
    @pytest.fixture(autouse=True)
    def mock_pipeline(self, monkeypatch):
        """Replace run_pipeline with a stub that returns minimal GeoJSON."""
        import apexline_pipeline as pl
        monkeypatch.setattr(pl, "run_pipeline", lambda bbox: MINIMAL_GEOJSON)

    def test_default_params_returns_200(self):
        r = client.get("/segments?south=53.30&west=-1.95&north=53.50&east=-1.60")
        assert r.status_code == 200

    def test_response_is_feature_collection(self):
        r = client.get("/segments?south=53.30&west=-1.95&north=53.50&east=-1.60")
        assert r.json()["type"] == "FeatureCollection"

    def test_south_greater_than_north_is_400(self):
        r = client.get("/segments?south=53.50&west=-1.95&north=53.30&east=-1.60")
        assert r.status_code == 400

    def test_west_greater_than_east_is_400(self):
        r = client.get("/segments?south=53.30&west=-1.60&north=53.50&east=-1.95")
        assert r.status_code == 400

    def test_bbox_too_large_is_400(self):
        # 3°×3° exceeds the 2° limit
        r = client.get("/segments?south=51.0&west=-2.0&north=54.0&east=1.0")
        assert r.status_code == 400

    def test_missing_params_uses_defaults(self):
        r = client.get("/segments")
        assert r.status_code == 200

    def test_pipeline_error_returns_500(self, monkeypatch):
        import apexline_pipeline as pl
        monkeypatch.setattr(pl, "run_pipeline", lambda bbox: (_ for _ in ()).throw(RuntimeError("boom")))
        r = client.get("/segments?south=53.30&west=-1.95&north=53.50&east=-1.60")
        assert r.status_code == 500


# ══════════════════════════════════════════════════════════════════════════════
# /segments/cached
# ══════════════════════════════════════════════════════════════════════════════

class TestSegmentsCached:
    def test_returns_404_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(server, "CACHE_PATH", tmp_path / "missing.geojson")
        r = client.get("/segments/cached")
        assert r.status_code == 404

    def test_returns_200_with_valid_file(self, tmp_path, monkeypatch):
        p = tmp_path / "apexline_segments.geojson"
        p.write_text(json.dumps(MINIMAL_GEOJSON))
        monkeypatch.setattr(server, "CACHE_PATH", p)
        r = client.get("/segments/cached")
        assert r.status_code == 200
        assert r.json()["type"] == "FeatureCollection"

    def test_cached_content_matches_file(self, tmp_path, monkeypatch):
        p = tmp_path / "apexline_segments.geojson"
        p.write_text(json.dumps(MINIMAL_GEOJSON))
        monkeypatch.setattr(server, "CACHE_PATH", p)
        r = client.get("/segments/cached")
        assert r.json()["features"][0]["properties"]["name"] == "Test Road"


# ══════════════════════════════════════════════════════════════════════════════
# CORS headers
# ══════════════════════════════════════════════════════════════════════════════

class TestConfig:
    def test_returns_token_from_env(self, monkeypatch):
        monkeypatch.setenv("MAPBOX_TOKEN", "pk.test.token")
        r = client.get("/config")
        assert r.status_code == 200
        assert r.json()["mapbox_token"] == "pk.test.token"

    def test_missing_env_returns_500(self, monkeypatch):
        monkeypatch.delenv("MAPBOX_TOKEN", raising=False)
        r = client.get("/config")
        assert r.status_code == 500


class TestCORS:
    def test_cors_header_on_health(self):
        r = client.get("/health", headers={"Origin": "null"})
        assert r.headers.get("access-control-allow-origin") == "*"

    def test_cors_header_on_geocode(self, monkeypatch):
        class FakeResp:
            def raise_for_status(self): pass
            def json(self):
                return [{"display_name": "X", "boundingbox": ["51", "52", "-1", "0"]}]

        monkeypatch.setattr(server.http, "get", lambda *a, **kw: FakeResp(), raising=False)
        r = client.get("/geocode?q=test", headers={"Origin": "file://"})
        assert r.headers.get("access-control-allow-origin") == "*"


# ══════════════════════════════════════════════════════════════════════════════
# /route
# ══════════════════════════════════════════════════════════════════════════════

ROUTE_GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [
                [-1.79, 53.38], [-1.795, 53.383], [-1.80, 53.386],
                [-1.805, 53.389], [-1.81, 53.39],
            ]},
            "properties": {
                "name": "A537 Cat and Fiddle", "highway": "primary",
                "maxspeed": "NSL", "length_m": 4200, "sinuosity": 0.81,
                "narrow": False, "drive_score": 77,
            },
        },
        {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [
                [-1.82, 53.40], [-1.825, 53.403], [-1.83, 53.406],
                [-1.835, 53.409], [-1.84, 53.41],
            ]},
            "properties": {
                "name": "A57 Snake Pass", "highway": "trunk",
                "maxspeed": "NSL", "length_m": 5100, "sinuosity": 0.78,
                "narrow": False, "drive_score": 82,
            },
        },
    ],
}

MAPBOX_DIRECTIONS_RESP = {
    "routes": [{
        "geometry": {"type": "LineString", "coordinates": [[-1.79, 53.38], [-1.84, 53.41]]},
        "distance": 12000,   # metres
        "duration": 900,     # seconds
    }]
}


class TestRoute:
    @pytest.fixture(autouse=True)
    def mock_pipeline_and_mapbox(self, monkeypatch):
        import apexline_pipeline as pl
        monkeypatch.setattr(pl, "run_pipeline", lambda bbox: ROUTE_GEOJSON)

        class FakeResp:
            ok = True
            def raise_for_status(self): pass
            def json(self): return MAPBOX_DIRECTIONS_RESP

        monkeypatch.setattr(server.http, "get", lambda *a, **kw: FakeResp(), raising=False)

    def test_loop_returns_200(self):
        r = client.post("/route", json={
            "start_lon": -1.79, "start_lat": 53.38,
            "hours": 2.0, "mapbox_token": "pk.test",
        })
        assert r.status_code == 200

    def test_response_has_required_keys(self):
        r = client.post("/route", json={
            "start_lon": -1.79, "start_lat": 53.38,
            "hours": 2.0, "mapbox_token": "pk.test",
        })
        data = r.json()
        assert "route" in data
        assert "included_segments" in data
        assert "google_maps_url" in data

    def test_route_is_feature(self):
        r = client.post("/route", json={
            "start_lon": -1.79, "start_lat": 53.38,
            "hours": 2.0, "mapbox_token": "pk.test",
        })
        assert r.json()["route"]["type"] == "Feature"

    def test_route_properties_present(self):
        r = client.post("/route", json={
            "start_lon": -1.79, "start_lat": 53.38,
            "hours": 2.0, "mapbox_token": "pk.test",
        })
        props = r.json()["route"]["properties"]
        for key in ("distance_km", "duration_hours", "segments_included", "avg_drive_score", "is_loop"):
            assert key in props, f"Missing property: {key}"

    def test_loop_flag_true_when_no_end(self):
        r = client.post("/route", json={
            "start_lon": -1.79, "start_lat": 53.38,
            "hours": 2.0, "mapbox_token": "pk.test",
        })
        assert r.json()["route"]["properties"]["is_loop"] is True

    def test_a_to_b_loop_flag_false(self):
        r = client.post("/route", json={
            "start_lon": -1.79, "start_lat": 53.38,
            "end_lon": -1.84, "end_lat": 53.41,
            "hours": 2.0, "mapbox_token": "pk.test",
        })
        assert r.json()["route"]["properties"]["is_loop"] is False

    def test_google_maps_url_format(self):
        r = client.post("/route", json={
            "start_lon": -1.79, "start_lat": 53.38,
            "hours": 2.0, "mapbox_token": "pk.test",
        })
        url = r.json()["google_maps_url"]
        assert url.startswith("https://www.google.com/maps/dir/")
        assert "53.38" in url
        assert "-1.79" in url

    def test_invalid_hours_returns_400(self):
        r = client.post("/route", json={
            "start_lon": -1.79, "start_lat": 53.38,
            "hours": -1.0, "mapbox_token": "pk.test",
        })
        assert r.status_code == 400

    def test_hours_over_24_returns_400(self):
        r = client.post("/route", json={
            "start_lon": -1.79, "start_lat": 53.38,
            "hours": 25.0, "mapbox_token": "pk.test",
        })
        assert r.status_code == 400

    def test_included_segments_is_feature_collection(self):
        r = client.post("/route", json={
            "start_lon": -1.79, "start_lat": 53.38,
            "hours": 2.0, "mapbox_token": "pk.test",
        })
        segs = r.json()["included_segments"]
        assert segs["type"] == "FeatureCollection"
        assert isinstance(segs["features"], list)

    def test_no_segments_returns_404(self, monkeypatch):
        import apexline_pipeline as pl
        monkeypatch.setattr(pl, "run_pipeline",
                            lambda bbox: {"type": "FeatureCollection", "features": []})
        r = client.post("/route", json={
            "start_lon": -1.79, "start_lat": 53.38,
            "hours": 2.0, "mapbox_token": "pk.test",
        })
        assert r.status_code == 404
