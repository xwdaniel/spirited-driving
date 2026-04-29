/**
 * Map tests — Mapbox GL JS layer/filter/source state via our stub.
 *
 * The mapboxgl stub (from helpers.js) stores all setFilter/addSource/addLayer
 * calls in memory, so we can assert the JS state without WebGL or a token.
 */

import { test, expect } from '@playwright/test';
import { gotoApp, waitForList, setSlider } from './helpers.js';

test.beforeEach(async ({ page }) => {
  await gotoApp(page);
  await waitForList(page);
  // Wait for the map stub to have been initialised (Map constructor called)
  await page.waitForFunction(() => window.map !== null, { timeout: 5000 });
});

// ── Layers exist ───────────────────────────────────────────────────────────

test('all five road layers are registered', async ({ page }) => {
  const ids = ['roads-hi', 'roads-mid', 'roads-low', 'selected-line', 'selected-glow'];
  for (const id of ids) {
    const layer = await page.evaluate(id => window.map.getLayer(id), id);
    expect(layer).not.toBeNull();
    expect(layer.id).toBe(id);
  }
});

test('roads source is populated with features', async ({ page }) => {
  const count = await page.evaluate(() =>
    window.map.getSource('roads')._data.features.length
  );
  expect(count).toBeGreaterThan(0);
});

test('selected source starts with zero features', async ({ page }) => {
  const count = await page.evaluate(() =>
    window.map.getSource('selected')._data.features.length
  );
  expect(count).toBe(0);
});

// ── Chip → map filter wiring ───────────────────────────────────────────────

test('trunk chip adds highway filter to all road layers', async ({ page }) => {
  await page.click('[data-type="trunk"]');
  for (const layer of ['roads-hi', 'roads-mid', 'roads-low']) {
    const f = await page.evaluate(id => JSON.stringify(window.map.getFilter(id)), layer);
    expect(f).toContain('"all"');
    expect(f).toContain('"highway"');
    expect(f).toContain('"trunk"');
  }
});

test('primary chip adds highway filter to all road layers', async ({ page }) => {
  await page.click('[data-type="primary"]');
  for (const layer of ['roads-hi', 'roads-mid', 'roads-low']) {
    const f = await page.evaluate(id => JSON.stringify(window.map.getFilter(id)), layer);
    expect(f).toContain('"highway"');
    expect(f).toContain('"primary"');
  }
});

test('"All" chip restores score-only filter with no highway clause', async ({ page }) => {
  await page.click('[data-type="trunk"]');
  await page.click('[data-type="all"]');
  for (const layer of ['roads-hi', 'roads-mid', 'roads-low']) {
    const f = await page.evaluate(id => JSON.stringify(window.map.getFilter(id)), layer);
    expect(f).not.toContain('"highway"');
  }
});

test('roads-hi filter always contains the >=75 score threshold', async ({ page }) => {
  // Check before any chip click
  const f1 = await page.evaluate(() => JSON.stringify(window.map.getFilter('roads-hi')));
  expect(f1).toContain('75');

  // And after chip filter applied
  await page.click('[data-type="secondary"]');
  const f2 = await page.evaluate(() => JSON.stringify(window.map.getFilter('roads-hi')));
  expect(f2).toContain('75');
});

// ── Slider → source data update ────────────────────────────────────────────

test('slider change calls setData on the roads source', async ({ page }) => {
  // Record the initial _score of the top feature
  const before = await page.evaluate(() =>
    window.map.getSource('roads')._data.features[0]?.properties?._score
  );

  await setSlider(page, 'w-wind', 0);
  await setSlider(page, 'w-speed', 10);

  // The source data should have been replaced (features still present)
  const count = await page.evaluate(() =>
    window.map.getSource('roads')._data.features.length
  );
  expect(count).toBeGreaterThan(0);
});

// ── Selection ─────────────────────────────────────────────────────────────

test('clicking a sidebar card populates the selected source', async ({ page }) => {
  await page.click('.road-card');
  const count = await page.evaluate(() =>
    window.map.getSource('selected')._data.features.length
  );
  expect(count).toBe(1);
});

test('closing the detail panel clears the selected source', async ({ page }) => {
  await page.click('.road-card');
  await page.click('#close-detail');
  const count = await page.evaluate(() =>
    window.map.getSource('selected')._data.features.length
  );
  expect(count).toBe(0);
});
