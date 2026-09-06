const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const context = {window: {}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', 'telemetry.js'), 'utf8'), context);
const {machines, hasFullTypeHistory} = context.window.Telemetry;
const metric = (id, count, time = 1000) => ({worker_id: id, completed_tasks: count, completed_inputs: count, average_execution_ms: time});

test('identical display names and hostnames do not merge distinct device IDs', () => {
  const workers = ['one', 'two'].map(id => ({id, device_id: id, name: 'Shared name', hostname: 'Mac', status: 'AVAILABLE'}));
  const rows = machines({worker_metrics: [metric('one', 2), metric('two', 3)]}, workers);
  assert.equal(rows.length, 2);
  assert.notEqual(rows[0].name, rows[1].name);
  assert.equal(rows[0].completedTasks, 3);
  assert.equal(rows[1].completedTasks, 2);
});

test('known device identity combines history and weights average by completed tasks', () => {
  const workers = ['old', 'new'].map(id => ({id, device_id: 'device', name: 'Mac', status: id === 'new' ? 'AVAILABLE' : 'OFFLINE'}));
  const rows = machines({worker_metrics: [metric('old', 3, 2000), metric('new', 1, 4000)]}, workers);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].completedTasks, 4);
  assert.equal(rows[0].averageExecutionMs, 2500);
  assert.equal(rows[0].registrations, 2);
  assert.equal(rows[0].online, true);
});

test('missing history and legacy IDs stay separate even when names match', () => {
  const rows = machines({worker_metrics: [metric('missing-a', 1), metric('missing-b', 2), metric('legacy-a', 3), metric('legacy-b', 4)]}, [
    {id: 'legacy-a', name: 'Mac', hostname: 'same'}, {id: 'legacy-b', name: 'Mac', hostname: 'same'}
  ]);
  assert.equal(rows.length, 4);
  assert.equal(rows.reduce((sum, row) => sum + row.completedTasks, 0), 10);
  assert.ok(rows.every(row => !row.online));
});

test('an empty full-history response does not fall back to recent task counts', () => {
  const activity = {worker_task_types: [], recent_tasks: [{task_id: 'task', worker_id: 'one', status: 'COMPLETED', task_type: 'summarization'}]};
  assert.equal(hasFullTypeHistory(activity), true);
  assert.equal(machines(activity, [])[0].byType.size, 0);
  delete activity.worker_task_types;
  assert.equal(hasFullTypeHistory(activity), false);
  assert.equal(machines(activity, [])[0].byType.get('summarization'), 1);
});
