import { test, expect } from '@playwright/test';
import { gotoApp, waitForList, setSlider } from './helpers.js';

test.beforeEach(async ({ page }) => {
  await gotoApp(page);
  await waitForList(page);
});

// ── Road list ──────────────────────────────────────────────────────────────

test('road list renders at least one card on load', async ({ page }) => {
  await expect(page.locator('.road-card').first()).toBeVisible();
});

test('results-meta shows road count', async ({ page }) => {
  await expect(page.locator('#results-meta')).toContainText('roads');
});

test('each card shows a numeric score badge in 0–100', async ({ page }) => {
  const badges = page.locator('.score-big');
  const count  = await badges.count();
  expect(count).toBeGreaterThan(0);
  for (let i = 0; i < count; i++) {
    const n = parseInt(await badges.nth(i).textContent(), 10);
    expect(n).toBeGreaterThanOrEqual(0);
    expect(n).toBeLessThanOrEqual(100);
  }
});

test('cards are sorted by score descending', async ({ page }) => {
  const badges = page.locator('.score-big');
  const count  = await badges.count();
  const scores = [];
  for (let i = 0; i < count; i++) {
    scores.push(parseInt(await badges.nth(i).textContent(), 10));
  }
  expect(scores).toEqual([...scores].sort((a, b) => b - a));
});

// ── Road name search ───────────────────────────────────────────────────────

test('name search filters list to matching roads', async ({ page }) => {
  await page.fill('#search-input', 'A537');
  const cards = page.locator('.road-card');
  const count = await cards.count();
  expect(count).toBeGreaterThan(0);
  for (let i = 0; i < count; i++) {
    const name = await cards.nth(i).locator('.card-name').textContent();
    expect(name.toLowerCase()).toContain('a537');
  }
});

test('name search with no match shows empty list', async ({ page }) => {
  await page.fill('#search-input', 'ZZZNOMATCH999');
  await expect(page.locator('.road-card')).toHaveCount(0);
});

test('clearing name search restores full list', async ({ page }) => {
  const initial = await page.locator('.road-card').count();
  await page.fill('#search-input', 'A537');
  await page.fill('#search-input', '');
  await expect(page.locator('.road-card')).toHaveCount(initial);
});

// ── Road class chips ───────────────────────────────────────────────────────

test('"All" chip is active on load', async ({ page }) => {
  await expect(page.locator('[data-type="all"]')).toHaveClass(/\bon\b/);
});

test('clicking a chip makes it active and deactivates others', async ({ page }) => {
  await page.click('[data-type="trunk"]');
  await expect(page.locator('[data-type="trunk"]')).toHaveClass(/\bon\b/);
  await expect(page.locator('[data-type="all"]')).not.toHaveClass(/\bon\b/);
  await expect(page.locator('[data-type="primary"]')).not.toHaveClass(/\bon\b/);
});

test('trunk chip filters list to trunk roads only', async ({ page }) => {
  await page.click('[data-type="trunk"]');
  const cards = page.locator('.road-card');
  const count = await cards.count();
  expect(count).toBeGreaterThan(0);
  for (let i = 0; i < count; i++) {
    const region = await cards.nth(i).locator('.card-region').textContent();
    expect(region.toLowerCase()).toMatch(/trunk/);
  }
});

test('primary chip filters list to primary roads only', async ({ page }) => {
  await page.click('[data-type="primary"]');
  const cards = page.locator('.road-card');
  const count = await cards.count();
  expect(count).toBeGreaterThan(0);
  for (let i = 0; i < count; i++) {
    const region = await cards.nth(i).locator('.card-region').textContent();
    expect(region.toLowerCase()).toMatch(/primary/);
  }
});

test('"All" chip restores full list after filtering', async ({ page }) => {
  const initial = await page.locator('.road-card').count();
  await page.click('[data-type="trunk"]');
  await page.click('[data-type="all"]');
  await expect(page.locator('.road-card')).toHaveCount(initial);
});

test('chip + name search compose correctly', async ({ page }) => {
  await page.click('[data-type="primary"]');
  await page.fill('#search-input', 'A537');
  const cards = page.locator('.road-card');
  const count = await cards.count();
  for (let i = 0; i < count; i++) {
    const name   = await cards.nth(i).locator('.card-name').textContent();
    const region = await cards.nth(i).locator('.card-region').textContent();
    expect(name.toLowerCase()).toContain('a537');
    expect(region.toLowerCase()).toMatch(/primary/);
  }
});

// ── Weight sliders ─────────────────────────────────────────────────────────

test('slider display value updates on input', async ({ page }) => {
  await setSlider(page, 'w-wind', 3);
  await expect(page.locator('#v-wind')).toHaveText('3');

  await setSlider(page, 'w-speed', 1);
  await expect(page.locator('#v-speed')).toHaveText('1');
});

test('setting all weights to zero does not produce NaN scores', async ({ page }) => {
  for (const id of ['w-wind', 'w-speed', 'w-cam', 'w-width']) {
    await setSlider(page, id, 0);
  }
  const badges = page.locator('.score-big');
  const count  = await badges.count();
  expect(count).toBeGreaterThan(0);
  for (let i = 0; i < count; i++) {
    expect(await badges.nth(i).textContent()).not.toMatch(/NaN|Infinity/);
  }
});

test('changing weights keeps list sorted by new score', async ({ page }) => {
  await setSlider(page, 'w-wind', 0);
  await setSlider(page, 'w-speed', 10);
  const badges = page.locator('.score-big');
  const count  = await badges.count();
  expect(count).toBeGreaterThan(0);
  const scores = [];
  for (let i = 0; i < count; i++) {
    scores.push(parseInt(await badges.nth(i).textContent(), 10));
  }
  expect(scores).toEqual([...scores].sort((a, b) => b - a));
});

// ── Detail panel ───────────────────────────────────────────────────────────

test('clicking a card opens the detail panel', async ({ page }) => {
  await page.click('.road-card');
  await expect(page.locator('#detail')).toHaveClass(/show/);
});

test('detail panel shows the clicked road name', async ({ page }) => {
  const firstName = await page.locator('.road-card .card-name').first().textContent();
  await page.click('.road-card');
  await expect(page.locator('#d-name')).toHaveText(firstName);
});

test('detail panel shows a valid score', async ({ page }) => {
  await page.click('.road-card');
  const score = await page.locator('#d-score').textContent();
  expect(score).toMatch(/\d+\s*\/\s*100/);
  expect(parseInt(score, 10)).toBeGreaterThan(0);
});

test('detail panel sub-score bars have widths in 0–100%', async ({ page }) => {
  await page.click('.road-card');
  for (const id of ['db-wind', 'db-speed', 'db-cam', 'db-width']) {
    const w = await page.locator(`#${id}`).evaluate(el => parseFloat(el.style.width));
    expect(w).toBeGreaterThanOrEqual(0);
    expect(w).toBeLessThanOrEqual(100);
  }
});

test('close button hides the detail panel', async ({ page }) => {
  await page.click('.road-card');
  await page.click('#close-detail');
  await expect(page.locator('#detail')).not.toHaveClass(/show/);
});

test('active card gets the .active class', async ({ page }) => {
  const name = await page.locator('.road-card:first-child .card-name').textContent();
  await page.click('.road-card:first-child');
  // Multiple sections of the same named road all get .active — that's by design
  const active = page.locator('.road-card.active');
  await expect(active).not.toHaveCount(0);
  // Every active card must share the clicked road's name
  const count = await active.count();
  for (let i = 0; i < count; i++) {
    await expect(active.nth(i).locator('.card-name')).toHaveText(name);
  }
});

test('closing detail panel clears the active card', async ({ page }) => {
  await page.click('.road-card');
  await page.click('#close-detail');
  await expect(page.locator('.road-card.active')).toHaveCount(0);
});

// ── Responsive layout ──────────────────────────────────────────────────────

test('sidebar stacks above map on mobile viewport', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await gotoApp(page);
  const sidebarY = await page.locator('.sidebar').evaluate(el => el.getBoundingClientRect().top);
  const mapY     = await page.locator('.map-wrap').evaluate(el => el.getBoundingClientRect().top);
  expect(sidebarY).toBeLessThan(mapY);
});
