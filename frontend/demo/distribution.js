/* Per-job accepted results, grouped by stable worker ID. */
window.WorkDistribution = {
  summarize(tasks, workers) {
    const rows = new Map();
    const add = (id, name) => {
      if (!rows.has(id)) rows.set(id, {id, name: name || 'Unassigned / unattributed', completed: 0,
        active: 0, queued: 0, failed: 0, inputs: 0, milliseconds: 0, timed: 0});
      return rows.get(id);
    };
    for (const task of tasks) {
      const row = add(task.worker_id, task.worker_name || task.worker_id);
      if (task.status === 'COMPLETED') {
        row.completed++; row.inputs += task.input_count;
        if (Number.isFinite(task.execution_time_ms)) { row.milliseconds += task.execution_time_ms; row.timed++; }
      } else if (['ASSIGNED', 'RUNNING'].includes(task.status)) row.active++;
      else if (task.status === 'FAILED') row.failed++;
      else row.queued++;
    }
    for (const worker of workers) if (worker.status !== 'OFFLINE') add(worker.id, worker.name);
    return [...rows.values()].sort((a, b) => b.completed - a.completed || a.name.localeCompare(b.name));
  },
  compatibility(worker, job) {
    if (!worker || !job) return 'Unavailable';
    const models = worker.models?.length ? worker.models : [worker];
    const model = models.find(m => m.model_id === job.model_id && m.model_revision === job.model_revision);
    if (!model) return 'Model / revision mismatch';
    if (!model.supported_tasks.includes(job.task_type)) return 'Task unsupported';
    return worker.status === 'OFFLINE' ? 'Compatible · offline' : 'Compatible';
  },
  render(container, job, result, workers) {
    const rows = result ? this.summarize(result.tasks, workers) : [];
    // Ignore heartbeat timestamps and memory readings: only redraw visible changes.
    const signature = JSON.stringify([job?.id, job?.model_id, job?.total_tasks, result,
      rows.map(row => [row, this.compatibility(workers.find(w => w.id === row.id), job)])]);
    if (container.dataset.signature === signature && container.childElementCount) return;
    const wasOpen = container.querySelector('details')?.open ?? false;
    container.dataset.signature = signature;
    container.replaceChildren();
    const node = (tag, text, className) => { const n = document.createElement(tag); n.textContent = text; if (className) n.className = className; return n; };
    if (!result) { container.append(node('p', 'Select a job to see how its work was shared.')); return; }
    const total = job?.total_tasks ?? result.tasks.length;
    const completed = result.tasks.filter(t => t.status === 'COMPLETED').length;
    const active = result.tasks.filter(t => ['ASSIGNED', 'RUNNING'].includes(t.status)).length;
    const failed = result.tasks.filter(t => t.status === 'FAILED').length;
    const overview = node('div', '', 'distribution-overview');
    const heading = node('div', '', 'distribution-heading');
    heading.append(node('strong', `${completed} of ${total} tasks complete`), node('span', result.status.replaceAll('_', ' ').toLowerCase(), 'dist-status'));
    overview.append(heading, node('p', job?.model_id || 'Coordinator default', 'muted'));
    const progress = document.createElement('progress'); progress.max = total || 1; progress.value = completed;
    progress.setAttribute('aria-label', 'Completed tasks'); overview.append(progress);
    overview.append(node('p', `${rows.filter(r => r.id && (r.completed || r.active)).length} participating computers · ${active} running · ${failed} failed`, 'muted'));
    container.append(overview);
    const cards = node('div', '', 'distribution-cards');
    for (const row of rows) {
      const card = node('article', '', 'distribution-card');
      const title = node('div', '', 'distribution-heading');
      title.append(node('h3', row.name), node('span', row.active ? 'Running' : row.completed ? 'Contributed' : 'No work yet', 'dist-status'));
      card.append(title);
      const identity = node('small', row.id ? `Device ${row.id.slice(0, 8)}` : 'Awaiting assignment', 'muted');
      identity.title = row.id || ''; card.append(identity);
      const share = total ? 100 * row.completed / total : 0;
      const contribution = node('div', '', 'distribution-contribution');
      contribution.append(node('strong', `${row.completed}`), node('span', `tasks completed · ${share.toFixed(1)}% of job`)); card.append(contribution);
      const bar = document.createElement('progress'); bar.max = total || 1; bar.value = row.completed;
      bar.setAttribute('aria-label', `${row.name}: ${row.completed} of ${total} tasks`); card.append(bar);
      const metrics = node('dl', '', 'distribution-metrics');
      for (const [label, value] of [['Running', row.active], ['Queued', row.queued], ['Failed', row.failed], ['Inputs completed', row.inputs],
        ['Total execution', row.timed ? `${(row.milliseconds / 1000).toFixed(2)}s` : '—'],
        ['Average / task', row.timed ? `${(row.milliseconds / row.timed / 1000).toFixed(2)}s` : '—']]) {
        const pair = node('div', ''); pair.append(node('dt', label), node('dd', value)); metrics.append(pair);
      }
      card.append(metrics, node('p', `Current model: ${this.compatibility(workers.find(w => w.id === row.id), job)}`, 'muted'));
      cards.append(card);
    }
    container.append(cards);
    const table = (headers, rows) => {
      const wrap = document.createElement('div'); wrap.className = 'distribution-table';
      const t = document.createElement('table'); const head = document.createElement('thead'); const tr = document.createElement('tr');
      for (const label of headers) { const th = node('th', label); th.scope = 'col'; tr.append(th); }
      head.append(tr); t.append(head); const body = document.createElement('tbody');
      for (const cells of rows) { const row = document.createElement('tr'); for (const value of cells) row.append(node('td', String(value))); body.append(row); }
      t.append(body); wrap.append(t); return wrap;
    };
    const details = document.createElement('details'); details.open = wasOpen;
    details.append(node('summary', 'Task-by-task assignment'));
    details.append(table(['Task', 'Computer', 'Input range', 'Status', 'Attempts', 'Execution'],
      [...result.tasks].sort((a,b) => a.input_start_index - b.input_start_index).map(task => [task.task_id.slice(0, 8),
        task.worker_name || task.worker_id || 'Unassigned / unattributed', `${task.input_start_index + 1}–${task.input_start_index + task.input_count}`,
        task.status, task.attempt_count, task.execution_time_ms == null ? '—' : `${(task.execution_time_ms / 1000).toFixed(2)}s`])));
    container.append(details);
    const note = node('p', 'Share measures completed tasks, not compute cost. Compatibility checks the advertised model and task, not current memory eligibility. Execution times count successful results; past retry owners are not retained. Offline computers appear here only when attributed to this job.');
    note.className = 'muted'; container.append(note);
  }
};
