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

test('keeps explicit and automatic worker assignment working', async ({page}) => {
  const {submissions, errors} = await setup(page);
  await page.getByRole('button', {name: 'Use this worker', exact: true}).first().click();
  await expect(page.locator('#selected-worker')).toContainText('Abel-Mac');
  await page.locator('#submit').click();
  await expect.poll(() => submissions.length).toBe(1);
  expect(submissions[0].target_worker_id).toBe('abel');
  await page.locator('#automatic-worker').click();
  await page.locator('#submit').click();
  await expect.poll(() => submissions.length).toBe(2);
  expect(submissions[1]).not.toHaveProperty('target_worker_id');
  expect(errors).toEqual([]);
});
