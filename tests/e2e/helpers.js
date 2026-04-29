/**
 * Shared test helpers for Apexline e2e tests.
 */

/**
 * Minimal mapboxgl stub injected before page scripts run.
 * Implements only what apexline.html actually calls so tests don't need
 * a real Mapbox token or WebGL renderer.
 */
export const MAPBOX_STUB = `
(function() {
  const sources = {};
  const filters = {};
  const layers  = {};
  const clickHandlers = [];

  const map = {
    loaded:       () => true,
    addControl:   () => map,
    addSource:    (id, cfg) => {
      sources[id] = {
        _data: cfg.data || { type: 'FeatureCollection', features: [] },
        setData(d) { this._data = d; },
      };
    },
    addLayer: (cfg) => {
      layers[cfg.id] = cfg;
      if (cfg.filter) filters[cfg.id] = cfg.filter;  // capture initial filter
    },
    setFilter: (id, f) => { filters[id] = f; },
    getFilter: (id)    => filters[id] || null,
    getSource: (id)    => sources[id] || null,
    getLayer:  (id)    => layers[id]  ? { id } : null,
    queryRenderedFeatures: () => [],
    on: (evt, layerOrCb, cb) => {
      // map.on('load', cb)  OR  map.on('click', 'layer-id', cb)
      const handler = typeof layerOrCb === 'function' ? layerOrCb : cb;
      if (evt === 'load') setTimeout(handler, 0);
      else if (evt === 'click') clickHandlers.push({ fn: handler, ref: layerOrCb });
      return map;
    },
    off: (evt, fn) => {
      if (evt === 'click') {
        for (let i = clickHandlers.length - 1; i >= 0; i--) {
          if (clickHandlers[i].ref === fn || clickHandlers[i].fn === fn)
            clickHandlers.splice(i, 1);
        }
      }
      return map;
    },
    fitBounds:  () => {},
    getCanvas:  () => ({ style: {} }),
  };

  // Allow tests to simulate map click events (fires generic handlers only, not layer-bound ones)
  window.simulateMapClick = (payload) =>
    clickHandlers.filter(h => typeof h.ref === 'function').forEach(h => h.fn(payload));

  window.map = null;   // will be set when Map constructor runs

  window.mapboxgl = {
    accessToken: '',
    Map: function(opts) {
      // Re-use the single map singleton so tests can reference window.map
      window.map = map;
      return map;
    },
    NavigationControl: function() {},
  };
})();
`;

/**
 * Set a range input value and fire the 'input' event.
 * page.fill() does not dispatch 'input' on <input type="range">.
 */
export async function setSlider(page, id, value) {
  await page.evaluate(([elId, val]) => {
    const el = document.getElementById(elId);
    if (!el) throw new Error('Slider not found: ' + elId);
    el.value = String(val);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  }, [id, value]);
}

// Minimal segment used as the cached API response so the sidebar has data on load.
export const INITIAL_SEGMENT = {
  type: 'Feature',
  geometry: { type: 'LineString', coordinates: [[-1.79, 53.38], [-1.80, 53.39], [-1.81, 53.40]] },
  properties: {
    name: 'A537 Cat and Fiddle', highway: 'primary', maxspeed: 'NSL',
    length_m: 4200, sinuosity: 0.81, narrow: false,
    score_sinuosity: 42, score_angular_density: 55, score_corner_variety: 48,
    score_straight_bend: 72, score_elevation: 70, score_speed_limit: 100,
    score_camera_free: 100,
    drive_score: 77,
  },
};

const INITIAL_SEGMENT_TRUNK = {
  type: 'Feature',
  geometry: { type: 'LineString', coordinates: [[-1.82, 53.41], [-1.83, 53.42], [-1.84, 53.43]] },
  properties: {
    name: 'A57 Snake Pass', highway: 'trunk', maxspeed: 'NSL',
    length_m: 5100, sinuosity: 0.78, narrow: false,
    score_sinuosity: 50, score_angular_density: 60, score_corner_variety: 52,
    score_straight_bend: 75, score_elevation: 85, score_speed_limit: 100,
    score_camera_free: 100,
    drive_score: 82,
  },
};

export const INITIAL_GEOJSON = {
  type: 'FeatureCollection',
  features: [INITIAL_SEGMENT, INITIAL_SEGMENT_TRUNK],
};

/**
 * Navigate to the app with the Mapbox stub in place.
 * Blocks real Mapbox network requests and mocks the cached-segments API endpoint
 * so the sidebar has data to render without a live backend.
 */
export async function gotoApp(page, path = '/apexline.html') {
  await page.addInitScript({ content: MAPBOX_STUB });
  await page.route('**/api.mapbox.com/**',    route => route.abort());
  await page.route('**/events.mapbox.com/**', route => route.abort());
  // Serve config so the map boot sequence completes without a live server
  await page.route('**/localhost:8000/config', route =>
    route.fulfill({ status: 200, contentType: 'application/json',
                    body: JSON.stringify({ mapbox_token: 'pk.e2e.stub' }) })
  );
  // Serve initial data so waitForList() finds road cards immediately
  await page.route('**/localhost:8000/segments/cached', route =>
    route.fulfill({ status: 200, contentType: 'application/json',
                    body: JSON.stringify(INITIAL_GEOJSON) })
  );
  await page.goto(path);
}

/**
 * Wait for the road list to render (GEOJSON is embedded so this is near-instant).
 */
export async function waitForList(page) {
  await page.waitForSelector('.road-card', { timeout: 5000 });
}

/**
 * Navigate to the app with no cached segments — used to test "no data" states.
 */
export async function gotoAppEmpty(page, path = '/apexline.html') {
  await page.addInitScript({ content: MAPBOX_STUB });
  await page.route('**/api.mapbox.com/**',    route => route.abort());
  await page.route('**/events.mapbox.com/**', route => route.abort());
  await page.route('**/localhost:8000/config', route =>
    route.fulfill({ status: 200, contentType: 'application/json',
                    body: JSON.stringify({ mapbox_token: 'pk.e2e.stub' }) })
  );
  await page.route('**/localhost:8000/segments/cached', route =>
    route.fulfill({ status: 200, contentType: 'application/json',
                    body: JSON.stringify({ type: 'FeatureCollection', features: [] }) })
  );
  await page.goto(path);
}
