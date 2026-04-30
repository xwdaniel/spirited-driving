import { test, expect } from '@playwright/test';
import { gotoApp, gotoAppEmpty, waitForList, setSlider, gotoAppWith, INITIAL_GEOJSON } from './helpers.js';

// ── Tab navigation ─────────────────────────────────────────────────────────

test.describe('Route tab', () => {
  test.beforeEach(async ({ page }) => {
    await gotoApp(page);
    await waitForList(page);
  });

  test('clicking Route tab shows route panel', async ({ page }) => {
    await page.click('#tab-route');
    await expect(page.locator('#panel-route')).toHaveClass(/active/);
    await expect(page.locator('#panel-roads')).not.toHaveClass(/active/);
  });

  test('clicking Roads tab restores roads panel', async ({ page }) => {
    await page.click('#tab-route');
    await page.click('#tab-roads');
    await expect(page.locator('#panel-roads')).toHaveClass(/active/);
    await expect(page.locator('#panel-route')).not.toHaveClass(/active/);
  });

  // ── Loop toggle ─────────────────────────────────────────────────────────

  test('end field is hidden when loop checkbox is checked (default)', async ({ page }) => {
    await page.click('#tab-route');
    await expect(page.locator('#route-end-field')).toHaveCSS('display', 'none');
  });

  test('unchecking loop reveals end field', async ({ page }) => {
    await page.click('#tab-route');
    await page.uncheck('#route-loop');
    await expect(page.locator('#route-end-field')).not.toHaveCSS('display', 'none');
  });

  test('re-checking loop hides end field again', async ({ page }) => {
    await page.click('#tab-route');
    await page.uncheck('#route-loop');
    await page.check('#route-loop');
    await expect(page.locator('#route-end-field')).toHaveCSS('display', 'none');
  });

  // ── Hours slider ─────────────────────────────────────────────────────────

  test('hours slider updates displayed value', async ({ page }) => {
    await page.click('#tab-route');
    await setSlider(page, 'route-hours', 3);
    await expect(page.locator('#route-hours-val')).toHaveText('3 hrs');
  });

  test('hours slider shows half-hour values', async ({ page }) => {
    await page.click('#tab-route');
    await setSlider(page, 'route-hours', 1.5);
    await expect(page.locator('#route-hours-val')).toHaveText('1.5 hrs');
  });

  // ── Plan button — Mapbox failure ─────────────────────────────────────────

  test('plan button re-enables after Mapbox Directions failure', async ({ page }) => {
    await page.click('#tab-route');
    // Set a start point via simulated map click (focus sets pickingFor = 'start')
    await page.focus('#route-start');
    await page.evaluate(() => {
      window.simulateMapClick({ lngLat: { lng: -1.79, lat: 53.38 } });
    });
    await page.click('#plan-btn');
    // Mapbox Directions is aborted by gotoApp → fetch fails → finally re-enables
    await expect(page.locator('#plan-btn')).toBeEnabled({ timeout: 5000 });
    await expect(page.locator('#plan-btn')).toHaveText('Plan spirited route');
  });
});

// ── Plan button disabled when no road data ─────────────────────────────────

test.describe('Plan button — no data', () => {
  test('plan button is disabled when no road data is loaded', async ({ page }) => {
    await gotoAppEmpty(page);
    // Wait for page to finish loading (config fetch completes)
    await page.waitForLoadState('networkidle');
    await expect(page.locator('#plan-btn')).toBeDisabled();
  });

  test('plan button is enabled after road data loads', async ({ page }) => {
    await gotoApp(page);
    await waitForList(page);
    await expect(page.locator('#plan-btn')).toBeEnabled();
  });
});

// ── Pin button ─────────────────────────────────────────────────────────────

test.describe('Pin button', () => {
  test.beforeEach(async ({ page }) => {
    await gotoApp(page);
    await waitForList(page);
  });

  test('pin button is visible on each road card', async ({ page }) => {
    const pins = page.locator('.road-card .pin-btn');
    await expect(pins.first()).toBeVisible();
    const count = await pins.count();
    expect(count).toBeGreaterThan(0);
  });

  test('pin button shows "+ pin" by default', async ({ page }) => {
    await expect(page.locator('.road-card .pin-btn').first()).toHaveText('+ pin');
  });

  test('clicking pin button toggles card to pinned state', async ({ page }) => {
    const card = page.locator('.road-card').first();
    await card.locator('.pin-btn').click();
    await expect(card).toHaveClass(/pinned/);
  });

  test('clicking pin button changes text to "✕ pinned"', async ({ page }) => {
    const btn = page.locator('.road-card .pin-btn').first();
    await btn.click();
    await expect(btn).toHaveText('✕ pinned');
  });

  test('clicking pinned button again unpins the card', async ({ page }) => {
    const card = page.locator('.road-card').first();
    const btn  = card.locator('.pin-btn');
    await btn.click();
    await btn.click();
    await expect(card).not.toHaveClass(/pinned/);
    await expect(btn).toHaveText('+ pin');
  });

  test('pinned button has .pinned class when active', async ({ page }) => {
    const btn = page.locator('.road-card .pin-btn').first();
    await btn.click();
    await expect(btn).toHaveClass(/pinned/);
  });
});

// ── sampleEvenly ───────────────────────────────────────────────────────────

test.describe('sampleEvenly', () => {
  test.beforeEach(async ({ page }) => {
    await gotoApp(page);
    await waitForList(page);
  });

  test('returns full array when length <= n', async ({ page }) => {
    const result = await page.evaluate(() => window.sampleEvenly([1, 2, 3], 5));
    expect(result).toEqual([1, 2, 3]);
  });

  test('returns exactly n elements when length > n', async ({ page }) => {
    const result = await page.evaluate(() => window.sampleEvenly([0,1,2,3,4,5,6,7,8,9], 4));
    expect(result).toHaveLength(4);
  });

  test('first element is always arr[0]', async ({ page }) => {
    const result = await page.evaluate(() => window.sampleEvenly([10,20,30,40,50], 3));
    expect(result[0]).toBe(10);
  });

  test('last element is always arr[arr.length-1]', async ({ page }) => {
    const result = await page.evaluate(() => window.sampleEvenly([10,20,30,40,50], 3));
    expect(result[result.length - 1]).toBe(50);
  });

  test('samples from across the full array, not just the start', async ({ page }) => {
    const arr = [0,1,2,3,4,5,6,7,8,9];
    const result = await page.evaluate((a) => window.sampleEvenly(a, 3), arr);
    expect(result[0]).toBe(0);
    expect(result[2]).toBe(9);
    // middle element must come from the middle of the array, not near the start
    expect(result[1]).toBeGreaterThan(2);
    expect(result[1]).toBeLessThan(8);
  });
});

// ── greedyWaypoints budget ─────────────────────────────────────────────────

test.describe('greedyWaypoints budget', () => {
  test.beforeEach(async ({ page }) => {
    await gotoApp(page);
    await waitForList(page);
  });

  test('includes segment midpoints within budget', async ({ page }) => {
    const features = INITIAL_GEOJSON.features;
    const result = await page.evaluate((feats) => {
      const start = [-1.79, 53.38];
      return window.greedyWaypoints([], feats, start, start, 500).waypoints.length;
    }, features);
    expect(result).toBeGreaterThan(2); // start + at least one midpoint + end
  });

  test('omits all segments when budget is zero', async ({ page }) => {
    const features = INITIAL_GEOJSON.features;
    const result = await page.evaluate((feats) => {
      const start = [-1.79, 53.38];
      return window.greedyWaypoints([], feats, start, start, 0).waypoints.length;
    }, features);
    expect(result).toBe(2); // only start and end
  });
});

// ── Google Maps URL waypoint sampling ─────────────────────────────────────

// 12-segment fixture for testing URL waypoint sampling
const TWELVE_SEGS = {
  type: 'FeatureCollection',
  features: Array.from({ length: 12 }, (_, i) => ({
    type: 'Feature',
    geometry: {
      type: 'LineString',
      coordinates: [
        [-1.79 + i * 0.002, 53.38],
        [-1.80 + i * 0.002, 53.39],
        [-1.81 + i * 0.002, 53.40],
      ],
    },
    properties: {
      name: `Test Road ${i}`, highway: 'primary', maxspeed: 'NSL',
      length_m: 3000, sinuosity: 0.80, narrow: false,
      score_sinuosity: 60, score_angular_density: 60, score_corner_variety: 60,
      score_straight_bend: 70, score_elevation: 80, score_speed_limit: 100,
      score_camera_free: 100, drive_score: 99 - i,
    },
  })),
};

const MOCK_DIRECTIONS_RESP = {
  routes: [{
    geometry: { type: 'LineString', coordinates: [[-1.79, 53.38], [-1.81, 53.40]] },
    distance: 5000,
    duration: 600,
  }],
};

test.describe('Google Maps URL waypoint sampling', () => {
  async function planRoute(page) {
    await page.click('#tab-route');
    await page.focus('#route-start');
    await page.evaluate(() => {
      window.simulateMapClick({ lngLat: { lng: -1.79, lat: 53.38 } });
    });
    await page.click('#plan-btn');
    await page.waitForSelector('.gmaps-btn', { timeout: 5000 });
    return page.locator('.gmaps-btn').getAttribute('href');
  }

  test('URL has at most MAX_GMAPS_WP + 2 path parts with 12 segments', async ({ page }) => {
    await gotoAppWith(page, { segments: TWELVE_SEGS, directions: MOCK_DIRECTIONS_RESP });
    await waitForList(page);
    const href = await planRoute(page);
    // path after /dir/ splits on '/' → count parts
    const parts = href.replace('https://www.google.com/maps/dir/', '').split('/').filter(Boolean);
    expect(parts.length).toBeLessThanOrEqual(11); // MAX_GMAPS_WP(9) inner + start + end
  });

  test('URL includes both start and end coordinates', async ({ page }) => {
    await gotoAppWith(page, { segments: INITIAL_GEOJSON, directions: MOCK_DIRECTIONS_RESP });
    await waitForList(page);
    const href = await planRoute(page);
    const parts = href.replace('https://www.google.com/maps/dir/', '').split('/').filter(Boolean);
    // First part = start lat,lng; last part = end lat,lng (loop → same point)
    expect(parts[0]).toMatch(/^[\d.-]+,[\d.-]+$/);
    expect(parts[parts.length - 1]).toBe(parts[0]);
  });
});
