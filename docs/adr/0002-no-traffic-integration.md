# ADR-0002: Traffic Data Not Integrated

## Status
Accepted

## Context
Considered adding average traffic conditions as either a scoring factor or a "best times" display in the UI.

## Decision
No traffic integration. Traffic is not factored into drive score or displayed in the UI.

## Alternatives Considered
- **Traffic as a scoring factor**: rejected — drive score measures a road's intrinsic physical quality, which doesn't change with traffic conditions. A score computed at one time would be misleading at another.
- **"Best times" display (time-of-week heuristics)**: rejected — rural driving roads follow well-known patterns (quiet Sunday mornings, busy Saturday afternoons) that add no value over common sense. Static information not worth the UI complexity.
- **External traffic API (TomTom, HERE)**: rejected — adds API key dependency and operational complexity for marginal accuracy gain over heuristics.
- **OSM `aadt` tags**: rejected — almost never populated for rural roads.

## Consequences
None — feature not built.
