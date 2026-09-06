const {test, expect} = require('@playwright/test');
const fs = require('node:fs/promises');
const path = require('node:path');

const worker = (id, name, latitude, longitude, extra = {}) => ({
  id, device_id: id, name, hostname: id, cpu: 'test', cpu_cores: 8, ram_gb: 24,
  gpu: 'Apple GPU', gpu_memory_kind: 'unified', gpu_core_count: 16, gpu_memory_gb: null,
  ram_available_gb: 12, gpu_available_gb: null, gpu_model_memory_gb: 8,
  cpu_utilization: 10, memory_utilization: 50, active_tasks: 0,
  supported_tasks: ['summarization', 'document-qa', 'information-extraction', 'coding-assistance'],
  model_id: 'gemma3:12b', model_revision: 'test-digest', status: 'AVAILABLE',
  last_heartbeat: new Date().toISOString(), location: {site: name + ' campus', latitude, longitude}, ...extra
});

async function setup(page, {controlled = false} = {}) {
  const workers = [worker('near', 'New York GPU', 40.71, -74.01),
    worker('far', 'West Coast GPU', 32.72, -117.16),
    worker('offline', 'Offline GPU', 51.51, -.13, {status: 'OFFLINE'}),
    worker('unknown', 'Unlocated GPU', 0, 0, {location: null}),
    worker('wrong', 'Other model GPU', 35.68, 139.69, {model_revision: 'other'})];
  const submissions = [], queries = [], errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('https://tile.openstreetmap.org/**', route => route.fulfill({contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#e7eee9"/><path d="M0 128H256M128 0V256" stroke="#d2ded7"/><text x="20" y="30" fill="#778d81">Test map tile</text></svg>'}));
  await page.route('https://coordinator.test/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.startsWith('/demo/')) {
      const name = url.pathname === '/demo/' ? 'index.html' : url.pathname.slice('/demo/'.length);
      const type = name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : name.endsWith('.svg') ? 'image/svg+xml' : 'text/html';
      return route.fulfill({contentType: type, body: await fs.readFile(path.join(__dirname, '..', name))});
    }
    if (url.pathname === '/api/me') return route.fulfill({json: {auth_mode: controlled ? 'controlled' : 'demo', credential_kind: controlled ? 'account' : 'demo', name: 'Test account', role: 'member'}});
    if (url.pathname === '/api/credits/quote') return route.fulfill({json: {total_inputs: 1, credits: 1, unit: 'demo credits', pricing_version: 'demo-v1'}});
    if (url.pathname === '/api/workers/locations' || url.pathname === '/api/workers/locations/search') {
      queries.push(url.searchParams);
      const origin = route.request().method() === 'POST' ? route.request().postDataJSON() : null;
      const items = workers.filter(w => url.searchParams.get('online_only') !== 'true' || w.status !== 'OFFLINE')
        .map((w, i) => ({worker: w, compatible: w.model_revision === 'test-digest',
          distance_km: w.location ? i * 1500 : null}))
        .sort((a, b) => (a.distance_km ?? Infinity) - (b.distance_km ?? Infinity));
      return route.fulfill({json: {items, total: items.length, limit: 50, offset: 0, distance_reference: origin ? 'request' : 'coordinator'}});
    }
    if (/^\/api\/workers\/[^/]+\/location$/.test(url.pathname)) {
      const id = url.pathname.split('/')[3];
      const w = workers.find(w => w.id === id);
      w.location = route.request().postDataJSON().location;
      return route.fulfill({json: w});
    }
    if (url.pathname === '/api/workers') return route.fulfill({json: workers});
    if (url.pathname === '/api/activity') return route.fulfill({json: {task_counts: {}, retries: 0, active_tasks: [], recent_tasks: [], worker_metrics: []}});
    if (url.pathname === '/api/jobs' && route.request().method() === 'POST') {
      submissions.push(route.request().postDataJSON());
      return route.fulfill({json: {job_id: 'test-job', status: 'QUEUED'}});
    }
    if (url.pathname === '/api/jobs') return route.fulfill({json: []});
    return route.fulfill({json: {job_id: 'test-job', status: 'QUEUED', total_inputs: 1, completed_inputs: 0, failed_inputs: 0, tasks: [], results: []}});
  });
  await page.goto('https://coordinator.test/demo/');
  await page.locator('#token').fill('test-only');
  await page.locator('#connect').click();
  await expect(page.locator('.location-card')).toHaveCount(5);
  return {submissions, queries, errors};
}

test('map discovery, explicit assignment, automatic reset, and disconnect', async ({page}) => {
  await page.setViewportSize({width: 1400, height: 1100});
  const {submissions, queries, errors} = await setup(page);
  await expect(page.locator('.compute-pin')).toHaveCount(4);
  expect(await page.evaluate(() => {
    const bounds = document.getElementById('compute-map').getBoundingClientRect();
    return [...document.querySelectorAll('.compute-pin')].every(pin => {
      const rect = pin.getBoundingClientRect(); const x = rect.x + rect.width / 2, y = rect.y + rect.height / 2;
      return x >= bounds.left && x <= bounds.right && y >= bounds.top && y <= bounds.bottom;
    });
  })).toBe(true);
  await expect(page.getByRole('button', {name: 'Use worker Offline GPU', exact: true})).toBeDisabled();
  await expect(page.getByRole('button', {name: 'Use worker Other model GPU', exact: true})).toBeDisabled();
  await expect(page.locator('.site-distance').first()).toHaveText('0 km away');
  await expect(page.locator('#distance-order')).toHaveText('Closest to coordinator → furthest');
  expect(queries.at(-1).has('latitude')).toBe(false);
  expect(queries.at(-1).has('longitude')).toBe(false);
  await expect(page.locator('#origin-lat, #origin-lon, #locate-me, #apply-location, #clear-location')).toHaveCount(0);
  await expect(page.locator('.location-card-title > strong').filter({hasText: 'New York GPU'})).toHaveCount(1);
  await page.getByRole('button', {name: 'Use worker New York GPU', exact: true}).click();
  await expect(page.locator('#selected-worker')).toContainText('New York GPU');
  await page.locator('#submit').click();
  await expect.poll(() => submissions.length).toBe(1);
  expect(submissions[0].target_worker_id).toBe('near');
  await page.locator('#automatic-worker').click();
  await page.locator('#submit').click();
  await expect.poll(() => submissions.length).toBe(2);
  expect(submissions[1]).not.toHaveProperty('target_worker_id');
  await page.locator('#online-only').check(); await expect(page.locator('.location-card')).toHaveCount(4);
  await page.locator('.compute-explorer').screenshot({path: '/private/tmp/dnhacks-compute-desktop.png'});
  await page.locator('#disconnect').click();
  await expect(page.locator('.compute-pin')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('controlled demo quotes before reserving credits and never persists account token', async ({page}) => {
  const {submissions, errors} = await setup(page, {controlled: true});
  await expect(page.locator('#remember-token')).toBeDisabled();
  await page.locator('#submit').click();
  await expect(page.locator('#credit-quote')).toContainText('Reserve 1 demo credits');
  expect(submissions).toHaveLength(0);
  await page.locator('#submit').click();
  await expect.poll(() => submissions.length).toBe(1);
  expect(await page.evaluate(() => sessionStorage.getItem('coordinatorToken'))).toBeNull();
  await expect(page.locator('#credit-quote')).toBeHidden();
  expect(errors).toEqual([]);
});

test('mobile layout without coordinate controls, and task switching', async ({page, context}) => {
  await page.setViewportSize({width: 390, height: 844});
  await context.clearPermissions();
  const {errors} = await setup(page);
  await expect(page.locator('.compute-explorer input[type=number]')).toHaveCount(0);
  await expect(page.locator('#location-invite')).toBeVisible();
  await page.getByRole('button', {name: 'Use worker New York GPU', exact: true}).click();
  await page.locator('#mode').selectOption('document-qa');
  await expect(page.locator('#selected-worker')).toContainText('Automatic:');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.locator('.compute-explorer').screenshot({path: '/private/tmp/dnhacks-compute-mobile.png'});
  expect(errors).toEqual([]);
});


test('consent shares rounded visitor location in POST body and clears on disconnect', async ({page, context}) => {
  await context.grantPermissions(['geolocation']);
  await context.setGeolocation({latitude: 40.712345, longitude: -74.012345});
  await setup(page);
  await expect(page.locator('#location-invite')).toBeVisible();
  const requestPromise = page.waitForRequest(r => r.url().endsWith('/workers/locations/search'));
  await page.locator('#share-location').click();
  const request = await requestPromise;
  expect(request.method()).toBe('POST');
  expect(request.postDataJSON()).toMatchObject({latitude: 40.71, longitude: -74.01});
  expect(request.url()).not.toContain('latitude');
  await expect(page.locator('#distance-order')).toHaveText('Closest to you → furthest');
  await expect(page.locator('.compute-pin-dot.visitor')).toHaveCount(1);
  await expect(page.locator('#location-invite')).toBeHidden();
  await page.locator('#forget-location').click();
  await expect(page.locator('.compute-pin-dot.visitor')).toHaveCount(0);
  await expect(page.locator('#distance-order')).toHaveText('Closest to coordinator → furthest');
  expect(await page.evaluate(() => Object.keys(localStorage).length)).toBe(0);
});

test('denied permission and LAN HTTP offer manual map selection', async ({page}) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'geolocation', {value: {getCurrentPosition(ok, fail) { fail({code: 1}); }}});
  });
  await setup(page);
  await page.locator('#share-location').click();
  await expect(page.locator('#visitor-location-message')).toContainText('denied');
  await page.evaluate(() => Object.defineProperty(window, 'isSecureContext', {value: false, configurable: true}));
  await page.locator('#share-location').click();
  await expect(page.locator('#visitor-location-message')).toContainText('HTTPS');
  await page.locator('#choose-location').click();
  await page.locator('#compute-map').click({position: {x: 120, y: 120}});
  await page.locator('#save-map-location').click();
  await expect(page.locator('#distance-order')).toHaveText('Closest to you → furthest');
});

test('owner can locate missing worker without changing visitor origin', async ({page}) => {
  await setup(page);
  await page.getByRole('button', {name: 'Set location for Unlocated GPU', exact: true}).click();
  await page.locator('#compute-map').click({position: {x: 180, y: 120}});
  await expect(page.locator('#save-map-location')).toBeDisabled();
  await page.locator('#site-name').fill('Test campus');
  await page.locator('#worker-location-confirm').check();
  const requestPromise = page.waitForRequest(r => r.url().endsWith('/workers/unknown/location'));
  await page.locator('#save-map-location').click();
  expect((await requestPromise).postDataJSON().location.site).toBe('Test campus');
  await expect(page.locator('.compute-pin')).toHaveCount(5);
  await expect(page.locator('.compute-pin-dot.visitor')).toHaveCount(0);
  await expect(page.locator('#distance-order')).toHaveText('Closest to coordinator → furthest');
});

test('zoom is preserved during refresh and missing backend route is explained', async ({page}) => {
  await setup(page);
  const before = await page.evaluate(() => locations.map.getZoom());
  await page.locator('.leaflet-control-zoom-in').click();
  await expect.poll(() => page.evaluate(() => locations.map.getZoom())).toBe(before + 1);
  await page.evaluate(() => locations.refresh());
  expect(await page.evaluate(() => locations.map.getZoom())).toBe(before + 1);
  await page.route('https://coordinator.test/api/workers/locations?**', route => route.fulfill({status: 404, json: {detail: 'Not Found'}}));
  await page.evaluate(() => locations.refresh());
  await expect(page.locator('#location-message')).toContainText('older backend');
});


test('tile failure is explained and late permission response cannot restore forgotten location', async ({page}) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'geolocation', {value: {getCurrentPosition(ok) { window.pendingLocation = ok; }}});
  });
  await setup(page);
  await page.evaluate(() => locations.tiles.fire('tileerror'));
  await expect(page.locator('#tile-message')).toContainText('could not load');
  await page.locator('#share-location').click();
  await page.locator('#disconnect').click();
  await page.evaluate(() => window.pendingLocation({coords: {latitude: 40, longitude: -74}}));
  await expect(page.locator('.compute-pin-dot.visitor')).toHaveCount(0);
  expect(await page.evaluate(() => locations.origin)).toBeNull();
});
