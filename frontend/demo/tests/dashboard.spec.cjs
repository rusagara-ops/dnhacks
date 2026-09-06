const {test, expect} = require('@playwright/test');
const fs = require('node:fs/promises');
const path = require('node:path');

const worker = (id, name, extra = {}) => ({
  id, device_id: id, name, hostname: id, cpu: 'arm64', cpu_cores: 8,
  ram_gb: 24, ram_available_gb: 12, gpu: 'Apple GPU', gpu_memory_kind: 'unified',
  gpu_core_count: 16, gpu_memory_gb: null, gpu_available_gb: null, gpu_model_memory_gb: 8,
  cpu_utilization: 10, memory_utilization: 50, active_tasks: 0,
  supported_tasks: ['summarization', 'document-qa', 'information-extraction', 'coding-assistance'],
  model_id: 'gemma3:12b', model_revision: 'test-digest', status: 'AVAILABLE',
  last_heartbeat: new Date().toISOString(), ...extra
});

async function setup(page) {
  const workers = [worker('abel', 'Abel-Mac'), worker('kevin', 'Kevin-Mac', {ram_gb: 8, ram_available_gb: 4, model_id: 'qwen2.5-coder:3b'}), worker('abel-old', 'Abel-Mac', {status: 'OFFLINE'})];
  const submissions = [], errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('https://coordinator.test/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.startsWith('/demo/')) {
      const name = url.pathname === '/demo/' ? 'index.html' : url.pathname.slice('/demo/'.length);
      const type = name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : 'text/html';
      return route.fulfill({contentType: type, body: await fs.readFile(path.join(__dirname, '..', name))});
    }
    if (url.pathname === '/api/workers') return route.fulfill({json: workers});
    if (url.pathname === '/api/activity') return route.fulfill({json: {
      as_of: new Date().toISOString(), task_counts: {QUEUED: 1, ASSIGNED: 1, RUNNING: 0, COMPLETED: 4, FAILED: 0}, retries: 1,
      active_tasks: [{task_id: 'active-task', job_id: 'active-job', task_type: 'summarization', status: 'ASSIGNED', worker_id: 'abel', worker_name: 'Abel-Mac', model_id: 'gemma3:12b', model_revision: 'test-digest', start_index: 0, input_count: 1, attempt_count: 1, elapsed_seconds: 2, queue_seconds: 1}],
      recent_tasks: [{task_id: 'active-task', job_id: 'active-job', task_type: 'summarization', status: 'ASSIGNED', worker_id: 'abel', worker_name: 'Abel-Mac', model_id: 'gemma3:12b', model_revision: 'test-digest', start_index: 0, input_count: 1, attempt_count: 1, elapsed_seconds: 2, queue_seconds: 1}],
      worker_metrics: [{worker_id: 'abel', completed_tasks: 4, completed_inputs: 4, average_execution_ms: 4200}]
    }});
    if (url.pathname === '/api/stats') return route.fulfill({json: {
      workers_online: 2, workers_available: 2, workers_busy: 0, jobs_queued: 0, jobs_running: 0,
      jobs_completed: 9, jobs_failed: 1, tasks_completed: 12, total_inferences: 40
    }});
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
  return {submissions, errors};
}

test('shows worker selection and coordinator task distribution without a map', async ({page}) => {
  const {errors} = await setup(page);
  await expect(page.locator('#compute-map, #location-invite, .leaflet-container')).toHaveCount(0);
  await expect(page.locator('#worker-picker .picker-card')).toHaveCount(2);
  await expect(page.locator('#workers .worker')).toHaveCount(2);
  await expect(page.locator('#overview .telemetry-card')).toHaveCount(5);
  await expect(page.locator('#distribution .distribution-card')).toHaveCount(1);
  await expect(page.locator('#distribution')).toContainText('Abel-Mac');
  await expect(page.locator('#distribution')).toContainText('RUNNING ON THIS COMPUTER');
  await expect(page.locator('#activity')).toContainText('Abel-Mac');
  await expect(page.getByRole('heading', {name: 'Recent jobs'})).toHaveCount(0);
  await page.locator('#activity .activity-row').click();
  await expect(page.locator('#activity-detail')).toContainText('Abel-Mac');
  await expect(page.locator('#activity-detail')).toContainText('gemma3:12b');
  await expect(page.locator('#activity-detail')).toContainText('Model revision');
  expect(errors).toEqual([]);
});

test('requires an explicit model and worker before submission', async ({page}) => {
  const {submissions, errors} = await setup(page);
  await expect(page.locator('#submit')).toBeDisabled();
  await page.locator('#model').selectOption('gemma3:12b');
  await expect(page.locator('#submit')).toBeDisabled();
  await page.getByRole('button', {name: 'Use this worker', exact: true}).first().click();
  await expect(page.locator('#selected-worker')).toContainText('Abel-Mac');
  await expect(page.locator('#submit')).toBeEnabled();
  await page.locator('#submit').click();
  await expect.poll(() => submissions.length).toBe(1);
  expect(submissions[0].target_worker_id).toBe('abel');
  expect(submissions[0].model_id).toBe('gemma3:12b');
  expect(errors).toEqual([]);
});

/* Group only registrations that share a persistent device ID. */
test('rolls repeated registrations of one computer into a single machine', async ({page}) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const live = [worker('abel-now', 'Abel-Mac', {device_id: 'abel-device'})];
  const history = [...live, worker('abel-old', 'Abel-Mac', {device_id: 'abel-device', status: 'OFFLINE'}), worker('kevin-old', 'Kevin-Mac', {status: 'OFFLINE'})];
  await page.route('https://coordinator.test/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.startsWith('/demo/')) {
      const name = url.pathname === '/demo/' ? 'index.html' : url.pathname.slice('/demo/'.length);
      const type = name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : 'text/html';
      return route.fulfill({contentType: type, body: await fs.readFile(path.join(__dirname, '..', name))});
    }
    if (url.pathname === '/api/workers') {
      return route.fulfill({json: url.searchParams.get('include_history') === 'true' ? history : live});
    }
    if (url.pathname === '/api/activity') return route.fulfill({json: {
      as_of: new Date().toISOString(), task_counts: {COMPLETED: 30}, retries: 0,
      active_tasks: [], recent_tasks: [],
      worker_metrics: [
        {worker_id: 'abel-now', completed_tasks: 12, completed_inputs: 12, average_execution_ms: 6000},
        {worker_id: 'abel-old', completed_tasks: 15, completed_inputs: 15, average_execution_ms: 8000},
        {worker_id: 'kevin-old', completed_tasks: 3, completed_inputs: 3, average_execution_ms: 4000}
      ],
      worker_task_types: [
        {worker_id: 'abel-now', task_type: 'summarization', completed_tasks: 12},
        {worker_id: 'abel-old', task_type: 'coding-assistance', completed_tasks: 15},
        {worker_id: 'kevin-old', task_type: 'summarization', completed_tasks: 3}
      ]
    }});
    return route.fulfill({json: []});
  });
  await page.goto('https://coordinator.test/demo/');
  await page.locator('#token').fill('test-only');
  await page.locator('#connect').click();

  // Two machines, not three registrations.
  await expect(page.locator('#share-legend .legend-item')).toHaveCount(2);
  await expect(page.locator('#share-legend')).toContainText('27 tasks');
  await expect(page.locator('#share-legend')).toContainText('3 tasks');
  await expect(page.locator('.donut-value')).toHaveText('30');
  await expect(page.locator('#distribution .distribution-card')).toHaveCount(2);
  await expect(page.locator('#distribution')).toContainText('2 registrations');
  await expect(page.locator('#mix-scope')).toContainText('all completed work');
  await expect(page.locator('.mix-row')).toHaveCount(2);
  expect(errors).toEqual([]);
});

/* Submitting should never be a quiet wait: the stage tracker appears immediately
   and keeps reporting where the job is. */
test('reports submission progress instead of waiting silently', async ({page}) => {
  const {errors} = await setup(page);
  await expect(page.locator('#job-stage')).toBeHidden();
  await page.locator('#model').selectOption('gemma3:12b');
  await page.getByRole('button', {name: 'Use this worker', exact: true}).first().click();
  await page.locator('#submit').click();

  await expect(page.locator('#job-stage')).toBeVisible();
  await expect(page.locator('.stage-step')).toHaveCount(4);
  // The mocked job stays QUEUED, so it settles there with Sending already behind it.
  await expect(page.locator('#job-stage')).toContainText('Queued');
  await expect(page.locator('.stage-step.stage-done .stage-name')).toHaveText(['Sending']);
  await expect(page.locator('.stage-step.stage-current .stage-name')).toHaveText(['Queued']);
  await expect(page.locator('#job-stage')).toContainText('since you submitted');
  expect(errors).toEqual([]);
});

/* The header pill is the only always-visible connection state, and the hero numbers
   come from /api/stats, which this dashboard previously never called. */
test('header reflects connection state and the hero shows coordinator totals', async ({page}) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('https://coordinator.test/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.startsWith('/demo/')) {
      const name = url.pathname === '/demo/' ? 'index.html' : url.pathname.slice('/demo/'.length);
      const type = name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : 'text/html';
      return route.fulfill({contentType: type, body: await fs.readFile(path.join(__dirname, '..', name))});
    }
    if (url.pathname === '/api/workers') return route.fulfill({json: [worker('abel', 'Abel-Mac')]});
    if (url.pathname === '/api/stats') return route.fulfill({json: {
      workers_online: 2, workers_available: 2, workers_busy: 0, jobs_queued: 0, jobs_running: 0,
      jobs_completed: 9, jobs_failed: 1, tasks_completed: 12, total_inferences: 40
    }});
    if (url.pathname === '/api/activity') return route.fulfill({json: {
      as_of: new Date().toISOString(), task_counts: {}, retries: 0,
      active_tasks: [], recent_tasks: [], worker_metrics: []
    }});
    return route.fulfill({json: []});
  });
  await page.goto('https://coordinator.test/demo/');
  await expect(page.locator('#connection')).toHaveClass(/conn-idle/);
  await expect(page.locator('#hero-stats')).toBeHidden();

  await page.locator('#token').fill('test-only');
  await page.locator('#connect').click();
  await expect(page.locator('#connection')).toHaveClass(/conn-live/);
  await expect(page.locator('#hero-stats')).toBeVisible();
  await expect(page.locator('#hero-stats')).toContainText('12');
  await expect(page.locator('#hero-stats')).toContainText('Tasks completed');
  await expect(page.locator('.connect')).toHaveClass(/is-connected/);

  await page.locator('#disconnect').click();
  await expect(page.locator('#connection')).toHaveClass(/conn-idle/);
  await expect(page.locator('#hero-stats')).toBeHidden();
  expect(errors).toEqual([]);
});

/* Make coordinator storage and the selected worker explicit. */
test('shows the data path once a machine and model are chosen', async ({page}) => {
  const {errors} = await setup(page);
  await expect(page.locator('#data-path')).toBeHidden();

  await page.locator('#model').selectOption('gemma3:12b');
  await page.getByRole('button', {name: 'Use this worker', exact: true}).first().click();
  await expect(page.locator('#data-path')).toBeVisible();
  await expect(page.locator('#path-machine')).toHaveText('Abel-Mac');
  await expect(page.locator('#path-model')).toHaveText('gemma3:12b');
  await expect(page.locator('#path-note')).toContainText('sends the task to Abel-Mac');
  await expect(page.locator('#path-note')).toContainText('coordinator stores');
  await expect(page.locator('.path-node')).toHaveCount(3);

  // Hold the request so the sending state can be observed without a timing race.
  let release;
  const held = new Promise(resolve => { release = resolve; });
  await page.route('**/api/jobs', async route => {
    await held;
    await route.fulfill({json: {job_id: 'test-job', status: 'QUEUED'}});
  });
  await page.locator('#submit').click();
  await expect(page.locator('#data-path')).toHaveClass(/path-live/);
  await expect(page.locator('#data-path')).toHaveAttribute('data-leg', 'out');
  release();
  await expect(page.locator('.stage-current .stage-name')).toHaveText('Queued');
  expect(errors).toEqual([]);
});

test('copy and download stay disabled until a result exists', async ({page}) => {
  const {errors} = await setup(page);
  await expect(page.locator('#copy-result')).toBeDisabled();
  await expect(page.locator('#download-result')).toBeDisabled();
  expect(errors).toEqual([]);
});

test('refreshes machine presence without waiting for the history cache', async ({page}) => {
  await setup(page);
  await expect(page.locator('#share-legend')).toContainText('WORKING');
  await page.route('**/api/activity', route => route.fulfill({json: {
    active_tasks: [], recent_tasks: [], worker_metrics: [{worker_id: 'abel', completed_tasks: 4, completed_inputs: 4, average_execution_ms: 1000}]
  }}));
  await page.route('**/api/workers?*', route => route.fulfill({json: [worker('abel', 'Abel-Mac', {status: 'OFFLINE'})]}));
  await expect(page.locator('#share-legend')).toContainText('OFFLINE');
});

test('freezes completed elapsed time and keeps the submitted model in the diagram', async ({page}) => {
  await page.clock.install();
  await setup(page);
  await expect(page.locator('#connection')).toBeVisible();
  await page.locator('#model').selectOption('gemma3:12b');
  await page.getByRole('button', {name: 'Use this worker', exact: true}).first().click();
  await page.route('**/api/jobs/test-job/results', route => route.fulfill({json: {
    job_id: 'test-job', status: 'COMPLETED', total_inputs: 1, completed_inputs: 1, failed_inputs: 0,
    tasks: [{status: 'COMPLETED', input_start_index: 0, worker_name: 'Abel-Mac', execution_time_ms: 1000, attempt_count: 1}],
    results: [{index: 0, text: 'A summary.'}]
  }}));
  await page.locator('#submit').click();
  await expect(page.locator('#job-stage')).toContainText('Completed');
  const elapsed = await page.locator('.stage-total').textContent();
  await page.locator('#mode').selectOption('coding-assistance');
  await page.locator('#model').selectOption('qwen2.5-coder:3b');
  await expect(page.locator('#path-model')).toHaveText('gemma3:12b');
  await page.clock.runFor(6000);
  await expect(page.locator('.stage-total')).toHaveText(elapsed);
  await page.locator('#disconnect').click();
  await expect(page.locator('#data-path')).toBeHidden();
  await page.locator('#connect').click();
  await expect(page.locator('#job-stage')).toBeHidden();
});

test('dashboard fits a narrow screen and supports reduced motion', async ({page}, testInfo) => {
  await page.setViewportSize({width: 390, height: 844});
  await page.emulateMedia({reducedMotion: 'reduce'});
  await setup(page);
  await expect(page.locator('#connection')).toBeVisible();
  await page.locator('#model').selectOption('gemma3:12b');
  await page.getByRole('button', {name: 'Use this worker', exact: true}).first().click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({path: testInfo.outputPath('dashboard-mobile.png'), fullPage: true});
  await page.setViewportSize({width: 1440, height: 1000});
  await page.screenshot({path: testInfo.outputPath('dashboard-desktop.png'), fullPage: true});
});
