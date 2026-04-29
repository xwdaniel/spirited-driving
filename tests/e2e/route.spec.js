import { test, expect } from '@playwright/test';
import { gotoApp, gotoAppEmpty, waitForList, setSlider } from './helpers.js';

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
