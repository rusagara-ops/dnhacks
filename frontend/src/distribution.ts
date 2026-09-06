import type { Job, Results, Worker } from './api';

export function distribution(tasks: Results['tasks']) {
  const rows = new Map<string, {id: string | null; name: string; completed: number; active: number; queued: number; failed: number; inputs: number; milliseconds: number; timed: number}>();
  for (const task of tasks) {
    const key = task.worker_id ?? 'unattributed';
    const row = rows.get(key) ?? {id: task.worker_id, name: task.worker_name ?? (task.worker_id ? 'Unknown worker' : 'Unassigned / unattributed'), completed: 0, active: 0, queued: 0, failed: 0, inputs: 0, milliseconds: 0, timed: 0};
    if (task.status === 'COMPLETED') {
      row.completed++; row.inputs += task.input_count;
      if (task.execution_time_ms != null) { row.milliseconds += task.execution_time_ms; row.timed++; }
    } else if (['ASSIGNED', 'RUNNING'].includes(task.status)) row.active++;
    else if (task.status === 'FAILED') row.failed++;
    else row.queued++;
    rows.set(key, row);
  }
  return [...rows.values()].sort((a,b) => b.completed - a.completed || a.name.localeCompare(b.name));
}

export function compatibility(worker: Worker, job: Job) {
  if (!worker.supported_tasks.includes(job.task_type)) return 'Task unsupported';
  if (!job.model_id || !job.model_revision) return 'Job model unconfigured';
  if (worker.model_id !== job.model_id || worker.model_revision !== job.model_revision) return 'Model / revision mismatch';
  if (worker.status === 'OFFLINE') return 'Compatible, offline';
  if (worker.status === 'BUSY') return 'Compatible, busy';
  return 'Compatible, available';
}
