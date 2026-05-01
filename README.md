# Apexline

Finds and scores roads suitable for spirited driving. Given a bounding box, Apexline fetches the road network from OpenStreetMap, locates speed cameras, and scores every road segment across 7 factors — then renders them on an interactive Mapbox GL JS map with score-based filtering.

## How it works

1. **Fetch** road network via osmnx (Overpass API)
2. **Fetch** speed cameras and junction/interruption nodes from OSM
3. **Compute** per-edge sinuosity and angular density
4. **Segment** roads by curvature character using breakpoint detection
5. **Score** each segment (0–100) across 7 weighted factors
6. **Render** scored segments as a choropleth on a filterable map

### Scoring factors

| Factor | Weight | What it measures |
|---|---|---|
| Sinuosity | 10% | Inverted sinuosity ratio |
| Angular density | 10% | Turns per metre |
| Corner variety | 10% | Std dev of angular changes |
| Straight-to-bend ratio | 10% | Balance vs ~14:3 Tilke optimum |
| Elevation | 30% | Elevation gain + loss per km (SRTM) |
| Speed limit | 20% | OSM `maxspeed` tag |
| Camera-free | 10% | Absence of speed cameras within 200 m |

Road types included: `primary`, `secondary`, `tertiary`, `trunk`, and their link variants. Motorways and unclassified lanes are excluded.

## Stack

| Layer | Technology |
|---|---|
| Road data | osmnx, Overpass API |
| Geometry | shapely, geopandas |
| Elevation | srtm |
| Server | FastAPI + uvicorn |
| Frontend | Vanilla JS, Mapbox GL JS v3.3.0 |
| Python tests | pytest |
| E2E tests | Playwright v1.59.1 |

## Setup

Install Python and Node dependencies:

```bash
pip install -r requirements.txt
npm install
npx playwright install
```

### Mapbox token

The frontend requires a Mapbox GL JS token to render the map. Get a free token at [mapbox.com](https://account.mapbox.com/access-tokens/) (sign up, then copy the default public token from your account dashboard).

Set it as an environment variable before starting the server:

```bash
# macOS / Linux
export MAPBOX_TOKEN=your_token_here
```

```powershell
# Windows (PowerShell)
$env:MAPBOX_TOKEN = "your_token_here"
```

The server exposes the token via `GET /config`, which the frontend fetches on load. Without it the map will not load.

## Running

```bash
# Start the API server
uvicorn apexline_server:app --reload --port 8000

# Open apexline.html in a browser (or serve it)
npx serve .
```

The frontend is a single self-contained file (`apexline.html`) with no build step. Enter a place name to geocode it, then the pipeline runs for that bounding box and renders the scored segments.

## API endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness check |
| `GET` | `/geocode?q=...` | Forward geocode via Nominatim |
| `POST` | `/segments` | Run pipeline for a given bbox, returns GeoJSON |
| `GET` | `/segments/cached` | Return the last pipeline result |

## Testing

```bash
# Python unit tests (no internet required)
python3 -m pytest tests/

# Pipeline tests only
python3 -m pytest tests/test_pipeline.py

# API tests only
python3 -m pytest tests/test_server.py

# E2E tests (headless)
npm run test:e2e

# E2E tests (interactive UI)
npm run test:e2e:ui
```

Python tests stub osmnx, geopandas, and requests so they run without those libraries installed. E2E tests use a Mapbox stub to avoid requiring a real token.

## Offline development

Generate synthetic segment data without an internet connection:

```bash
python3 generate_test_data.py
```

This writes `apexline_segments.geojson`, which the frontend and cached endpoint will serve.

## Configuration

Key constants at the top of `apexline_pipeline.py`:

- `BBOX` — default bounding box (Peak District)
- `ROAD_TYPES` — OSM highway tags to include
- `WEIGHTS` — scoring factor weights (must sum to 1.0)
- `MIN_SEGMENT_METRES` — minimum segment length before merging (1500 m)
- `CAMERA_RADIUS_M` — camera influence radius constant (500 m, defined but currently overridden by `score_cameras` default of 200 m)

The Playwright config sets `--use-gl=swiftshader` so E2E tests run without a GPU.
