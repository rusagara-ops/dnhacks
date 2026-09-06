const $ = id => document.getElementById(id);
let token = '', jobId = null, connected = false, polling = false, jobMode = 'summarization';
let connectionGeneration = 0, latestResult = null, latestWorkers = [], submitting = false;
let selectedWorkerId = '';
let selectedActivityTaskId = '';

const example = `The city library is launching a three-month pilot to make its services easier to access. Starting in October, weekday closing time will move from 6 p.m. to 9 p.m. The change follows requests from residents who work during the day and need a quiet place to study in the evening.

The pilot will also introduce a free digital skills workshop every Tuesday evening. Library staff will help participants use online job applications, create a basic resume, and access public services. Twelve computers will be available, and residents can reserve a place by phone or at the front desk.

The city has allocated $18,000 for additional staffing during the pilot. Library managers will track evening attendance, workshop participation, and operating costs. At the end of the three months, they will present the findings to the city council, which will decide whether to continue the extended hours.`;
const modes = {
  summarization: ['Summarize document →', 'One coherent summary of your entire document.'],
  'document-qa': ['Ask question →', 'Answer a question using only the supplied document.'],
  'information-extraction': ['Extract details →', 'Find names, dates, amounts, and action items in labeled fields.'],
  'coding-assistance': ['Get code help →', 'Explain code or suggest a fix. Suggestions are displayed, never executed.']
};

function updateMode() {
  const mode = $('mode').value;
  const coding = mode === 'coding-assistance';
  $('submit').textContent = modes[mode][0];
  $('mode-help').textContent = modes[mode][1];
  $('source-title').textContent = coding ? 'Code snippet' : 'Source document';
  $('source-label').textContent = coding ? 'Paste code to explain or debug.' : 'Paste the entire English document, including all its paragraphs.';
  $('inputs').placeholder = coding ? 'Paste your code here…' : 'Paste an English document here…';
  $('instruction-field').hidden = !['document-qa', 'coding-assistance'].includes(mode);
  $('instruction-label').textContent = coding ? 'What should we explain or fix? (optional)' : 'Question (required)';
}
$('mode').onchange = () => {
  updateMode();
  selectedWorkerId = '';
  $('model').value = '';
  renderModels();
  renderWorkerPicker(latestWorkers);
};
$('model').onchange = () => {
  renderModels();
  renderWorkerPicker(latestWorkers);
};
function samples() {
  const mode = $('mode').value;
  $('inputs').value = mode === 'coding-assistance' ? 'def average(values):\n    return sum(values) / len(values)\n\nprint(average([]))' : example;
  $('instruction').value = mode === 'document-qa' ? 'What is the staffing budget, and who decides whether the pilot continues?' : mode === 'coding-assistance' ? 'Why does this fail for an empty list? Suggest a fix.' : '';
}
samples();
updateMode();
$('sample').onclick = samples;
const gib = value => Number.isFinite(value) ? `${value.toFixed(1)} GiB` : 'Not reported';
function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
async function api(path, body) {
  const response = await fetch('/api' + path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  if (!response.ok) {
    const details = await response.json().catch(() => ({}));
    const error = Error(response.status === 401 ? 'Invalid API token.' : typeof details.detail === 'string' ? details.detail : `Coordinator request failed (${response.status}).`);
    error.status = response.status;
    throw error;
  }
  return response.json();
}
function metric(card, label, value) {
  const row = el('div', undefined, 'metric');
  row.append(el('span', label), el('strong', value));
  card.append(row);
}
function workerModels(worker) {
  return worker.models?.length ? worker.models : worker.model_id ? [{
    model_id: worker.model_id, model_revision: worker.model_revision, supported_tasks: worker.supported_tasks || []
  }] : [];
}
function uniqueWorkers(workers) {
  const modernHosts = new Set(workers.filter(w => w.device_id).map(w => w.hostname));
  const selected = new Map();
  for (const worker of workers) {
    const w = worker;
    if (!w.device_id && modernHosts.has(w.hostname) && w.status === 'OFFLINE') continue;
    const key = w.device_id || `legacy:${w.hostname}`;
    const previous = selected.get(key);
    if (!previous || (previous.status === 'OFFLINE' && w.status !== 'OFFLINE')) selected.set(key, w);
  }
  return [...selected.values()];
}
function activeWorkers(workers) {
  return uniqueWorkers(workers).filter(worker => worker.status !== 'OFFLINE');
}
function workerSupports(worker, mode, modelId = '') {
  return workerModels(worker).some(model => model.supported_tasks.includes(mode) && (!modelId || model.model_id === modelId));
}
function renderModels() {
  const select = $('model'), previous = select.value, mode = $('mode').value;
  const choices = new Map();
  for (const worker of uniqueWorkers(latestWorkers)) {
    if (selectedWorkerId && selectedWorkerId !== worker.id) continue;
    for (const model of workerModels(worker)) {
      if (!model.supported_tasks.includes(mode)) continue;
      if (!choices.has(model.model_id)) choices.set(model.model_id, []);
      if (worker.status !== 'OFFLINE') choices.get(model.model_id).push(worker.name);
    }
  }
  select.replaceChildren(el('option', 'Select a model'));
  select.firstChild.value = '';
  for (const [id, names] of choices) {
    const option = el('option', `${id} — ${names.length ? [...new Set(names)].join(', ') : 'No worker online'}`);
    option.value = id; option.disabled = !names.length; select.append(option);
  }
  if (previous && !choices.has(previous)) {
    const missing = el('option', `${previous} — Unavailable for this selection`);
    missing.value = previous; missing.disabled = true; select.append(missing);
  }
  select.value = previous;
  select.disabled = !connected;
  const available = !!previous && !!choices.get(previous)?.length;
  $('model-help').textContent = !connected ? 'Connect to see available models.' : !available
    ? 'Choose a model advertised by the selected active machine.'
    : 'Your job will use this exact model on the selected machine.';
  $('submit').disabled = !connected || submitting || !available || !selectedWorkerId;
}
function renderWorkerPicker(workers) {
  const list = $('worker-picker');
  const mode = $('mode').value;
  const modelId = $('model').value;
  const relevant = activeWorkers(workers).filter(w => workerSupports(w, mode, modelId));
  const online = relevant.filter(w => w.status !== 'OFFLINE').length;
  $('workers-match').textContent = connected ? `${online} online · ${relevant.length} compatible` : 'Connect to see workers';
  list.replaceChildren();
  for (const worker of relevant) {
    const onlineNow = true;
    const selected = selectedWorkerId === worker.id;
    const card = el('article', undefined, `picker-card${selected ? ' selected' : ''}`);
    const header = el('div', undefined, 'picker-card-header');
    header.append(el('strong', worker.name), el('span', worker.status, `badge ${onlineNow ? 'available' : 'offline'}`));
    card.append(header);
    card.append(el('p', workerModels(worker).map(m => m.model_id).join(' · ') || 'Model not reported', 'picker-model'));
    const details = el('div', undefined, 'picker-details');
    details.append(el('span', `RAM ${gib(worker.ram_available_gb)} free`));
    details.append(el('span', worker.gpu || 'GPU not reported'));
    card.append(details);
    const button = el('button', selected ? 'Selected worker' : 'Use this worker', selected ? 'subtle selected-button' : 'subtle');
    button.disabled = !onlineNow;
    button.setAttribute('aria-pressed', String(selected));
    button.onclick = () => {
      selectedWorkerId = selected ? '' : worker.id;
      renderModels();
      renderWorkerPicker(latestWorkers);
    };
    card.append(button);
    list.append(card);
  }
  if (!relevant.length) list.append(el('p', connected ? 'No online worker supports this task and model.' : 'Connect to see available compute.', 'empty'));
  $('selected-worker').textContent = selectedWorkerId
    ? `Selected: ${relevant.find(w => w.id === selectedWorkerId)?.name || selectedWorkerId.slice(0, 8)}. This job runs on this machine.`
    : 'Choose an active machine above before submitting.';
}
function renderWorkers(workers, activity) {
  const candidates = activeWorkers(workers).filter(w => workerModels(w).some(m => m.supported_tasks.some(t => t in modes)));
  $('workers').replaceChildren();
  for (const w of candidates) {
    const card = el('article', undefined, 'worker');
    const online = true;
    const shared = w.gpu_memory_kind === 'unified';
    card.append(el('strong', w.name), el('span', w.status, 'badge'));
    const tasks = activity.active_tasks.filter(t => t.worker_id === w.id);
    const metrics = activity.worker_metrics.find(m => m.worker_id === w.id);
    metric(card, 'Current task', tasks.length ? tasks.map(t => `${t.task_type} · ${t.elapsed_seconds}s`).join(', ') : online ? 'Idle' : 'Offline');
    for (const task of tasks) {
      const link = el('button', `View job ${task.job_id.slice(0, 8)}`, 'subtle');
      link.onclick = () => openJob(task.job_id, task.task_type); card.append(link);
    }
    metric(card, 'Completed tasks', String(metrics?.completed_tasks || 0));
    metric(card, 'Average execution', metrics ? `${(metrics.average_execution_ms / 1000).toFixed(1)}s` : 'No completed tasks');
    metric(card, 'CPU usage', online && Number.isFinite(w.cpu_utilization) ? `${w.cpu_utilization.toFixed(1)}%` : 'Unavailable');
    metric(card, 'RAM usage', online && Number.isFinite(w.memory_utilization) ? `${w.memory_utilization.toFixed(1)}%` : 'Unavailable');
    metric(card, 'Total RAM', gib(w.ram_gb));
    metric(card, 'Available RAM', online ? gib(w.ram_available_gb) : 'Offline — unavailable');
    metric(card, 'Total GPU', `${w.gpu || 'Not reported'}${w.gpu_core_count ? ` · ${w.gpu_core_count} cores` : ''}`);
    metric(card, 'GPU memory', shared ? `Shares ${gib(w.ram_gb)} system RAM` : gib(w.gpu_memory_gb));
    metric(card, 'Available GPU memory', !online ? 'Offline — unavailable' : shared ? `${gib(w.ram_available_gb)} available in shared RAM*` : gib(w.gpu_available_gb));
    metric(card, 'Ollama GPU allocation', online ? gib(w.gpu_model_memory_gb) : 'Offline — unavailable');
    card.append(el('small', workerModels(w).map(m => m.model_id).join(' · ') || 'No model'));
    if (shared) card.append(el('small', '*System memory estimate, not a guaranteed GPU allocation budget. No separate GPU RAM pool.'));
    $('workers').append(card);
  }
  if (!candidates.length) $('workers').append(el('p', 'No active workers available. Start or reconnect a compatible worker.'));
  $('online').textContent = `${candidates.length} active`;
}
function renderResults(data) {
  latestResult = data; $('download-result').disabled = false;
  $('status').textContent = data.status;
  $('progress').max = data.total_inputs;
  $('progress').value = data.completed_inputs + data.failed_inputs;
  $('job').textContent = `Job ${jobId} · ${data.completed_inputs}/${data.total_inputs} documents complete`;
  $('results').replaceChildren();
  if (data.status === 'FAILED') $('results').append(el('p', 'This job failed. Any results shown are partial.', 'failure'));
  for (const task of data.tasks) {
    const card = el('article', undefined, 'result');
    const result = data.results.find(r => r.index === task.input_start_index);
    card.append(el('small', `DOCUMENT ${task.input_start_index + 1} · ${task.status}`));
    if (result && 'names' in result) {
      for (const [key, label] of Object.entries({names: 'Names', dates: 'Dates', amounts: 'Amounts', action_items: 'Action items'})) {
        card.append(el('h3', label));
        const list = el('ul');
        for (const value of result[key]) list.append(el('li', value));
        if (!result[key].length) list.append(el('li', 'Not found in source'));
        card.append(list);
      }
    } else card.append(el(jobMode === 'coding-assistance' ? 'pre' : 'p', result?.text || (task.status === 'FAILED' ? 'Task failed after retries.' : 'Waiting for the result…')));
    card.append(el('small', `${task.worker_name || 'Unassigned'}${task.execution_time_ms !== null ? ' · ' + (task.execution_time_ms / 1000).toFixed(1) + 's' : ''} · attempt ${task.attempt_count}`));
    if (task.inference_metrics) {
      const m = task.inference_metrics;
      card.append(el('small', `Prompt tokens: ${m.prompt_tokens ?? 'unknown'} · Output tokens: ${m.output_tokens ?? 'unknown'} · Generation: ${m.generation_duration_ms === null ? 'unknown' : (m.generation_duration_ms / 1000).toFixed(2) + 's'} · ${m.tokens_per_second ?? 'unknown'} tokens/s`));
    }
    $('results').append(card);
  }
}
async function openJob(id, mode) {
  jobId = id; jobMode = mode; $('result-title').textContent = mode;
  try { const result = await api(`/jobs/${id}/results`); if (connected && jobId === id) renderResults(result); }
  catch (error) { $('error').textContent = error.message; }
}
function formatTaskType(value) {
  return String(value || 'Task').replace(/[-_]/g, ' ').replace(/\b\w/g, letter => letter.toUpperCase());
}
function formatWhen(value) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString();
}
function formatDuration(seconds) {
  return Number.isFinite(seconds) ? `${seconds.toFixed(1)}s` : '—';
}
function formatExecution(task) {
  return Number.isFinite(task.execution_time_ms) ? `${(task.execution_time_ms / 1000).toFixed(2)}s measured` : `${formatDuration(task.elapsed_seconds)} wall time`;
}
function detailRow(label, value) {
  const row = el('div', undefined, 'activity-detail-row');
  row.append(el('dt', label), el('dd', value == null || value === '' ? '—' : String(value)));
  return row;
}
function showActivityDetail(task) {
  selectedActivityTaskId = task.task_id;
  const panel = $('activity-detail');
  panel.replaceChildren();
  const heading = el('div', undefined, 'activity-detail-heading');
  const title = el('div');
  title.append(el('p', 'TASK DETAILS', 'eyebrow'), el('h3', formatTaskType(task.task_type)));
  heading.append(title, el('span', task.status, `badge activity-status-${String(task.status || '').toLowerCase()}`));
  panel.append(heading);
  panel.append(el('p', `${task.worker_name || 'Waiting for a worker'} · ${task.model_id || 'Coordinator default'}`, 'activity-detail-summary'));
  const grid = el('dl', undefined, 'activity-detail-grid');
  const inputStart = Number.isInteger(task.start_index) ? task.start_index + 1 : null;
  const inputEnd = inputStart !== null && Number.isInteger(task.input_count) ? inputStart + task.input_count - 1 : null;
  grid.append(
    detailRow('Computer', task.worker_name || 'Unassigned'),
    detailRow('Worker ID', task.worker_id || '—'),
    detailRow('Model', task.model_id || 'Coordinator default'),
    detailRow('Model revision', task.model_revision || '—'),
    detailRow('Task', formatTaskType(task.task_type)),
    detailRow('Input range', inputStart === null ? '—' : `${inputStart}${inputEnd === inputStart ? '' : `–${inputEnd}`}`),
    detailRow('Queue time', formatDuration(task.queue_seconds)),
    detailRow('Execution', formatExecution(task)),
    detailRow('Attempts', task.attempt_count),
    detailRow('Created', formatWhen(task.created_at)),
    detailRow('Started', formatWhen(task.started_at)),
    detailRow('Completed', formatWhen(task.completed_at)),
    detailRow('Job ID', task.job_id),
    detailRow('Task ID', task.task_id)
  );
  panel.append(grid);
  if (task.error_code) panel.append(el('p', `Failure code: ${task.error_code}`, 'failure'));
  if (task.inference_metrics) {
    const metrics = task.inference_metrics;
    const generation = Number.isFinite(metrics.generation_duration_ms) ? `${(metrics.generation_duration_ms / 1000).toFixed(2)}s` : '—';
    const rate = metrics.output_tokens && metrics.generation_duration_ms ? ` · ${(metrics.output_tokens * 1000 / metrics.generation_duration_ms).toFixed(1)} tokens/s` : '';
    panel.append(el('p', `Prompt tokens ${metrics.prompt_tokens ?? '—'} · Output tokens ${metrics.output_tokens ?? '—'} · Generation ${generation}${rate}`, 'activity-detail-metrics'));
  }
  const open = el('button', 'Open full job results', 'subtle');
  open.type = 'button'; open.onclick = () => openJob(task.job_id, task.task_type);
  panel.append(open);
  panel.hidden = false;
}
function renderActivity(data, workers) {
  const counts = data.task_counts || {};
  const cards = {
    Queued: counts.QUEUED || 0,
    Active: (counts.RUNNING || 0) + (counts.ASSIGNED || 0),
    Completed: counts.COMPLETED || 0,
    Failed: counts.FAILED || 0,
    Retries: data.retries || 0
  };
  $('overview').replaceChildren();
  for (const [label, value] of Object.entries(cards)) {
    const card = el('article', undefined, `telemetry-card telemetry-${label.toLowerCase()}`);
    card.append(el('strong', String(value)), el('span', label));
    $('overview').append(card);
  }
  $('activity-updated').textContent = data.as_of ? `Updated ${new Date(data.as_of).toLocaleTimeString()}` : 'Live coordinator data';

  const activeByWorker = new Map();
  for (const task of data.active_tasks || []) {
    if (!activeByWorker.has(task.worker_id)) activeByWorker.set(task.worker_id, []);
    activeByWorker.get(task.worker_id).push(task);
  }
  const recentByWorker = new Map();
  for (const task of data.recent_tasks || []) {
    if (task.worker_id) {
      if (!recentByWorker.has(task.worker_id)) recentByWorker.set(task.worker_id, []);
      recentByWorker.get(task.worker_id).push(task);
    }
  }
  const metricsByWorker = new Map((data.worker_metrics || []).map(item => [item.worker_id, item]));
  const distribution = $('distribution');
  distribution.replaceChildren();
  const workerRows = uniqueWorkers(workers).filter(worker => activeByWorker.has(worker.id) || recentByWorker.has(worker.id) || metricsByWorker.has(worker.id));
  for (const worker of workerRows) {
    const active = activeByWorker.get(worker.id) || [];
    const recent = recentByWorker.get(worker.id) || [];
    const metricData = metricsByWorker.get(worker.id);
    const card = el('article', undefined, 'distribution-card');
    const header = el('div', undefined, 'distribution-header');
    header.append(el('strong', worker.name), el('span', worker.status, `badge ${worker.status === 'OFFLINE' ? 'offline' : 'available'}`));
    card.append(header);
    const stats = el('div', undefined, 'distribution-stats');
    stats.append(el('span', `${active.length} active now`), el('span', `${metricData?.completed_tasks || 0} completed`), el('span', metricData ? `avg ${(metricData.average_execution_ms / 1000).toFixed(1)}s` : 'No timing yet'));
    card.append(stats);
    if (active.length) {
      const current = el('div', undefined, 'current-work');
      current.append(el('small', 'RUNNING ON THIS COMPUTER'));
      for (const task of active) {
        const row = el('div', undefined, 'task-owner-row');
        row.append(el('strong', task.task_type), el('span', `${task.status} · ${task.elapsed_seconds ?? 0}s`));
        const button = el('button', `Job ${task.job_id.slice(0, 8)}`, 'subtle');
        button.onclick = () => openJob(task.job_id, task.task_type);
        row.append(button); current.append(row);
      }
      card.append(current);
    } else if (recent.length) {
      const last = recent[0];
      card.append(el('p', `Last task: ${last.task_type} · ${last.status}`, 'last-work'));
    } else card.append(el('p', 'No task history yet.', 'last-work'));
    distribution.append(card);
  }
  if (!workerRows.length) distribution.append(el('p', 'No task assignments recorded yet. Submit a job to see which computer claims it.', 'empty'));

  $('activity').replaceChildren();
  for (const task of (data.recent_tasks || []).slice(0, 12)) {
    const row = el('button', undefined, `activity-row${selectedActivityTaskId === task.task_id ? ' selected' : ''}`);
    row.type = 'button';
    const main = el('div', undefined, 'activity-main');
    main.append(el('strong', formatTaskType(task.task_type)), el('span', `${task.worker_name || 'Waiting for a worker'} · ${task.model_id || 'Coordinator default'}`));
    main.append(el('small', `Queue ${formatDuration(task.queue_seconds)} · Execution ${formatExecution(task)} · Attempt ${task.attempt_count}${task.error_code ? ' · ' + task.error_code : ''}`));
    row.append(main);
    row.append(el('span', task.status, `badge activity-status-${String(task.status || '').toLowerCase()}`));
    row.setAttribute('aria-label', `View details for ${formatTaskType(task.task_type)} on ${task.worker_name || 'unassigned worker'}`);
    row.onclick = () => showActivityDetail(task);
    $('activity').append(row);
  }
  if (!(data.recent_tasks || []).length) $('activity').append(el('p', 'No tasks yet.'));
  const selected = (data.recent_tasks || []).find(task => task.task_id === selectedActivityTaskId);
  if (selected) showActivityDetail(selected);
  else if (!(data.recent_tasks || []).length) $('activity-detail').hidden = true;
}
async function refresh() {
  if (polling || !connected) return;
  polling = true;
  const generation = connectionGeneration;
  try {
    const [workers, activity] = await Promise.all([api('/workers?limit=500'), api('/activity')]);
    if (!connected || generation !== connectionGeneration) return;
    latestWorkers = workers;
    renderModels(); renderWorkerPicker(workers); renderWorkers(workers, activity); renderActivity(activity, workers);
    if (jobId) {
      const selectedJob = jobId;
      const result = await api(`/jobs/${selectedJob}/results`);
      if (!connected || generation !== connectionGeneration || selectedJob !== jobId) return;
      renderResults(result);
    }
    $('connection').textContent = 'Connected · live updates';
  } catch (error) {
    if (generation !== connectionGeneration) return;
    $('connection').textContent = 'Connection interrupted — retrying'; $('error').textContent = error.message;
  } finally { polling = false; }
}
function rememberToken(value) {
  try { if (value) sessionStorage.setItem('coordinatorToken', value); else sessionStorage.removeItem('coordinatorToken'); }
  catch { /* Connection still works when browser storage is unavailable. */ }
}
$('coordinator-url').textContent = location.origin;
$('show-token').onclick = () => {
  const show = $('token').type === 'password'; $('token').type = show ? 'text' : 'password'; $('show-token').textContent = show ? 'Hide token' : 'Show token';
};
$('disconnect').onclick = () => {
  latestResult = null; $('download-result').disabled = true; connectionGeneration++; connected = false; token = ''; rememberToken('');
  latestWorkers = []; selectedWorkerId = ''; $('model').value = ''; renderModels(); renderWorkerPicker([]);
  $('token').value = ''; $('token').type = 'password'; $('show-token').textContent = 'Show token';
  $('submit').disabled = true; $('disconnect').hidden = true; $('connection').textContent = 'Disconnected';
  for (const id of ['workers', 'overview', 'distribution', 'activity', 'results']) $(id).replaceChildren();
  $('activity-detail').replaceChildren(); $('activity-detail').hidden = true; selectedActivityTaskId = '';
  $('activity-updated').textContent = 'Waiting for a connection';
};
$('remember-token').onchange = () => rememberToken(connected && $('remember-token').checked ? token : '');
$('connect').onclick = async () => {
  token = $('token').value.trim(); $('connect').disabled = true;
  try {
    await api('/workers?limit=1'); connectionGeneration++; connected = true; rememberToken($('remember-token').checked ? token : '');
    $('submit').disabled = false; $('disconnect').hidden = false; $('error').textContent = ''; await refresh();
  } catch (error) {
    connected = false; rememberToken(''); $('submit').disabled = true; $('connection').textContent = 'Not connected'; $('error').textContent = error.message;
  } finally { $('connect').disabled = false; }
};
$('token').addEventListener('keydown', event => { if (event.key === 'Enter') $('connect').click(); });
try {
  const saved = sessionStorage.getItem('coordinatorToken');
  if (saved) { $('token').value = saved; $('remember-token').checked = true; $('connect').click(); }
} catch { /* Storage is optional. */ }
$('submit').onclick = async () => {
  const mode = $('mode').value; const instruction = ['document-qa', 'coding-assistance'].includes(mode) ? $('instruction').value.trim() : '';
  const document = $('inputs').value.trim();
  if (mode === 'document-qa' && !instruction) { $('error').textContent = 'Enter a question about the document.'; return; }
  if (!document) { $('error').textContent = 'Add a document first.'; return; }
  if (new TextEncoder().encode(document).length > 6000 || new TextEncoder().encode(document + instruction).length > 6500) {
    $('error').textContent = 'Keep the source under 6,000 UTF-8 bytes and source plus request under 6,500. Input will not be silently truncated.'; return;
  }
  submitting = true; $('submit').disabled = true; $('error').textContent = '';
  try {
    const job = await api('/jobs', { task_type: mode, model_id: $('model').value, inputs: [document], optimization: 'fastest', target_worker_id: selectedWorkerId, ...(instruction ? {instruction} : {}) });
    jobId = job.job_id; jobMode = mode;
    $('result-title').textContent = {summarization: 'Document summary', 'document-qa': 'Answer', 'information-extraction': 'Extracted information', 'coding-assistance': 'Code assistance'}[mode];
    await refresh();
  } catch (error) { $('error').textContent = error.message; }
  finally { submitting = false; renderModels(); }
};
setInterval(refresh, 2000);
$('download-result').onclick = () => {
  if (!latestResult) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(latestResult, null, 2)], {type: 'application/json'}));
  const link = document.createElement('a'); link.href = url; link.download = `job-${latestResult.job_id}.json`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
};
