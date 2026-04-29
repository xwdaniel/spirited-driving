# ADR-0001: Hard Filters for Categorical Exclusions

## Status
Accepted

## Context
The original algorithm scored all road segments on a weighted composite. This caused roundabouts, short town roads, and dead-straight segments to appear in output with high scores — because their geometric properties (e.g. a roundabout's circular geometry produces high sinuosity and angular density scores) overwhelmed contextual signals.

## Decision
Categorical non-driving-roads are excluded via hard filters applied before scoring, not via score weighting. Filters are:

1. `junction=roundabout` — circular infrastructure, not a destination
2. Resolved speed limit ≤ 40 mph — urban roads excluded unconditionally
3. Sinuosity ratio < 1.05 — dead-straight roads excluded unconditionally
4. Junction density > 0.5/km — traffic-interrupted roads excluded unconditionally
5. Segment length < 2,000 m — too short to navigate to as a destination

## Alternatives Considered
- **Heavy penalisation via weights**: rejected — score weighting cannot reliably overcome strong geometric signals (e.g. roundabout sinuosity). Hard filters are cleaner and more predictable.
- **Raising speed limit weight**: rejected — a 30 mph twisty village road should never appear, regardless of windiness. Binary exclusion is the right model.

## Consequences
- Output set shrinks significantly; only genuinely rural, open roads appear.
- Junction density score sub-factor removed; elevation weight raised to 0.30 with freed weight.
- Road surface sub-factor removed (sparsely tagged in OSM; not meaningful signal).
- Narrow roads (`lanes=1` or `width < 4.5m`) are not excluded but score-capped at 50.
