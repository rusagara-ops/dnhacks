const {test, expect} = require('@playwright/test');
const fs = require('node:fs/promises');
const path = require('node:path');

async function setup(page, {kind = 'account', role = 'admin', mode = 'controlled'} = {}) {
  const calls = [], errors = [], accountId = '11111111-1111-4111-8111-111111111111';
  const state = {failGrant: false, policy: null, credentials: [], accounts: [{id: accountId, name: 'Kevin', role: 'admin', enabled: true}], recovered: false};
  page.on('pageerror', error => errors.push(error.message));
  await page.route('https://coordinator.test/**', async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.pathname.startsWith('/demo/')) {
      const name = url.pathname.slice('/demo/'.length), type = name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : 'text/html';
      return route.fulfill({contentType: type, body: await fs.readFile(path.join(__dirname, '..', name))});
    }
    const body = request.method() === 'POST' ? request.postDataJSON() : null;
    calls.push({path: url.pathname, body, method: request.method(), authorization: request.headers().authorization});
    if (url.pathname === '/api/me') return route.fulfill({json: {account_id: kind === 'account' ? accountId : null, name: 'Kevin', role, auth_mode: mode, credential_kind: kind}});
    if (url.pathname === '/api/provider/workers') return route.fulfill({json: {auth_mode: mode, items: [{worker_id: 'worker-one', name: 'Kevin Mac', ram_gb: 8,
      accepting_new_tasks: false, admission_reasons: ['SHARING_PAUSED'], policy: {sharing_enabled: false, allowed_task_types: ['coding-assistance'], max_concurrent_tasks: 1, min_ram_available_gb: 1, availability: []},
      reliability: {completed_tasks: 8, failed_attempts: 1, expired_attempts: 2, observed_attempts: 11, average_reported_execution_ms: 1200, scope: 'since_tracking'}}]}});
    if (url.pathname.endsWith('/policy')) { state.policy = body; return route.fulfill({json: {ok: true}}); }
    if (url.pathname === '/api/credits') return route.fulfill({json: {account_id: accountId, available: 20, reserved: 3, lifetime_earned: 8, unit: 'demo credits', pricing_version: 'demo-v1', entries: [{id: 'entry', kind: 'GRANT', available_delta: 20, reserved_delta: 0, job_id: null, task_id: null, created_at: '2026-09-06T00:00:00Z'}], total_entries: 1}});
    if (/^\/api\/accounts\/[^/]+\/credentials$/.test(url.pathname)) {
      const credential = {id: 'replacement-account-token', account_id: accountId, kind: 'account', device_id: null, label: 'Replacement account access', created_at: '2026-09-06T00:00:00Z', revoked_at: null};
      if (body) { state.recovered = true; return route.fulfill({json: {credential, token: 'one-time-replacement-test-token'}}); }
      return route.fulfill({json: state.recovered ? [credential] : []});
    }
    if (url.pathname === '/api/credentials' && body) {
      const credential = {id: 'credential-one', account_id: accountId, kind: 'worker', ...body, created_at: '2026-09-06T00:00:00Z', revoked_at: null}; state.credentials.push(credential);
      return route.fulfill({json: {credential, token: 'one-time-worker-test-token'}});
    }
    if (url.pathname.endsWith('/revoke')) { state.credentials[0].revoked_at = '2026-09-06T01:00:00Z'; return route.fulfill({json: state.credentials[0]}); }
    if (url.pathname === '/api/credentials') return route.fulfill({json: state.credentials});
    if (url.pathname === '/api/accounts' && body) { const account = {id: 'created-account', ...body, enabled: true}; state.accounts.push(account); return route.fulfill({json: {account, token: 'one-time-account-test-token'}}); }
    if (url.pathname === '/api/accounts') return route.fulfill({json: state.accounts});
    if (url.pathname === '/api/credits/grants') return state.failGrant ? route.abort('failed') : route.fulfill({json: {available: 40}});
    if (url.pathname.endsWith('/enroll')) return route.fulfill({json: {worker_id: 'worker-one', owner_account_id: accountId}});
    return route.fulfill({status: 404, json: {detail: 'Not Found'}});
  });
  await page.goto('https://coordinator.test/demo/sharing.html');
  await page.getByLabel('Account token', {exact: true}).fill('private-test-account');
  await page.getByRole('button', {name: 'Connect', exact: true}).click();
  return {calls, errors, state};
}

test('provider can pause, limit workloads and save UTC windows; invalid overnight range is rejected', async ({page}) => {
  await page.setViewportSize({width: 1440, height: 1000});
  const {calls, errors, state} = await setup(page);
  await expect(page.locator('#available')).toHaveText('20');
  await expect(page.locator('.provider-card')).toContainText('Accepted tasks: 8');
  await page.getByLabel('Share this machine').check();
  await page.getByLabel('Summaries', {exact: true}).check();
  await page.getByLabel('Maximum active tasks').fill('2');
  await page.getByRole('button', {name: 'Add availability window'}).click();
  await page.getByLabel('Start (UTC)').fill('22:00');
  await page.getByLabel('End (UTC)').fill('06:00');
  await page.getByRole('button', {name: 'Save sharing settings'}).click();
  await expect(page.locator('.policy-form [role=status]')).toContainText('Split overnight');
  expect(state.policy).toBeNull();
  await page.getByLabel('End (UTC)').fill('24:00');
  await page.getByRole('button', {name: 'Save sharing settings'}).click();
  await expect(page.locator('.policy-form [role=status]')).toContainText('Saved');
  expect(state.policy).toEqual({sharing_enabled: true, allowed_task_types: ['summarization', 'coding-assistance'], max_concurrent_tasks: 2, min_ram_available_gb: 1, availability: [{days: [0,1,2,3,4], start_minute: 1320, end_minute: 1440}]});
  expect(calls.filter(call => call.path.endsWith('/policy'))).toHaveLength(1);
  await page.screenshot({path: '/private/tmp/dnhacks-sharing-desktop.png', fullPage: true});
  expect(errors).toEqual([]);
});

test('one-time worker keys stay masked and out of storage; revoke requires a second click and disconnect clears secrets', async ({page}) => {
  const {calls, errors} = await setup(page, {role: 'member'});
  await expect(page.locator('#admin-panel')).toBeHidden();
  await page.getByLabel('Installation ID', {exact: true}).fill('22222222-2222-4222-8222-222222222222');
  await page.getByLabel('Label', {exact: true}).fill('My Mac');
  await page.getByRole('button', {name: 'Create worker credential'}).click();
  await expect(page.locator('#new-token')).toHaveValue('one-time-worker-test-token');
  await expect(page.locator('#new-token')).toHaveAttribute('type', 'password');
  expect(await page.evaluate(() => ({local: {...localStorage}, session: {...sessionStorage}}))).toEqual({local: {}, session: {}});
  await page.getByRole('button', {name: 'Reveal token', exact: true}).click();
  await expect(page.locator('#new-token')).toHaveAttribute('type', 'text');
  await page.getByRole('button', {name: 'Revoke My Mac'}).click();
  expect(calls.some(call => call.path.endsWith('/revoke'))).toBe(false);
  await page.getByRole('button', {name: 'Revoke My Mac'}).click();
  await expect(page.locator('#credentials')).toContainText('Revoked');
  await page.getByRole('button', {name: 'Disconnect and clear'}).click();
  await expect(page.locator('#new-token')).toHaveValue('');
  await expect(page.locator('#dashboard')).toBeHidden();
  expect(errors).toEqual([]);
});

test('bootstrap enrolls first admin without making forbidden workload reads', async ({page}) => {
  const {calls, errors} = await setup(page, {kind: 'bootstrap'});
  await expect(page.locator('#mode-message')).toContainText('Setup access only');
  await expect(page.locator('#wallet-panel')).toBeHidden();
  await expect(page.locator('#providers-panel')).toBeHidden();
  await page.getByLabel('Account name', {exact: true}).fill('Abel');
  await page.getByRole('button', {name: 'Create account', exact: true}).click();
  await expect(page.locator('#new-token')).toHaveValue('one-time-account-test-token');
  expect(calls.every(call => ['/api/me', '/api/accounts'].includes(call.path))).toBe(true);
  expect(calls.find(call => call.path === '/api/accounts' && call.body).body).toEqual({name: 'Abel', role: 'admin'});
  expect(errors).toEqual([]);
});

test('uncertain credit grant retries reuse a request ID and mobile layout fits', async ({page}) => {
  await page.setViewportSize({width: 390, height: 844});
  const {calls, state, errors} = await setup(page);
  state.failGrant = true;
  await page.getByRole('button', {name: 'Grant demo credits', exact: true}).click();
  await expect(page.locator('#grant-message')).not.toBeEmpty();
  state.failGrant = false;
  await page.getByRole('button', {name: 'Grant demo credits', exact: true}).click();
  await expect(page.locator('#grant-message')).toContainText('Demo credits granted');
  const grants = calls.filter(call => call.path === '/api/credits/grants');
  expect(grants).toHaveLength(2); expect(grants[0].body.request_id).toBe(grants[1].body.request_id);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({path: '/private/tmp/dnhacks-sharing-mobile.png', fullPage: true});
  expect(errors).toEqual([]);
});

test('demo mode keeps provider controls available and labels unmetered behavior', async ({page}) => {
  const {calls, errors} = await setup(page, {kind: 'demo', mode: 'demo'});
  await expect(page.locator('#mode-message')).toContainText('existing jobs remain unmetered');
  await expect(page.locator('.provider-card')).toHaveCount(1);
  await expect(page.locator('#wallet-panel')).toBeHidden();
  expect(calls.every(call => ['/api/me', '/api/provider/workers'].includes(call.path))).toBe(true);
  expect(errors).toEqual([]);
});

test('administrator recovery issues a token for the same account without automatically revoking old access', async ({page}) => {
  const {calls, errors} = await setup(page);
  await page.getByRole('button', {name: 'Issue replacement token for Kevin'}).click();
  await expect(page.locator('#new-token')).toHaveValue('one-time-replacement-test-token');
  await expect(page.locator('#new-token')).toHaveAttribute('type', 'password');
  await expect(page.locator('#secret-description')).toContainText('Existing tokens remain active until explicitly revoked');
  expect(calls.some(call => call.path.endsWith('/revoke'))).toBe(false);
  expect(calls.some(call => call.path === '/api/accounts' && call.method === 'POST')).toBe(false);
  await expect(page.locator('#available')).toHaveText('20');
  expect(errors).toEqual([]);
});
