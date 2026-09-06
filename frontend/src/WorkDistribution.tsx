import type { Job, Results, Worker } from './api';
import { compatibility, distribution } from './distribution';

export function Distribution({job, results, workers, stale}: {job: Job; results: Results; workers: Worker[]; stale: boolean}) {
  const rows = distribution(results.tasks);
  const ids = new Set(rows.map(row => row.id));
  for (const worker of workers) if (!ids.has(worker.id)) rows.push({id: worker.id, name: worker.name, completed: 0, active: 0, queued: 0, failed: 0, inputs: 0, milliseconds: 0, timed: 0});
  const completed = results.tasks.filter(task => task.status === 'COMPLETED').length;
  return <section className="panel recent"><div className="section-heading"><h2>Work distribution · this job</h2><span className="badge">{completed} / {job.total_tasks} tasks complete</span></div>
    <p className="hint">Share = tasks completed by this computer ÷ all tasks in this job. Input counts and execution time are separate measures; equal task counts do not mean equal compute cost.</p>
    {stale && <p className="notice">Connection interrupted. Counts may be stale; current compatibility is unavailable.</p>}
    <div className="table-wrap"><table><thead><tr><th>Computer</th><th>Current compatibility</th><th>Completed</th><th>Share of job</th><th>Active</th><th>Queued</th><th>Failed</th><th>Inputs completed</th><th>Execution total / average</th></tr></thead><tbody>{rows.map(row => {
      const worker = workers.find(worker => worker.id === row.id);
      return <tr key={row.id ?? 'unattributed'}><td>{row.name}<div className="hint">{row.id?.slice(0,8)}</div></td><td>{stale ? 'Unavailable' : worker ? compatibility(worker,job) : 'Not in current worker list'}</td><td>{row.completed} / {job.total_tasks}</td><td>{job.total_tasks ? (100 * row.completed / job.total_tasks).toFixed(1) : '0.0'}%</td><td>{row.active}</td><td>{row.queued}</td><td>{row.failed}</td><td>{row.inputs}</td><td>{row.timed ? `${(row.milliseconds / 1000).toFixed(2)}s / ${(row.milliseconds / row.timed / 1000).toFixed(2)}s (${row.timed} timed)` : 'Unavailable'}</td></tr>;
    })}</tbody></table></div>
    {!results.tasks.length && <p className="notice">No task attribution returned by the backend yet.</p>}
    <p className="hint">Compatibility reflects advertised task support and exact model/revision now, not at assignment time. The worker list is limited to 500 registrations. Completion counts credit the accepted result once. Past retry owners are not exposed by this API; unassigned failures cannot be attributed to a computer. Execution totals exclude failed attempts and are not wall-clock job duration.</p>
    <details><summary>Chunk-by-chunk assignment</summary><div className="table-wrap"><table><thead><tr><th>Chunk</th><th>Task ID</th><th>Input range</th><th>Computer</th><th>Status</th><th>Attempts</th><th>Execution</th></tr></thead><tbody>{[...results.tasks].sort((a,b) => a.input_start_index - b.input_start_index).map((task,index) => <tr key={task.task_id}><td>{index + 1}</td><td title={task.task_id}>{task.task_id.slice(0,8)}</td><td>{task.input_start_index + 1}–{task.input_start_index + task.input_count}</td><td>{task.worker_name ?? task.worker_id ?? 'Unassigned / unattributed'}</td><td>{task.status}</td><td>{task.attempt_count}</td><td>{task.execution_time_ms == null ? 'Unavailable' : `${task.execution_time_ms} ms`}</td></tr>)}</tbody></table></div></details>
  </section>;
}
