/**
 * Location search tests — Nominatim geocoding and API fetch, both mocked.
 */

import { test, expect } from '@playwright/test';
import { gotoApp, waitForList } from './helpers.js';

const FAKE_NOMINATIM = [{
  display_name: 'Yorkshire Dales, North Yorkshire, England, United Kingdom',
  boundingbox: ['54.06', '54.45', '-2.44', '-1.83'],
}];

const FAKE_SEGMENTS = {
  type: 'FeatureCollection',
  features: [{
    type: 'Feature',
    geometry: { type: 'LineString', coordinates: [[-1.79, 53.38], [-1.80, 53.39]] },
    properties: {
      name: 'B1234 Test Road', highway: 'secondary', maxspeed: 'NSL',
      length_m: 3200, sinuosity: 0.72, narrow: false,
      score_sinuosity: 40, score_angular_density: 55, score_corner_variety: 45,
      score_straight_bend: 68, score_elevation: 50, score_speed_limit: 100,
      score_camera_free: 100,
      drive_score: 72,
    },
  }],
};

async function setup(page, { nominatim = FAKE_NOMINATIM, apiStatus = 200, apiBody = FAKE_SEGMENTS } = {}) {
  await gotoApp(page);
  await waitForList(page);

  await page.route('**/nominatim.openstreetmap.org/**', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(nominatim) })
  );

  if (apiStatus === 'abort') {
    await page.route('**/localhost:8000/**', route => route.abort());
  } else {
    await page.route('**/localhost:8000/**', route =>
      route.fulfill({ status: apiStatus, contentType: 'application/json', body: JSON.stringify(apiBody) })
    );
  }
}

// ── Successful geocode + API fetch ─────────────────────────────────────────

test('location search updates header with place name', async ({ page }) => {
  await setup(page);
  await page.fill('#location-input', 'Yorkshire Dales');
  await page.press('#location-input', 'Enter');
  await expect(page.locator('#logo-sub')).toContainText('Yorkshire Dales', { timeout: 5000 });
});

test('road list updates to show fetched segments', async ({ page }) => {
  await setup(page);
  await page.fill('#location-input', 'Yorkshire Dales');
  await page.press('#location-input', 'Enter');
  await expect(page.locator('#logo-sub')).toContainText('Yorkshire Dales', { timeout: 5000 });
  await expect(page.locator('.road-card')).toHaveCount(1);
  await expect(page.locator('.road-card .card-name')).toHaveText('B1234 Test Road');
});

test('segment count in header updates to match fetched data', async ({ page }) => {
  await setup(page);
  await page.fill('#location-input', 'Yorkshire Dales');
  await page.press('#location-input', 'Enter');
  await expect(page.locator('#logo-sub')).toContainText('1 segment', { timeout: 5000 });
});

test('loading overlay appears then disappears after successful fetch', async ({ page }) => {
  await setup(page);
  await page.fill('#location-input', 'Yorkshire Dales');
  await page.press('#location-input', 'Enter');
  // Overlay must be gone by the time the response resolves
  await expect(page.locator('#loading-overlay')).not.toHaveClass(/show/, { timeout: 5000 });
});

test('map source is updated with new features after fetch', async ({ page }) => {
  await setup(page);
  await page.waitForFunction(() => window.map !== null, { timeout: 5000 });
  await page.fill('#location-input', 'Yorkshire Dales');
  await page.press('#location-input', 'Enter');
  await expect(page.locator('#logo-sub')).toContainText('Yorkshire Dales', { timeout: 5000 });
  const count = await page.evaluate(() => window.map.getSource('roads')._data.features.length);
  expect(count).toBe(1);
});

// ── API offline ────────────────────────────────────────────────────────────

test('shows "API offline" when server is unreachable', async ({ page }) => {
  await setup(page, { apiStatus: 'abort' });
  await page.fill('#location-input', 'Yorkshire Dales');
  await page.press('#location-input', 'Enter');
  await expect(page.locator('#loc-status')).toHaveText('API offline', { timeout: 5000 });
});

test('loading overlay clears even when API is offline', async ({ page }) => {
  await setup(page, { apiStatus: 'abort' });
  await page.fill('#location-input', 'Yorkshire Dales');
  await page.press('#location-input', 'Enter');
  await expect(page.locator('#loading-overlay')).not.toHaveClass(/show/, { timeout: 5000 });
});

test('original road data is preserved when API is offline', async ({ page }) => {
  await setup(page, { apiStatus: 'abort' });
  const countBefore = await page.locator('.road-card').count();
  await page.fill('#location-input', 'Yorkshire Dales');
  await page.press('#location-input', 'Enter');
  await expect(page.locator('#loc-status')).toHaveText('API offline', { timeout: 5000 });
  await expect(page.locator('.road-card')).toHaveCount(countBefore);
});

// ── Geocode failures ───────────────────────────────────────────────────────

test('shows "Not found" for an unknown place', async ({ page }) => {
  await setup(page, { nominatim: [] });
  await page.fill('#location-input', 'XYZNONEXISTENTPLACE');
  await page.press('#location-input', 'Enter');
  await expect(page.locator('#loc-status')).toHaveText('Not found', { timeout: 5000 });
});

test('empty input does nothing when Enter is pressed', async ({ page }) => {
  await setup(page);
  const countBefore = await page.locator('.road-card').count();
  await page.fill('#location-input', '');
  await page.press('#location-input', 'Enter');
  // No fetch should have been initiated — count unchanged, status empty
  await expect(page.locator('.road-card')).toHaveCount(countBefore);
  await expect(page.locator('#loc-status')).toHaveText('');
});
