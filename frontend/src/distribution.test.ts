import { test } from 'node:test';
import assert from 'node:assert/strict';
import { distribution, compatibility } from './distribution.ts';
import type { Results, Worker, Job } from './api.ts';
const task = (worker: string | null, index: number, status = 'COMPLETED'): Results['tasks'][number] => ({task_id: String(index), input_start_index:index, input_count:1, worker_id:worker, worker_name:worker, status, attempt_count:3, execution_time_ms:status === 'COMPLETED' ? 1000 : null});
test('8/10 versus 2/10 counts accepted completions, not three attempts per task', () => {
  const rows = distribution(Array.from({length:10},(_,i) => task(i < 8 ? 'A' : 'B', i)));
  assert.deepEqual(rows.map(r => [r.id,r.completed,r.inputs,r.milliseconds]), [['A',8,8,8000],['B',2,2,2000]]);
});
test('single-worker processing and unassigned failures remain distinct', () => {
  const rows = distribution([...Array.from({length:10},(_,i) => task('A',i)),task(null,10,'FAILED'),task('B',11,'ASSIGNED')]);
  assert.equal(rows.find(r => r.id === 'A')?.completed,10);
  assert.equal(rows.find(r => r.id === null)?.failed,1);
  assert.equal(rows.find(r => r.id === 'B')?.active,1);
  assert.equal(rows.find(r => r.id === 'B')?.milliseconds,0);
});
test('compatibility requires task support, model revision and presence', () => {
  const job = {task_type:'summarization', model_id:'model', model_revision:'v1'} as Job;
  const worker = {supported_tasks:['summarization'], model_id:'model', model_revision:'v1', status:'AVAILABLE'} as Worker;
  assert.equal(compatibility(worker,job),'Compatible, available');
  assert.equal(compatibility({...worker,supported_tasks:['coding-assistance']},job),'Task unsupported');
  assert.equal(compatibility({...worker,model_revision:'v2'},job),'Model / revision mismatch');
  assert.equal(compatibility({...worker,status:'OFFLINE'},job),'Compatible, offline');
});
