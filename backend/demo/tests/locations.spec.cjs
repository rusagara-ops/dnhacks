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

async function setup(page) {
  const workers = [worker('near', 'New York GPU', 40.71, -74.01),
    worker('far', 'West Coast GPU', 32.72, -117.16),
    worker('offline', 'Offline GPU', 51.51, -.13, {status: 'OFFLINE'}),
    worker('unknown', 'Unlocated GPU', 0, 0, {location: null}),
    worker('wrong', 'Other model GPU', 35.68, 139.69, {model_revision: 'other'})];
  const submissions = [], queries = [], errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('https://coordinator.test/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.startsWith('/demo/')) {
      const name = url.pathname === '/demo/' ? 'index.html' : path.basename(url.pathname);
      const type = name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : name.endsWith('.svg') ? 'image/svg+xml' : 'text/html';
      return route.fulfill({contentType: type, body: await fs.readFile(path.join(__dirname, '..', name))});
    }
    if (url.pathname === '/api/workers/locations') {
      queries.push(url.searchParams);
      const items = workers.filter(w => url.searchParams.get('online_only') !== 'true' || w.status !== 'OFFLINE')
        .map((w, i) => ({worker: w, compatible: w.model_revision === 'test-digest',
          distance_km: w.location ? i * 1500 : null}))
        .sort((a, b) => (a.distance_km ?? Infinity) - (b.distance_km ?? Infinity));
      return route.fulfill({json: {items, total: items.length, limit: 50, offset: 0, distance_reference: 'coordinator'}});
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
  await expect(page.locator('.map-pin')).toHaveCount(4);
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
  await expect(page.locator('.map-pin')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('mobile layout without coordinate controls, and task switching', async ({page, context}) => {
  await page.setViewportSize({width: 390, height: 844});
  await context.clearPermissions();
  const {errors} = await setup(page);
  await expect(page.locator('.compute-explorer input[type=number]')).toHaveCount(0);
  await page.getByRole('button', {name: 'Use worker New York GPU', exact: true}).click();
  await page.locator('#mode').selectOption('document-qa');
  await expect(page.locator('#selected-worker')).toContainText('Automatic:');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.locator('.compute-explorer').screenshot({path: '/private/tmp/dnhacks-compute-mobile.png'});
  expect(errors).toEqual([]);
});
