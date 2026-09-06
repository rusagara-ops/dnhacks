const $ = id => document.getElementById(id);
let token = '', jobId = null, connected = false, polling = false, jobMode = 'summarization', connectionGeneration = 0, latestResult = null;
let latestWorkers = [], submitting = false;
let identity = null, creditQuote = null, ambiguousSubmission = false;
const knownJobs = new Map();
let jobsPage = 0, jobsOnPage = [], jobsHaveNext = false, jobsLoading = false, jobsRequest = 0;
const locations = new ComputeLocations(api, () => renderModels());
const example = `The city library is launching a three-month pilot to make its services easier to access. Starting in October, weekday closing time will move from 6 p.m. to 9 p.m. The change follows requests from residents who work during the day and need a quiet place to study in the evening.

The pilot will also introduce a free digital skills workshop every Tuesday evening. Library staff will help participants use online job applications, create a basic resume, and access public services. Twelve computers will be available, and residents can reserve a place by phone or at the front desk.

The city has allocated $18,000 for additional staffing during the pilot. Library managers will track evening attendance, workshop participation, and operating costs. At the end of the three months, they will present the findings to the city council, which will decide whether to continue the extended hours.`;
const modes = {
  'summarization': ['Summarize document →', 'One coherent summary of your entire document.'],
  'document-qa': ['Ask question →', 'Answer a question using only the supplied document.'],
  'information-extraction': ['Extract details →', 'Find names, dates, amounts, and action items in labeled fields.'],
  'coding-assistance': ['Get code help →', 'Explain code or suggest a fix. Suggestions are displayed, never executed.']
};
function updateMode() {
  clearCreditQuote();
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
$('mode').onchange = () => { updateMode(); $('model').value = ''; locations.modelId = ''; locations.setMode($('mode').value); renderModels(); };
$('model').onchange = () => { locations.setModel($('model').value); renderModels(); };
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
function metric(card, label, value) {
  const row = el('div', undefined, 'metric');
  row.append(el('span', label), el('strong', value));
  card.append(row);
}
function workerModels(worker) {
  return worker.models?.length ? worker.models : worker.model_id ? [{model_id: worker.model_id,
    model_revision: worker.model_revision, supported_tasks: worker.supported_tasks}] : [];
}
function renderModels() {
  const select = $('model'), previous = select.value, mode = $('mode').value;
  const choices = new Map();
  for (const worker of latestWorkers) {
    if (locations.selected && locations.selected !== worker.id) continue;
    for (const model of workerModels(worker)) {
      if (!model.supported_tasks.includes(mode)) continue;
      if (!choices.has(model.model_id)) choices.set(model.model_id, []);
      if (worker.status !== 'OFFLINE') choices.get(model.model_id).push(worker.name);
    }
  }
  select.replaceChildren(el('option', 'Coordinator default'));
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
  const available = !previous || !!choices.get(previous)?.length;
  $('model-help').textContent = !connected ? 'Connect to see available models.' : !available
    ? 'The selected model is unavailable. Choose another model or use automatic worker assignment.'
    : previous ? 'Your job will use this exact model on a compatible worker.'
    : 'Uses the coordinator’s configured default model.';
  $('submit').disabled = !connected || submitting || !available || ambiguousSubmission;
  $('submit').textContent = identity?.auth_mode === 'controlled' ? creditQuote ? `Reserve ${creditQuote.value.credits} credits and submit →` : 'Review demo credit cost →' : modes[mode][0];
}
function renderWorkers(workers, activity) {
  const candidates = workers.filter(w => w.status !== 'OFFLINE' && workerModels(w).some(m => m.supported_tasks.some(t => t in modes)));
  const modernHosts = new Set(candidates.filter(w => w.device_id).map(w => w.hostname));
  const seen = new Set();
  const relevant = candidates.filter(w => {
    if (!w.device_id && modernHosts.has(w.hostname) && w.status === 'OFFLINE') return false;
    const key = w.device_id || `legacy:${w.hostname}`;
    if (seen.has(key)) return false;
    seen.add(key); return true;
  });
  $('workers').replaceChildren();
  for (const w of relevant) {
    const card = el('article', undefined, 'worker');
    const online = w.status !== 'OFFLINE';
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
    metric(card, 'CPU usage', online ? `${w.cpu_utilization.toFixed(1)}%` : 'Unavailable');
    metric(card, 'RAM usage', online ? `${w.memory_utilization.toFixed(1)}%` : 'Unavailable');
    metric(card, 'Total RAM' , gib(w.ram_gb));
    metric(card, 'Available RAM', online ? gib(w.ram_available_gb) : 'Offline — unavailable');
    metric(card, 'Total GPU', `${w.gpu || 'Not reported'}${w.gpu_core_count ? ` · ${w.gpu_core_count} cores` : ''}`);
    metric(card, 'GPU memory', shared ? `Shares ${gib(w.ram_gb)} system RAM` : gib(w.gpu_memory_gb));
    metric(card, 'Available GPU memory', !online ? 'Offline — unavailable' : shared
      ? `${gib(w.ram_available_gb)} available in shared RAM*` : gib(w.gpu_available_gb));
    metric(card, 'Ollama GPU allocation', online ? gib(w.gpu_model_memory_gb) : 'Offline — unavailable');
    card.append(el('small', workerModels(w).map(m => m.model_id).join(' · ') || 'No model'));
    if (shared) card.append(el('small', '*System memory estimate, not a guaranteed GPU allocation budget. No separate GPU RAM pool.'));
    $('workers').append(card);
  }
  if (!relevant.length) $('workers').append(el('p', 'No compute machines online. Start a compatible worker.'));
  $('online').textContent = `${relevant.filter(w => w.status !== 'OFFLINE').length} online`;
}
function renderResults(data) {
  latestResult = data; $('download-result').disabled = false;
  WorkDistribution.render($('distribution'), knownJobs.get(jobId), data, latestWorkers);
  $('distribution-state').textContent = 'Showing job ' + jobId;
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
    } else {
      card.append(el(jobMode === 'coding-assistance' ? 'pre' : 'p', result?.text || (task.status === 'FAILED' ? 'Task failed after retries.' : 'Waiting for the result…')));
    }
    card.append(el('small', `${task.worker_name || 'Unassigned'}${task.execution_time_ms !== null ? ' · ' + (task.execution_time_ms / 1000).toFixed(1) + 's' : ''} · attempt ${task.attempt_count}`));
    if (task.inference_metrics) {
      const m = task.inference_metrics;
      card.append(el('small', `Prompt tokens: ${m.prompt_tokens ?? 'unknown'} · Output tokens: ${m.output_tokens ?? 'unknown'} · Generation: ${m.generation_duration_ms === null ? 'unknown' : (m.generation_duration_ms / 1000).toFixed(2) + 's'} · ${m.tokens_per_second ?? 'unknown'} tokens/s`));
    }
    $('results').append(card);
  }
}
async function openJob(id, mode) {
  jobId = id; jobMode = mode;
  $('result-title').textContent = mode;
  $('distribution-state').textContent = 'Loading selected job…';
  $('distribution').replaceChildren();
  const generation = connectionGeneration;
  try {
    const [job, result] = await Promise.all([api(`/jobs/${id}`), api(`/jobs/${id}/results`)]);
    if (connected && jobId === id && generation === connectionGeneration) {
      knownJobs.set(id, job); renderJobList(); renderResults(result);
    }
  } catch (error) { $('error').textContent = error.message; $('distribution-state').textContent = 'Could not load the selected job.'; }
}
function renderJobList() {
  const list = $('job-list');
  const signature = JSON.stringify([jobsOnPage, jobId, jobsPage, jobsHaveNext, jobsLoading, connected]);
  if (list.dataset.signature === signature && list.childElementCount) return;
  list.dataset.signature = signature; list.replaceChildren();
  for (const job of jobsOnPage) {
    const button = el('button', undefined, 'job-list-item' + (job.id === jobId ? ' selected' : ''));
    button.type = 'button'; button.disabled = !connected || jobsLoading;
    button.setAttribute('aria-pressed', String(job.id === jobId));
    button.append(el('strong', `${job.task_type} · ${job.status}`),
      el('span', `${job.model_id || 'Default model'} · ${job.id.slice(0, 8)}`),
      el('small', new Date(job.created_at).toLocaleString()));
    button.onclick = () => { openJob(job.id, job.task_type); renderJobList(); };
    list.append(button);
  }
  if (!jobsOnPage.length) list.append(el('p', !connected ? 'Connect to see jobs.' : jobsLoading ? 'Loading jobs…' : 'No jobs yet.'));
  $('jobs-page').textContent = `Page ${jobsPage + 1}` + (jobsLoading ? ' · Loading…' : jobsOnPage.length ? ` · Jobs ${jobsPage * 10 + 1}–${jobsPage * 10 + jobsOnPage.length}` : '');
  $('jobs-prev').disabled = !connected || jobsLoading || jobsPage === 0;
  $('jobs-next').disabled = !connected || jobsLoading || !jobsHaveNext;
}
async function loadJobPage(background = false) {
  const request = ++jobsRequest, generation = connectionGeneration, page = jobsPage;
  if (!background) { jobsLoading = true; renderJobList(); }
  try {
    // The eleventh record indicates another page; only ten are displayed.
    const jobs = await api(`/jobs?limit=11&offset=${page * 10}`);
    if (!connected || request !== jobsRequest || generation !== connectionGeneration) return;
    jobsOnPage = jobs.slice(0, 10); jobsHaveNext = jobs.length > 10;
    for (const job of jobsOnPage) knownJobs.set(job.id, job);
  } finally {
    if (request === jobsRequest && generation === connectionGeneration) { jobsLoading = false; renderJobList(); }
  }
}
async function changeJobPage(delta) {
  jobsPage += delta; jobsOnPage = [];
  try { await loadJobPage(); }
  catch (error) { $('error').textContent = error.message; }
}
$('jobs-prev').onclick = () => { if (jobsPage > 0 && !jobsLoading) changeJobPage(-1); };
$('jobs-next').onclick = () => { if (jobsHaveNext && !jobsLoading) changeJobPage(1); };
async function refresh() {
  if (polling || !connected) return;
  polling = true;
  const generation = connectionGeneration;
  try {
    const [workers, activity] = await Promise.all([api('/workers?limit=500'), api('/activity'), loadJobPage(true)]);
    if (!connected || generation !== connectionGeneration) return;
    latestWorkers = workers; renderModels(); renderWorkers(workers, activity); renderJobList();
    await locations.refresh();
    if (!connected || generation !== connectionGeneration) return;
    if (jobId) {
      const selectedJob = jobId;
      const result = await api(`/jobs/${selectedJob}/results`);
      if (!connected || generation !== connectionGeneration || selectedJob !== jobId) return;
      renderResults(result);
      if (result.status === 'QUEUED') {
        const eligibility = await api(`/jobs/${selectedJob}/eligibility?limit=100`);
        if (!connected || generation !== connectionGeneration || selectedJob !== jobId) return;
        const online = eligibility.workers.filter(w => !w.reasons.includes('OFFLINE'));
        const reasons = [...new Set(online.flatMap(w => w.reasons))];
        const messages = {FREE_RAM_INSUFFICIENT: 'waiting for available RAM', GPU_MODEL_NOT_CONFIRMED: 'waiting for models to load', BUSY: 'waiting for a free model slot', CPU_OVERLOADED: 'waiting for CPU capacity'};
        if (!online.some(w => w.eligible)) $('status').textContent = 'QUEUED — ' + (online.length ? reasons.map(r => messages[r] || r.toLowerCase().replaceAll('_', ' ')).join('; ') : 'waiting for an online worker');
      }
    }
    $('connection').textContent = 'Connected · live updates';
  } catch (error) {
    if (generation !== connectionGeneration) return;
    $('connection').textContent = 'Connection interrupted — retrying';
    $('distribution-state').textContent = 'Connection interrupted. Displayed counts may be stale.';
    $('error').textContent = error.message;
  } finally { polling = false; }
}
function rememberToken(value) {
  try { if (value) sessionStorage.setItem('coordinatorToken', value); else sessionStorage.removeItem('coordinatorToken'); }
  catch { /* Connection still works when browser storage is unavailable. */ }
}
$('coordinator-url').textContent = location.origin;
$('show-token').onclick = () => {
  const show = $('token').type === 'password'; $('token').type = show ? 'text' : 'password';
  $('show-token').textContent = show ? 'Hide token' : 'Show token';
};
$('disconnect').onclick = () => {
  identity = null; clearCreditQuote(); ambiguousSubmission = false; $('allow-resubmit').hidden = true;
  locations.disconnect();
  latestResult = null; $('download-result').disabled = true;
  connectionGeneration++; connected = false; token = ''; rememberToken('');
  latestWorkers = []; $('model').value = ''; locations.modelId = ''; renderModels();
  $('token').value = ''; $('token').type = 'password'; $('show-token').textContent = 'Show token';
  $('submit').disabled = true; $('disconnect').hidden = true; $('connection').textContent = 'Disconnected';
  knownJobs.clear(); jobId = null; jobsPage = 0; jobsOnPage = []; jobsHaveNext = false; jobsLoading = false; jobsRequest++; renderJobList(); $('distribution-state').textContent = 'Disconnected';
  for (const id of ['workers','distribution','results']) $(id).replaceChildren();
};
$('remember-token').onchange = () => rememberToken(connected && $('remember-token').checked ? token : '');
$('connect').onclick = async () => {
  token = $('token').value.trim();
  $('connect').disabled = true;
  try {
    try { identity = await api('/me'); } catch (error) { if (error.status !== 404) throw error; identity = null; }
    if (identity?.credential_kind === 'worker') throw Error('Use an account token in the dashboard. Worker credentials belong in the worker terminal.');
    if (identity?.credential_kind === 'bootstrap') throw Error('This is a setup token. Open Sharing and credits above to create an administrator account, then connect with its account token.');
    await api('/workers?limit=1');
    connectionGeneration++; connected = true; locations.connected = true; locations.version++;
    clearCreditQuote(); ambiguousSubmission = false; $('allow-resubmit').hidden = true;
    if (identity?.auth_mode === 'controlled') { $('remember-token').checked = false; $('token').value = ''; }
    $('remember-token').disabled = identity?.auth_mode === 'controlled';
    rememberToken($('remember-token').checked ? token : '');
    $('submit').disabled = false; $('disconnect').hidden = false;
    $('error').textContent = '';
    await refresh();
  } catch (error) {
    connected = false; locations.disconnect(); rememberToken(''); $('submit').disabled = true;
    $('connection').textContent = 'Not connected'; $('error').textContent = error.message;
  } finally { $('connect').disabled = false; }
};
$('token').addEventListener('keydown', event => { if (event.key === 'Enter') $('connect').click(); });
try {
  const saved = sessionStorage.getItem('coordinatorToken');
  if (saved) { $('token').value = saved; $('remember-token').checked = true; $('connect').click(); }
} catch { /* Storage is optional. */ }
$('submit').onclick = async () => {
  if (!connected || submitting || ambiguousSubmission) return;
  const mode = $('mode').value;
  const instruction = ['document-qa', 'coding-assistance'].includes(mode) ? $('instruction').value.trim() : '';
  const document = $('inputs').value.trim();
  if (mode === 'document-qa' && !instruction) { $('error').textContent = 'Enter a question about the document.'; return; }
  if (!document) { $('error').textContent = 'Add a document first.'; return; }
  if (new TextEncoder().encode(document).length > 6000 || new TextEncoder().encode(document + instruction).length > 6500) {
    $('error').textContent = 'Keep the source under 6,000 UTF-8 bytes and source plus request under 6,500. Input will not be silently truncated.';
    return;
  }
  submitting = true; $('submit').disabled = true;
  const current = connectionGeneration;
  let submittingJob = false;
  $('error').textContent = '';
  try {
    const payload = { task_type: mode, ...($('model').value ? {model_id: $('model').value} : {}), inputs: [document], optimization: 'fastest', ...(locations.selected ? {target_worker_id: locations.selected} : {}), ...(instruction ? {instruction} : {}) };
    const signature = JSON.stringify(payload);
    if (identity?.auth_mode === 'controlled' && creditQuote?.payload !== signature) {
      const value = await api('/credits/quote', payload);
      if (current !== connectionGeneration) return;
      creditQuote = {payload: signature, value}; $('credit-quote').hidden = false;
      $('credit-quote').textContent = `Reserve ${value.credits} demo credits for ${value.total_inputs} inputs. Accepted work is charged once; permanently failed inputs are refunded. No cash value. Confirm below to submit.`;
      return;
    }
    submittingJob = true;
    const job = await api('/jobs', payload);
    if (current !== connectionGeneration) return;
    clearCreditQuote();
    jobId = job.job_id;
    jobMode = mode;
    jobsPage = 0; await loadJobPage();
    $('result-title').textContent = {summarization: 'Document summary', 'document-qa': 'Answer', 'information-extraction': 'Extracted information', 'coding-assistance': 'Code assistance'}[mode];
    await refresh();
  } catch (error) {
    if (current !== connectionGeneration) return;
    ambiguousSubmission = submittingJob && (!error.status || error.status >= 500);
    $('allow-resubmit').hidden = !ambiguousSubmission;
    $('error').textContent = ambiguousSubmission ? 'Submission could not be confirmed. A job and credit reservation may already exist. Check recent jobs before submitting again.' : error.message;
  }
  finally { submitting = false; renderModels(); }
};
function clearCreditQuote() { creditQuote = null; $('credit-quote').hidden = true; $('credit-quote').textContent = ''; }
for (const id of ['inputs', 'instruction', 'model']) $(id).addEventListener('input', () => { clearCreditQuote(); renderModels(); });
$('sample').addEventListener('click', () => { clearCreditQuote(); renderModels(); });
$('allow-resubmit').onclick = () => { ambiguousSubmission = false; $('allow-resubmit').hidden = true; $('error').textContent = ''; renderModels(); };
setInterval(refresh, 2000);

$('download-result').onclick = () => {
  if (!latestResult) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(latestResult, null, 2)], {type:'application/json'}));
  const link = document.createElement('a'); link.href = url; link.download = `job-${latestResult.job_id}.json`;
  link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
};
