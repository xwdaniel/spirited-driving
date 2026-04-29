import { haversineKm, segmentMidpoint, insertCheapest, greedyWaypoints, MAX_MAPBOX_WP } from '../../apexline_route.js';

// ── haversineKm ────────────────────────────────────────────────────────────

test('haversineKm: same point is zero', () => {
  expect(haversineKm(0, 0, 0, 0)).toBe(0);
});

test('haversineKm: London to Manchester is ~263km', () => {
  // London: -0.1278, 51.5074 / Manchester: -2.2426, 53.4808
  const km = haversineKm(-0.1278, 51.5074, -2.2426, 53.4808);
  expect(km).toBeCloseTo(263, -1); // within ~10km
});

// ── segmentMidpoint ────────────────────────────────────────────────────────

test('segmentMidpoint: 2-point line returns midpoint', () => {
  const coords = [[0, 0], [2, 0]];
  const mid = segmentMidpoint(coords);
  expect(mid[0]).toBeCloseTo(1, 3);
  expect(mid[1]).toBeCloseTo(0, 3);
});

test('segmentMidpoint: 3-point equal-length segments returns middle point', () => {
  // Three points each equidistant: [0,0], [1,0], [2,0]
  // Midpoint of arc-length should land near [1,0]
  const coords = [[0, 0], [1, 0], [2, 0]];
  const mid = segmentMidpoint(coords);
  expect(mid[0]).toBeCloseTo(1, 1);
  expect(mid[1]).toBeCloseTo(0, 2);
});

// ── insertCheapest ─────────────────────────────────────────────────────────

test('insertCheapest: inserts midpoint between two endpoints', () => {
  const route = [[-1, 0], [1, 0]];
  const mid = [0, 0];
  insertCheapest(route, mid);
  expect(route.length).toBe(3);
  expect(route[1]).toEqual([0, 0]);
});

test('insertCheapest: returns added km ≥ 0', () => {
  const route = [[-1, 0], [1, 0]];
  const added = insertCheapest(route, [0, 1]);
  expect(added).toBeGreaterThanOrEqual(0);
});

test('insertCheapest: picks cheapest position in multi-point route', () => {
  // route: A(-2,0) → B(0,0) → C(2,0)
  // inserting point at (0.1, 0) should go between B and C, not A and B
  const route = [[-2, 0], [0, 0], [2, 0]];
  const mid = [0.1, 0];
  insertCheapest(route, mid);
  // mid should be between index 2 and 3 (the original [0,0] and [2,0])
  expect(route[2]).toEqual([0.1, 0]);
});

// ── greedyWaypoints ────────────────────────────────────────────────────────

const START = [-1.79, 53.38];
const END   = [-1.84, 53.41];

function makeFeature(coords, score = 80, name = 'Road') {
  return {
    type: 'Feature',
    geometry: { type: 'LineString', coordinates: coords },
    properties: { name, drive_score: score },
  };
}

test('greedyWaypoints: no features → just start and end', () => {
  const { waypoints, overrunKm } = greedyWaypoints([], [], START, END, 200);
  expect(waypoints).toEqual([START, END]);
  expect(overrunKm).toBe(0);
});

test('greedyWaypoints: pinned always included regardless of budget', () => {
  const pinned = [makeFeature([[-1.80, 53.39], [-1.81, 53.40]])];
  const { waypoints } = greedyWaypoints(pinned, [], START, END, 0); // budget 0
  expect(waypoints.length).toBe(3); // start + pinned mid + end
});

test('greedyWaypoints: pins exceeding budget set overrunKm > 0', () => {
  const pinned = [makeFeature([[-1.80, 53.39], [-1.81, 53.40]])];
  const { overrunKm } = greedyWaypoints(pinned, [], START, END, 0);
  expect(overrunKm).toBeGreaterThan(0);
});

test('greedyWaypoints: greedy stops when budget exhausted', () => {
  const features = Array.from({ length: 20 }, (_, i) =>
    makeFeature([[-1.79 - i * 0.01, 53.38], [-1.80 - i * 0.01, 53.39]])
  );
  const { waypoints } = greedyWaypoints([], features, START, END, 1); // tiny budget
  // Should only have start + end (nothing fits within 1km)
  expect(waypoints.length).toBe(2);
});

test('greedyWaypoints: pinned not duplicated by greedy pass', () => {
  const pinned = [makeFeature([[-1.80, 53.39], [-1.81, 53.40]], 90, 'Snake Pass')];
  // Same feature also in scored list
  const scored = [makeFeature([[-1.80, 53.39], [-1.81, 53.40]], 90, 'Snake Pass')];
  const { waypoints } = greedyWaypoints(pinned, scored, START, END, 500);
  // Midpoints are identical so deduplication should prevent double-insertion
  const mids = waypoints.slice(1, -1);
  const unique = new Set(mids.map(p => p[0].toFixed(5) + ',' + p[1].toFixed(5)));
  expect(unique.size).toBe(mids.length);
});

test('greedyWaypoints: MAX_MAPBOX_WP cap respected', () => {
  const features = Array.from({ length: 50 }, (_, i) =>
    makeFeature([[-1.79 - i * 0.001, 53.38], [-1.80 - i * 0.001, 53.39]])
  );
  const { waypoints } = greedyWaypoints([], features, START, END, 100000);
  // Inner waypoints (excluding start/end) should not exceed MAX_MAPBOX_WP
  expect(waypoints.length - 2).toBeLessThanOrEqual(MAX_MAPBOX_WP);
});
