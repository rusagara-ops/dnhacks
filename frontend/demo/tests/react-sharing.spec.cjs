const {test, expect} = require('@playwright/test');
const path = require('node:path');
const {pathToFileURL} = require('node:url');

let server, origin;
test.beforeAll(async () => {
  const {createServer} = await import(pathToFileURL(path.join(__dirname, '../../node_modules/vite/dist/node/index.js')).href);
  server = await createServer({root: path.join(__dirname, '../..'), server: {host: '127.0.0.1', port: 0}, configFile: false});
  await server.listen(); origin = `http://127.0.0.1:${server.httpServer.address().port}`;
});
test.afterAll(async () => { await server?.close(); });

async function setup(page, kind = 'account') {
  const state = {quotes: [], submissions: [], quoteFailure: false};
  await page.route('http://coordinator.test/**', async route => {
    const request = route.request(), url = new URL(request.url());
    if (request.method() === 'OPTIONS') return route.fulfill({headers: {'access-control-allow-origin': origin, 'access-control-allow-headers': 'authorization,content-type', 'access-control-allow-methods': 'GET,POST,OPTIONS'}});
    const fulfill = (json, status = 200) => route.fulfill({status, headers: {'access-control-allow-origin': origin}, json});
    if (url.pathname === '/health' || url.pathname === '/ready') return fulfill({status: 'ok'});
    if (url.pathname === '/api/me') return fulfill({auth_mode: 'controlled', credential_kind: kind, role: 'admin', account_id: 'account-one', name: 'Kevin'});
    if (url.pathname === '/api/credits/quote') { state.quotes.push(request.postDataJSON()); return state.quoteFailure ? fulfill({detail: 'Quote temporarily unavailable'}, 503) : fulfill({credits: request.postDataJSON().inputs.length, total_inputs: request.postDataJSON().inputs.length, unit: 'demo credits', pricing_version: 'demo-v1'}); }
    if (url.pathname === '/api/jobs' && request.method() === 'POST') { state.submissions.push(request.postDataJSON()); return fulfill({job_id: 'job-one'}); }
    if (url.pathname === '/api/jobs' || url.pathname === '/api/workers') return fulfill([]);
    if (url.pathname === '/api/activity') return fulfill({as_of: '2026-09-06T00:00:00Z', active_tasks: [], recent_tasks: [], task_counts: {}, retries: 0, worker_metrics: []});
    if (url.pathname.endsWith('/results')) return fulfill({job_id: 'job-one', is_final: false, status: 'QUEUED', completed_inputs: 0, failed_inputs: 0, total_inputs: 2, tasks: [], results: [], failed_tasks: []});
    return fulfill({id: 'job-one', task_type: 'summarization', status: 'QUEUED', total_inputs: 2, total_tasks: 2, completed_tasks: 0, failed_tasks: 0, progress_percentage: 0, model_id: 'test-model', created_at: '2026-09-06T00:00:00Z'});
  });
  await page.goto(origin);
  await page.getByLabel('Backend URL', {exact: true}).fill('http://coordinator.test');
  await page.getByLabel('Account or demo token', {exact: true}).fill('test-account-token');
  await page.getByRole('button', {name: 'Connect', exact: true}).click();
  return state;
}

test('React jobs require a fresh explicit credit confirmation and account credentials are not remembered', async ({page}) => {
  const state = await setup(page);
  await expect(page.getByRole('button', {name: 'Disconnect and forget token'})).toBeVisible();
  await page.getByLabel('Source document', {exact: true}).fill('First document.');
  await page.getByRole('button', {name: 'Review demo credit cost →'}).click();
  await expect(page.getByRole('button', {name: 'Reserve 1 credits and submit →'})).toBeVisible();
  expect(state.submissions).toHaveLength(0);
  await page.getByLabel('Split into independent sections', {exact: true}).check();
  await page.getByLabel('Source document', {exact: true}).fill('First document.\n---\nSecond document.');
  await expect(page.getByRole('button', {name: 'Review demo credit cost →'})).toBeVisible();
  state.quoteFailure = true;
  await page.getByRole('button', {name: 'Review demo credit cost →'}).click();
  await expect(page.getByRole('alert')).toContainText('Quote temporarily unavailable');
  await expect(page.getByRole('button', {name: 'I checked recent jobs — allow another submission'})).toHaveCount(0);
  state.quoteFailure = false;
  await page.getByRole('button', {name: 'Review demo credit cost →'}).click();
  await page.getByRole('button', {name: 'Reserve 2 credits and submit →'}).click();
  await expect.poll(() => state.submissions.length).toBe(1);
  expect(state.submissions[0].inputs).toEqual(['First document.', 'Second document.']);
  expect(await page.evaluate(() => sessionStorage.getItem('sc-connection'))).toBeNull();
});

test('React setup credentials direct the operator to enrollment without loading jobs', async ({page}) => {
  await setup(page, 'bootstrap');
  await expect(page.getByRole('alert')).toContainText('create an administrator account');
  await expect(page.getByRole('link', {name: 'Sharing and credits ↗'})).toHaveAttribute('href', 'http://coordinator.test/demo/sharing.html');
  await expect(page.getByRole('button', {name: 'Disconnect and forget token'})).toHaveCount(0);
});
