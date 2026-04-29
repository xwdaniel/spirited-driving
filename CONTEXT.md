# Apexline — Domain Context

## Core Concept

**Spirited driving road** — a road segment suitable for enthusiastic, legal driving. Characterised by sustained curves, open speed limits, elevation change, and absence of urban interruptions. Not a track day venue; a real public road you'd seek out on a weekend.

## Key Terms

**Segment** — a scored sub-section of an OSM road edge, minimum 2,000 m. The atomic unit of Apexline output. Segments shorter than 2 km are not worth navigating to as a driving destination.

**Drive Score** — a 0–100 composite score representing how suitable a segment is for spirited driving. Combines windiness, elevation, speed limit, and camera factors. Subject to hard filters that can exclude a segment entirely regardless of score.

**Hard Filter** — a binary exclusion applied before scoring. A segment failing a hard filter never appears in output, regardless of its geometric or scoring properties.

**Score Cap** — an upper bound applied to the final drive score for segments with a specific characteristic (e.g. narrow lanes). The segment appears in output but is bounded.

**Windiness** — the degree to which a road curves, measured via four sub-scores: sinuosity, angular density, corner variety, and straight-to-bend ratio.

**Sinuosity Ratio** — straight-line distance divided by road length between endpoints (stored as `straight/road`, ≤ 1.0). 1.0 = dead straight; lower values = more winding. Segments with ratio > 0.952 (i.e. road deviates less than 5% from straight line) are excluded.

**Narrow Road** — a road tagged `lanes=1` or `width < 4.5m` in OSM. Suitable for passage but not a driving destination. Score capped at 50.

**Urban Road** — a road with a resolved speed limit ≤ 40 mph. Always excluded. Includes 20, 30, and 40 mph zones.

**Roundabout** — an OSM edge tagged `junction=roundabout`. Always excluded. Not a driving destination regardless of geometric properties.

## Hard Filters (applied in order, before scoring)

1. `junction=roundabout` → excluded
2. Resolved speed limit ≤ 40 mph → excluded
3. Sinuosity ratio (straight/road) > 0.952 → excluded (road deviates < 5% from straight line)
4. Junction density > 0.5 per km (traffic signals + stop signs) → excluded
5. Segment length < 1,000 m → excluded

## Score Caps

- `lanes=1` or `width < 4.5m` → drive score capped at 50

## Scoring Weights

| Factor | Weight | Notes |
|---|---|---|
| sinuosity | 0.10 | Higher = more winding |
| angular_density | 0.10 | Turns per metre |
| corner_variety | 0.10 | Std dev of angular changes |
| straight_bend | 0.10 | Optimal ~14:3 ratio (Tilke) |
| elevation | 0.30 | Gain+loss per km via SRTM |
| speed_limit | 0.20 | NSL = 100, 60mph = 80, etc. |
| camera_free | 0.10 | Cameras within 200m penalised |

## Route Planning

**Spirited Route** — a navigable route between a start and end point (which may be the same, forming a loop) that threads through the highest-scoring road segments within a time budget. Optimised for drive score, not travel time or distance.

**Time Budget** — the maximum driving time a user is willing to spend, expressed in hours. Converted to a maximum route distance at 60 km/h average speed (conservative; accounts for corners, junctions, brief stops).

**Waypoint** — the midpoint of a high-scoring segment selected by the greedy algorithm to be included in the spirited route.

**Pinned Segment** — a scored segment explicitly selected by the user to be guaranteed included in the next spirited route, regardless of drive score or budget. Pinned segments are inserted into the route before the greedy algorithm runs. Persists until the user explicitly unpins. Distinct visual state on the map (solid white, 3px outline). Up to 25 waypoints are passed to the Mapbox Directions API to construct a navigable route. Up to 9 are included in the "Open in Google Maps" URL.

**Loop** — a spirited route where start and end point are the same location. A special case of A-to-B routing.

## What Is Not a Spirited Driving Road

- Roundabouts
- Roads with speed limits ≤ 40 mph
- Segments shorter than 2 km
- Segments with > 0.5 traffic signals or stop signs per km
- Dead-straight roads (sinuosity ratio < 1.05)
