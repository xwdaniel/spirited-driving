# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

Apexline finds and scores roads suitable for spirited driving. Given a bounding box, it:
1. Fetches road network from OpenStreetMap (via Overpass API / osmnx)
2. Fetches speed camera locations from OSM
3. Scores every road segment on 4 criteria: windiness, speed limit, camera proximity, road width
4. Renders scored segments on an interactive Mapbox GL JS map with a filterable sidebar

## Commands

### Python tests
```bash
python3 -m pytest tests/                                                          # all 89 tests
python3 -m pytest tests/test_pipeline.py                                          # pipeline unit tests only
python3 -m pytest tests/test_server.py                                            # API tests only
python3 -m pytest tests/test_pipeline.py::TestHaversine::test_same_point_is_zero  # single test
```

### E2E tests (Playwright)
```bash
npm run test:e2e       # headless
npm run test:e2e:ui    # interactive UI mode
```

### Run the server
```bash
uvicorn apexline_server:app --reload --port 8000
```

### Generate synthetic test data (no internet required)
```bash
python3 generate_test_data.py
```

## Architecture

### Backend — `apexline_pipeline.py`
The core ETL pipeline. Fetches road graph via osmnx, fetches cameras via Overpass API, splits edges into segments, scores each segment, and writes `apexline_segments.geojson`. Key internals:
- `haversine()` — distance between lat/lon points
- `score_segment()` — combines 4 sub-scores into a final 0–100 score
- `fetch_speed_cameras()` — Overpass API query, returns list of (lat, lon) tuples
- `run_pipeline()` — orchestrates everything; accepts a bounding box dict

### API Server — `apexline_server.py`
FastAPI app with 4 endpoints:
- `GET /health` — liveness check
- `GET /geocode?q=...` — forward geocode via Nominatim
- `POST /segments` — run pipeline for a given bbox, returns GeoJSON
- `GET /segments/cached` — return the last pipeline result

### Frontend — `apexline.html`
Single self-contained file (698 lines). No build step. Uses Mapbox GL JS v3.3.0. Renders segments as a choropleth layer, sidebar with score-based filtering, and a location search box that calls `/geocode` then `/segments`.

### Tests
- `tests/test_pipeline.py` — pure-function unit tests; stubs osmnx, geopandas, and requests so they run without those libs installed
- `tests/test_server.py` — FastAPI TestClient tests; stubs the pipeline
- `tests/e2e/` — Playwright specs (map, sidebar, location); uses a Mapbox stub in `helpers.js` to avoid real tokens; base URL is `http://localhost:5173` (auto-served by `npx serve`)

## Key Tech

| Layer | Technology |
|---|---|
| Road data | osmnx, Overpass API |
| Geometry | shapely, geopandas |
| Server | FastAPI + uvicorn |
| Frontend | Vanilla JS, Mapbox GL JS v3.3.0 |
| Python tests | pytest (deps stubbed) |
| E2E tests | Playwright (`@playwright/test` v1.59.1) |

## Configuration Notes

- The Playwright config (`playwright.config.js`) sets `--use-gl=swiftshader` so tests run without a GPU.
- `apexline_segments.geojson` is the pipeline output file; regenerate with `generate_test_data.py` for offline development.
- A full architecture and design rationale document lives in `APEXLINE_HANDOFF.md`.
