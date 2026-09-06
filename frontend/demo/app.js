const $ = id => document.getElementById(id);
let token = '', jobId = null, connected = false, polling = false, jobMode = 'summarization';
let connectionGeneration = 0, latestResult = null, latestWorkers = [], submitting = false;
let selectedWorkerId = '';
let selectedActivityTaskId = '';
let documents = [], parsing = false, parseGeneration = 0, uncertainSubmission = false;
/* Retired registrations still own completed tasks, so telemetry resolves names from
   the full worker history. It changes rarely; refetch only when it goes stale or a
   task references an ID we have not seen. */
let workerHistory = [], historyFetchedAt = 0;
/* Submitting used to be a quiet wait: the button greyed out and nothing else moved
   until a poll landed. This tracks the job through its stages and keeps a live
   elapsed counter running between polls. */
let jobStage = null, stageTicker = null;
const jobFiles = new Map();
function fileMode() { return document.querySelector('input[name="source-kind"]:checked').value === 'files'; }
function saveNames(id, names) {
  jobFiles.set(id, names);
  try {
    const stored = JSON.parse(sessionStorage.getItem('documentJobNames') || '{}');
    stored[id] = names;
    sessionStorage.setItem('documentJobNames', JSON.stringify(Object.fromEntries(Object.entries(stored).slice(-50))));
  } catch { /* Names remain available until refresh if storage is unavailable. */ }
}
function namesFor(id) {
  if (jobFiles.has(id)) return jobFiles.get(id);
  try { const names = JSON.parse(sessionStorage.getItem('documentJobNames') || '{}')[id]; return Array.isArray(names) ? names : []; } catch { return []; }
}
function renderDocuments() {
  $('document-list').replaceChildren();
  for (const [index, entry] of documents.entries()) {
    const card = el('article', undefined, 'upload-document');
    card.append(el('strong', entry.name), el('p', entry.error || (entry.text === null ? 'Parsing…' : `Ready · ${Documents.bytes(entry.text).toLocaleString()} UTF-8 bytes`), entry.error ? 'failure' : 'muted'));
    if (entry.text !== null && !entry.error) {
      const preview = el('details'); preview.append(el('summary', 'Preview extracted text'), el('pre', entry.text)); card.append(preview);
    }
    const remove = el('button', 'Remove', 'subtle'); remove.type = 'button'; remove.disabled = parsing || submitting;
    remove.onclick = () => { documents.splice(index,1); renderDocuments(); }; card.append(remove); $('document-list').append(card);
  }
  $('upload-status').textContent = `${documents.length} documents · ${documents.filter(entry => entry.text !== null && !entry.error).length} ready${parsing ? ' · Parsing…' : ''}`;
  $('document-files').disabled = parsing || submitting; $('clear-documents').disabled = parsing || submitting;
  renderModels();
}
document.querySelectorAll('input[name="source-kind"]').forEach(input => input.onchange = () => {
  $('upload-panel').hidden = !fileMode(); $('paste-panel').hidden = fileMode(); $('sample').hidden = fileMode(); updateMode(); renderDocuments();
});
$('clear-documents').onclick = () => { documents = []; $('document-files').value = ''; renderDocuments(); };
$('document-files').onchange = async event => {
  const files = Array.from(event.target.files); event.target.value = '';
  if (documents.length + files.length > Documents.MAX_FILES) { $('error').textContent = 'Choose at most 100 documents per batch.'; return; }
  parsing = true; const current = ++parseGeneration; $('error').textContent = '';
  const added = files.map(file => ({name:file.name,text:null,error:null})); documents.push(...added); renderDocuments();
  for (let index=0; index<files.length; index++) {
    try { added[index].text = await Documents.parse(files[index]); }
    catch (error) { added[index].error = error.message; }
    if (current !== parseGeneration) return;
    renderDocuments();
  }
  parsing = false; renderDocuments();
};


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
  $('mode-help').textContent = fileMode() ? 'Each uploaded document is processed independently; results stay associated with its filename.' : modes[mode][1];
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
    method: body === undefined ? 'GET' : 'POST', redirect: 'error', signal: AbortSignal.timeout(15000),
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
/* The connection pill lives in the header, so its state has to be set explicitly
   rather than inferred from where the text happens to sit. */
function setConnection(state, text) {
  document.querySelector('.connect').classList.toggle('is-connected', state === 'live');
  const pill = $('connection');
  pill.className = `conn conn-${state}`;
  pill.textContent = text;
}
const HERO_STATS = [
  ['workers_online', 'Machines online'],
  ['tasks_completed', 'Tasks completed'],
  ['jobs_completed', 'Jobs completed'],
  ['total_inferences', 'Documents processed']
];
function renderHeroStats(stats) {
  const panel = $('hero-stats');
  if (!stats) { panel.hidden = true; panel.replaceChildren(); return; }
  panel.replaceChildren();
  for (const [key, label] of HERO_STATS) {
    const item = el('div', undefined, 'hero-stat');
    item.append(el('strong', Number(stats[key] ?? 0).toLocaleString()), el('span', label));
    panel.append(item);
  }
  panel.hidden = false;
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
  $('submit').disabled = !connected || submitting || !available || !selectedWorkerId || uncertainSubmission || (fileMode() && (parsing || !documents.length || documents.some(entry => entry.error || entry.text === null)));
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
  renderDataPath(jobStage?.key || '');
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
const STAGES = [
  {key: 'sending', label: 'Sending'},
  {key: 'queued', label: 'Queued'},
  {key: 'running', label: 'Running'},
  {key: 'done', label: 'Done'}
];
function setJobStage(key, {machine = '', model = '', failed = false} = {}) {
  const previous = jobStage;
  jobStage = {
    key, failed,
    machine: machine || previous?.machine || '',
    model: model || previous?.model || '',
    // Elapsed is only honest for a job this tab submitted; reopened jobs omit it.
    startedAt: previous ? previous.startedAt : key === 'sending' ? Date.now() : null,
    enteredAt: previous && previous.key === key ? previous.enteredAt : Date.now(),
    finishedAt: key === 'done' ? previous?.finishedAt ?? Date.now() : null
  };
  renderJobStage();
  renderDataPath(key);
  if (key === 'done') {
    if (stageTicker) { clearInterval(stageTicker); stageTicker = null; }
  } else if (!stageTicker) stageTicker = setInterval(renderJobStage, 1000);
}
function clearJobStage() {
  jobStage = null;
  renderDataPath('');
  if (stageTicker) { clearInterval(stageTicker); stageTicker = null; }
  $('job-stage').replaceChildren();
  $('job-stage').hidden = true;
}
function renderJobStage() {
  if (!jobStage) return;
  const panel = $('job-stage');
  panel.hidden = false;
  panel.replaceChildren();
  const active = STAGES.findIndex(stage => stage.key === jobStage.key);
  const steps = el('div', undefined, 'stage-steps');
  for (const [index, stage] of STAGES.entries()) {
    const state = jobStage.failed && index === active ? 'failed'
      : index < active ? 'done' : index === active ? 'current' : 'todo';
    const step = el('div', undefined, `stage-step stage-${state}`);
    step.append(el('span', undefined, 'stage-dot'), el('span', stage.label, 'stage-name'));
    steps.append(step);
  }
  panel.append(steps);
  const on = jobStage.machine ? ` on ${jobStage.machine}` : '';
  const waiting = Math.round((Date.now() - jobStage.enteredAt) / 1000);
  const message = {
    sending: 'Sending to the coordinator…',
    queued: `Queued — waiting for ${jobStage.machine || 'a machine'} to claim it · ${waiting}s`,
    running: `Running${on} · ${waiting}s`,
    done: jobStage.failed ? `Finished with failures${on}` : `Completed${on}`
  }[jobStage.key];
  const line = el('p', message, `stage-message${jobStage.failed ? ' failure' : ''}`);
  if (jobStage.startedAt !== null) {
    const total = Math.round(((jobStage.finishedAt ?? Date.now()) - jobStage.startedAt) / 1000);
    line.append(el('span', `${total}s since you submitted`, 'stage-total'));
  }
  panel.append(line);
}
/* The coordinator stores the job and forwards its tasks to the selected worker. */
function renderDataPath(stage) {
  const figure = $('data-path');
  const worker = latestWorkers.find(candidate => candidate.id === selectedWorkerId);
  const machine = jobStage ? jobStage.machine : worker?.name || '';
  const model = jobStage ? jobStage.model : $('model').value;
  if (!machine && !model) { figure.hidden = true; return; }
  figure.hidden = false;
  $('path-machine').textContent = machine || 'No machine chosen';
  $('path-model').textContent = model || (jobStage ? 'Recorded job' : 'Pick a model');
  figure.classList.toggle('path-live', stage === 'sending' || stage === 'running');
  figure.classList.toggle('path-done', stage === 'done');
  // Direction of travel: outbound while the job runs, inbound once results exist.
  figure.dataset.leg = stage === 'done' ? 'back' : stage ? 'out' : 'idle';
  $('path-note').textContent = machine
    ? `The coordinator stores your job and results, and sends the task to ${machine}. Coordinator and worker operators can access the text.`
    : 'The coordinator stores your job and results, and sends tasks to your selected worker. Coordinator and worker operators can access the text.';
}
function trackJob(data) {
  const machine = data.tasks.map(task => task.worker_name).find(Boolean) || '';
  if (data.status === 'COMPLETED' || data.status === 'FAILED') {
    setJobStage('done', {machine, failed: data.status === 'FAILED'});
  } else if (data.tasks.some(task => ['ASSIGNED', 'RUNNING'].includes(task.status))) {
    setJobStage('running', {machine});
  } else setJobStage('queued', {machine});
}
function renderResults(data) {
  latestResult = data; $('download-result').disabled = false; $('copy-result').disabled = !data.results.length;
  trackJob(data);
  $('status').textContent = data.status;
  $('progress').max = data.total_inputs;
  $('progress').value = data.completed_inputs + data.failed_inputs;
  $('job').textContent = `Job ${jobId} · ${data.completed_inputs}/${data.total_inputs} documents complete`;
  $('results').replaceChildren();
  if (data.status === 'FAILED') $('results').append(el('p', 'This job failed. Any results shown are partial.', 'failure'));
  for (const task of data.tasks) {
    const card = el('article', undefined, 'result');
    const result = data.results.find(r => r.index === task.input_start_index);
    card.append(el('h3', namesFor(jobId)[task.input_start_index] || `Document ${task.input_start_index + 1}`));
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
  const generation = connectionGeneration;
  if (id !== jobId) clearJobStage();
  jobId = id; jobMode = mode; $('result-title').textContent = mode;
  try { const result = await api(`/jobs/${id}/results`); if (connected && generation === connectionGeneration && jobId === id) renderResults(result); }
  catch (error) { if (generation === connectionGeneration) $('error').textContent = error.message; }
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
function machineStatusLabel(machine) {
  if (machine.activeTasks.length) return 'WORKING';
  return machine.online ? 'ONLINE' : 'OFFLINE';
}
function renderOverview(summary) {
  const cards = {
    Queued: summary.queued, Active: summary.active, Completed: summary.completed,
    Failed: summary.failed, Retries: summary.retries
  };
  $('overview').replaceChildren();
  for (const [label, value] of Object.entries(cards)) {
    const card = el('article', undefined, `telemetry-card telemetry-${label.toLowerCase()}`);
    card.append(el('strong', String(value)), el('span', label));
    $('overview').append(card);
  }
}
function renderShareChart(machines) {
  const holder = $('share-chart'), legend = $('share-legend');
  holder.replaceChildren(); legend.replaceChildren();
  const contributors = machines.filter(machine => machine.completedTasks > 0);
  const total = contributors.reduce((sum, machine) => sum + machine.completedTasks, 0);
  if (!total) {
    holder.append(el('p', 'No completed tasks yet.', 'empty'));
    return;
  }
  holder.append(Charts.donut(
    contributors.map((machine, index) => ({
      label: machine.name, value: machine.completedTasks, color: Charts.colorFor(index)
    })),
    {centerValue: total, centerLabel: total === 1 ? 'task' : 'tasks'}
  ));
  for (const [index, machine] of contributors.entries()) {
    const item = el('li', undefined, 'legend-item');
    const swatch = el('span', undefined, 'swatch');
    swatch.style.background = Charts.colorFor(index);
    const text = el('div', undefined, 'legend-text');
    text.append(el('strong', machine.name));
    const detail = `${machine.completedTasks} ${machine.completedTasks === 1 ? 'task' : 'tasks'} · ${Charts.percent(machine.completedTasks, total)}%`;
    text.append(el('span', detail));
    item.append(swatch, text);
    item.append(el('span', machineStatusLabel(machine), `legend-status status-${machineStatusLabel(machine).toLowerCase()}`));
    legend.append(item);
  }
}
function renderTypeMix(machines, fullHistory) {
  const chart = $('mix-chart'), legend = $('type-legend');
  chart.replaceChildren(); legend.replaceChildren();
  $('mix-scope').textContent = fullHistory ? 'By task type · all completed work' : 'By task type · last 30 tasks';
  const totals = Telemetry.typeTotals(machines);
  if (!totals.length) {
    chart.append(el('p', 'No completed tasks to break down yet.', 'empty'));
    return;
  }
  for (const entry of totals) {
    const item = el('span', undefined, 'legend-chip');
    const swatch = el('span', undefined, 'swatch');
    swatch.style.background = Charts.TYPE_COLORS[entry.type] || '#7a8596';
    item.append(swatch, el('span', `${entry.label} · ${entry.count}`));
    legend.append(item);
  }
  const rows = machines.filter(machine => machine.byType.size);
  const max = Math.max(...rows.map(machine => [...machine.byType.values()].reduce((a, b) => a + b, 0)), 1);
  for (const machine of rows) {
    const row = el('div', undefined, 'mix-row');
    const label = el('div', undefined, 'mix-label');
    const counted = [...machine.byType.values()].reduce((a, b) => a + b, 0);
    label.append(el('strong', machine.name), el('span', `${counted} ${counted === 1 ? 'task' : 'tasks'}`));
    row.append(label);
    const segments = Telemetry.TASK_TYPES
      .filter(type => machine.byType.get(type))
      .map(type => ({type, label: Telemetry.LABELS[type] || type, value: machine.byType.get(type)}));
    for (const [type, value] of machine.byType) {
      if (!Telemetry.TASK_TYPES.includes(type)) segments.push({type, label: type, value});
    }
    row.append(Charts.stackedBar(segments, max));
    const detail = el('div', undefined, 'mix-detail');
    for (const segment of segments) detail.append(el('span', `${segment.label} ${segment.value}`));
    row.append(detail);
    chart.append(row);
  }
}
function renderMachines(machines) {
  const distribution = $('distribution');
  distribution.replaceChildren();
  for (const machine of machines) {
    const card = el('article', undefined, `distribution-card${machine.activeTasks.length ? ' working' : ''}`);
    const header = el('div', undefined, 'distribution-header');
    const status = machineStatusLabel(machine);
    header.append(el('strong', machine.name), el('span', status, `badge status-${status.toLowerCase()}`));
    card.append(header);
    card.append(el('p', machine.models.join(' · ') || 'Model not reported', 'distribution-models'));
    const stats = el('div', undefined, 'distribution-stats');
    stats.append(
      el('span', `${machine.completedTasks} completed`),
      el('span', `${machine.activeTasks.length} active now`),
      el('span', machine.averageExecutionMs ? `avg ${(machine.averageExecutionMs / 1000).toFixed(1)}s` : 'No timing yet')
    );
    if (machine.registrations > 1) stats.append(el('span', `${machine.registrations} registrations`));
    card.append(stats);
    const timings = machine.recentTasks
      .filter(task => Number.isFinite(task.execution_time_ms))
      .slice(0, 12).reverse().map(task => task.execution_time_ms);
    if (timings.length > 1) {
      const trend = el('div', undefined, 'distribution-trend');
      trend.append(Charts.sparkline(timings), el('small', 'Recent execution time'));
      card.append(trend);
    }
    if (machine.activeTasks.length) {
      const current = el('div', undefined, 'current-work');
      current.append(el('small', 'RUNNING ON THIS COMPUTER'));
      for (const task of machine.activeTasks) {
        const row = el('div', undefined, 'task-owner-row');
        row.append(el('strong', formatTaskType(task.task_type)), el('span', `${task.status} · ${task.elapsed_seconds ?? 0}s`));
        const button = el('button', `Job ${task.job_id.slice(0, 8)}`, 'subtle');
        button.onclick = () => openJob(task.job_id, task.task_type);
        row.append(button); current.append(row);
      }
      card.append(current);
    } else if (machine.lastTask) {
      card.append(el('p', `Last task: ${formatTaskType(machine.lastTask.task_type)} · ${machine.lastTask.status}`, 'last-work'));
    } else card.append(el('p', 'No task history yet.', 'last-work'));
    distribution.append(card);
  }
  if (!machines.length) distribution.append(el('p', 'No task assignments recorded yet. Submit a job to see which computer claims it.', 'empty'));
}
function renderActivity(data, workers) {
  renderOverview(Telemetry.summary(data));
  $('activity-updated').textContent = data.as_of ? `Updated ${new Date(data.as_of).toLocaleTimeString()}` : 'Live coordinator data';

  const machines = Telemetry.machines(data, workers);
  renderShareChart(machines);
  renderTypeMix(machines, Telemetry.hasFullTypeHistory(data));
  renderMachines(machines);

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
async function ensureWorkerHistory(activity, live, generation) {
  const referenced = new Set([
    ...(activity.worker_metrics || []).map(metric => metric.worker_id),
    ...(activity.active_tasks || []).map(task => task.worker_id),
    ...(activity.recent_tasks || []).map(task => task.worker_id),
    ...(activity.worker_task_types || []).map(row => row.worker_id)
  ].filter(Boolean));
  const known = new Set(workerHistory.map(worker => worker.id));
  if (Date.now() - historyFetchedAt >= 30000 || [...referenced].some(id => !known.has(id))) {
    try {
      const history = [];
      for (let offset = 0; ; offset += 500) {
        const page = await api(`/workers?limit=500&include_history=true&offset=${offset}`);
        if (!connected || generation !== connectionGeneration) return [];
        history.push(...page);
        if (page.length < 500) break;
      }
      workerHistory = history;
      historyFetchedAt = Date.now();
    } catch {
      // Unknown historical IDs remain separate; never guess identity from names.
    }
  }
  // Cached history resolves identity; each fresh poll supplies current presence.
  const merged = new Map(workerHistory.map(worker => [worker.id, {...worker, status: 'OFFLINE'}]));
  for (const worker of live) merged.set(worker.id, worker);
  return [...merged.values()];
}
async function refresh() {
  if (polling || !connected) return;
  polling = true;
  const generation = connectionGeneration;
  try {
    const [workers, activity, stats] = await Promise.all([
      api('/workers?limit=500'), api('/activity'),
      // Older coordinators may not expose /stats; the hero simply stays hidden.
      api('/stats').catch(() => null)
    ]);
    if (!connected || generation !== connectionGeneration) return;
    renderHeroStats(stats);
    latestWorkers = workers;
    const history = await ensureWorkerHistory(activity, workers, generation);
    if (!connected || generation !== connectionGeneration) return;
    renderModels(); renderWorkerPicker(workers); renderWorkers(workers, activity); renderActivity(activity, history);
    if (jobId) {
      const selectedJob = jobId;
      const result = await api(`/jobs/${selectedJob}/results`);
      if (!connected || generation !== connectionGeneration || selectedJob !== jobId) return;
      renderResults(result);
    }
    setConnection('live', 'Connected · live updates');
  } catch (error) {
    if (generation !== connectionGeneration) return;
    setConnection('warn', 'Connection interrupted — retrying'); $('error').textContent = error.message;
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
  latestResult = null; $('download-result').disabled = true; $('copy-result').disabled = true; connectionGeneration++; uncertainSubmission = false; $('retry-submission').hidden = true; connected = false; token = ''; rememberToken('');
  latestWorkers = []; selectedWorkerId = ''; $('model').value = ''; renderModels(); renderWorkerPicker([]);
  $('token').value = ''; $('token').type = 'password'; $('show-token').textContent = 'Show token';
  $('submit').disabled = true; $('disconnect').hidden = true; setConnection('idle', 'Disconnected');
  workerHistory = []; historyFetchedAt = 0; clearJobStage(); renderHeroStats(null);
  jobId = null; $('status').textContent = 'No job yet'; $('job').textContent = 'Submit a document to begin.'; $('progress').value = 0;
  for (const id of ['workers', 'overview', 'distribution', 'activity', 'results', 'share-chart', 'share-legend', 'type-legend', 'mix-chart']) $(id).replaceChildren();
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
    connected = false; rememberToken(''); $('submit').disabled = true; setConnection('idle', 'Not connected'); $('error').textContent = error.message;
  } finally { $('connect').disabled = false; }
};
$('token').addEventListener('keydown', event => { if (event.key === 'Enter') $('connect').click(); });
try {
  const saved = sessionStorage.getItem('coordinatorToken');
  if (saved) { $('token').value = saved; $('remember-token').checked = true; $('connect').click(); }
} catch { /* Storage is optional. */ }
$('submit').onclick = async () => {
  const mode = $('mode').value;
  const instruction = ['document-qa', 'coding-assistance'].includes(mode) ? $('instruction').value.trim() : '';
  if (submitting || parsing || uncertainSubmission || !connected || !selectedWorkerId || !$('model').value) return;
  const document = $('inputs').value;
  let inputs;
  try { inputs = Documents.validate(fileMode() ? documents : [{name:'Pasted document',text:document}], instruction); }
  catch (error) { $('error').textContent = error.message; return; }
  const names = fileMode() ? documents.map(entry => entry.name) : ['Pasted document'];
  const generation = connectionGeneration;
  if (mode === 'document-qa' && !instruction) { $('error').textContent = 'Enter a question about the document.'; return; }
  submitting = true; $('submit').disabled = true; renderDocuments();
  $('error').textContent = '';
  jobId = null; latestResult = null; $('results').replaceChildren();
  $('download-result').disabled = true; $('copy-result').disabled = true; $('progress').value = 0;
  clearJobStage(); setJobStage('sending', {
    machine: latestWorkers.find(worker => worker.id === selectedWorkerId)?.name || '', model: $('model').value
  });
  $('status').textContent = 'Submitting';
  $('job').textContent = 'Handing the job to the coordinator…';
  let accepted = false;
  try {
    const job = await api('/jobs', { task_type: mode, model_id: $('model').value, inputs, optimization: 'fastest', target_worker_id: selectedWorkerId, ...(instruction ? {instruction} : {}) });
    accepted = true; saveNames(job.job_id, names);
    if (generation !== connectionGeneration || !connected) return;
    jobId = job.job_id;
    jobMode = mode;
    setJobStage('queued');
    $('result-title').textContent = {summarization: 'Document summary', 'document-qa': 'Answer', 'information-extraction': 'Extracted information', 'coding-assistance': 'Code assistance'}[mode];
    await refresh();
  } catch (error) {
    if (generation !== connectionGeneration) return;
    clearJobStage();
    uncertainSubmission = !accepted && (!error.status || error.status >= 500);
    $('error').textContent = uncertainSubmission ? 'Submission could not be confirmed. Check recent task activity before trying again; a job may already exist.' : error.message;
    $('retry-submission').hidden = !uncertainSubmission;
  }
  finally { submitting = false; renderDocuments(); }
};
setInterval(refresh, 2000);
function resultText(data) {
  return data.results.map((entry, index) => {
    const name = namesFor(data.job_id)[entry.index] || `Document ${entry.index + 1}`;
    if ('names' in entry) {
      return [name, `Names: ${entry.names.join(', ') || '—'}`, `Dates: ${entry.dates.join(', ') || '—'}`,
              `Amounts: ${entry.amounts.join(', ') || '—'}`, `Action items: ${entry.action_items.join(', ') || '—'}`].join('\n');
    }
    return data.results.length > 1 ? `${name}\n${entry.text}` : entry.text;
  }).join('\n\n');
}
$('copy-result').onclick = async () => {
  if (!latestResult) return;
  try {
    await navigator.clipboard.writeText(resultText(latestResult));
    $('copy-result').textContent = 'Copied';
  } catch {
    $('copy-result').textContent = 'Copy blocked by browser';
  }
  setTimeout(() => { $('copy-result').textContent = 'Copy result'; }, 1600);
};
// Submitting from the keyboard without reaching for the mouse.
for (const id of ['inputs', 'instruction']) {
  $(id).addEventListener('keydown', event => {
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter' && !$('submit').disabled) $('submit').click();
  });
}
$('download-result').onclick = () => {
  if (!latestResult) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify({...latestResult, source_files: namesFor(latestResult.job_id).map((name,index) => ({index,name}))}, null, 2)], {type: 'application/json'}));
  const link = document.createElement('a'); link.href = url; link.download = `job-${latestResult.job_id}.json`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
};
$('retry-submission').onclick = () => { uncertainSubmission = false; $('retry-submission').hidden = true; $('error').textContent = ''; renderModels(); };
