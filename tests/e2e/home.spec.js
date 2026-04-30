import { test, expect } from '@playwright/test';
import { gotoApp, waitForList } from './helpers.js';

const FAKE_NOMINATIM_HOME = [{
  display_name: 'Sheffield, South Yorkshire, England, United Kingdom',
  lat: '53.3811',
  lon: '-1.4701',
  boundingbox: ['53.30', '53.45', '-1.60', '-1.35'],
}];

async function setup(page, { home = null } = {}) {
  if (home) {
    await page.addInitScript((h) => localStorage.setItem('apexline_home', JSON.stringify(h)), home);
  }
  await gotoApp(page);
  await waitForList(page);
}

const SAVED_HOME = { lon: -1.4701, lat: 53.3811, label: 'Sheffield' };

// ── Cycle 1: Settings modal ────────────────────────────────────────────────

test.describe('Settings modal', () => {
  test('gear button opens settings modal', async ({ page }) => {
    await setup(page);
    await page.click('#settings-btn');
    await expect(page.locator('#settings-modal')).toBeVisible();
  });

  test('close button hides settings modal', async ({ page }) => {
    await setup(page);
    await page.click('#settings-btn');
    await page.click('#settings-close');
    await expect(page.locator('#settings-modal')).toBeHidden();
  });
});

// ── Cycle 2: "Use home" button visibility ─────────────────────────────────

test.describe('"Use home as start" button', () => {
  test('hidden by default when no home is saved', async ({ page }) => {
    await setup(page);
    await page.click('#tab-route');
    await expect(page.locator('#use-home-btn')).toBeHidden();
  });

  test('visible when home is in localStorage on load', async ({ page }) => {
    await setup(page, { home: SAVED_HOME });
    await page.click('#tab-route');
    await expect(page.locator('#use-home-btn')).toBeVisible();
  });
});

// ── Cycle 4: "Use home" click populates route start ───────────────────────

test.describe('"Use home as start" click', () => {
  test('populates start input with home label', async ({ page }) => {
    await setup(page, { home: SAVED_HOME });
    await page.click('#tab-route');
    await page.click('#use-home-btn');
    await expect(page.locator('#route-start')).toHaveValue('Sheffield');
  });

  test('enables the plan button', async ({ page }) => {
    await setup(page, { home: SAVED_HOME });
    await page.click('#tab-route');
    await page.click('#use-home-btn');
    await expect(page.locator('#plan-btn')).toBeEnabled();
  });
});

// ── Cycle 5: Clearing home ────────────────────────────────────────────────

test.describe('Clearing home', () => {
  test('clear button removes home from localStorage', async ({ page }) => {
    await setup(page, { home: SAVED_HOME });
    await page.click('#settings-btn');
    await page.click('#home-clear-btn');
    const stored = await page.evaluate(() => localStorage.getItem('apexline_home'));
    expect(stored).toBeNull();
  });

  test('clear button hides "Use home" button', async ({ page }) => {
    await setup(page, { home: SAVED_HOME });
    await page.click('#settings-btn');
    await page.click('#home-clear-btn');
    await page.click('#tab-route');
    await expect(page.locator('#use-home-btn')).toBeHidden();
  });
});

// ── Cycle 6: Startup fly-to ───────────────────────────────────────────────

test.describe('Startup fly-to', () => {
  test('map.flyTo is called with home coordinates on load when home is set', async ({ page }) => {
    await page.addInitScript((h) => {
      localStorage.setItem('apexline_home', JSON.stringify(h));
      // Intercept window.mapboxgl assignment (runs before MAPBOX_STUB)
      // so we can wrap the Map constructor and spy on flyTo.
      window.__flyToCalls = [];
      let _val;
      Object.defineProperty(window, 'mapboxgl', {
        configurable: true,
        get() { return _val; },
        set(v) {
          if (v && v.Map) {
            const Orig = v.Map;
            v.Map = function(opts) {
              const inst = new Orig(opts);
              const orig = inst.flyTo;
              inst.flyTo = function(o) { window.__flyToCalls.push(o); return orig && orig.call(inst, o); };
              return inst;
            };
          }
          _val = v;
        },
      });
    }, SAVED_HOME);
    await gotoApp(page);
    await waitForList(page);
    const calls = await page.evaluate(() => window.__flyToCalls);
    expect(calls.length).toBeGreaterThan(0);
    expect(calls[0].center[0]).toBeCloseTo(SAVED_HOME.lon, 2);
    expect(calls[0].center[1]).toBeCloseTo(SAVED_HOME.lat, 2);
  });
});

// ── Cycle 3: Saving home via settings ─────────────────────────────────────

test.describe('Saving home', () => {
  test('saving home writes to localStorage and shows "Use home" button', async ({ page }) => {
    await page.route('**/nominatim.openstreetmap.org/**', route =>
      route.fulfill({ status: 200, contentType: 'application/json',
                      body: JSON.stringify(FAKE_NOMINATIM_HOME) })
    );
    await setup(page);
    await page.click('#settings-btn');
    await page.fill('#home-input', 'Sheffield');
    await page.click('#home-save-btn');
    await expect(page.locator('#settings-modal')).toBeHidden();
    // localStorage persisted
    const stored = await page.evaluate(() => localStorage.getItem('apexline_home'));
    expect(stored).not.toBeNull();
    const parsed = JSON.parse(stored);
    expect(parsed.label).toBe('Sheffield');
    expect(parsed.lon).toBeCloseTo(-1.4701, 2);
    // "Use home" button now visible
    await page.click('#tab-route');
    await expect(page.locator('#use-home-btn')).toBeVisible();
  });
});
