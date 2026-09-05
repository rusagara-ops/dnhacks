const $ = id => document.getElementById(id);
let token = '', jobId = null, connected = false, polling = false;
const example = `The city library is launching a three-month pilot to make its services easier to access. Starting in October, weekday closing time will move from 6 p.m. to 9 p.m. The change follows requests from residents who work during the day and need a quiet place to study in the evening.

The pilot will also introduce a free digital skills workshop every Tuesday evening. Library staff will help participants use online job applications, create a basic resume, and access public services. Twelve computers will be available, and residents can reserve a place by phone or at the front desk.

The city has allocated $18,000 for additional staffing during the pilot. Library managers will track evening attendance, workshop participation, and operating costs. At the end of the three months, they will present the findings to the city council, which will decide whether to continue the extended hours.`;
function samples() { $('inputs').value = example; }
samples();
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
  if (!response.ok) throw Error(response.status === 401 ? 'Invalid API token.' : `Coordinator request failed (${response.status}).`);
  return response.json();
}
function metric(card, label, value) {
  const row = el('div', undefined, 'metric');
  row.append(el('span', label), el('strong', value));
  card.append(row);
}
function renderWorkers(workers) {
  const relevant = workers.filter(w => w.supported_tasks.includes('summarization') && w.model_id === 'gemma3:12b');
  $('workers').replaceChildren();
  for (const w of relevant) {
    const card = el('article', undefined, 'worker');
    const online = w.status !== 'OFFLINE';
    const shared = w.gpu_memory_kind === 'unified';
    card.append(el('strong', w.name), el('span', w.status, 'badge'));
    metric(card, 'Total RAM', gib(w.ram_gb));
    metric(card, 'Available RAM', online ? gib(w.ram_available_gb) : 'Offline — unavailable');
    metric(card, 'Total GPU', `${w.gpu || 'Not reported'}${w.gpu_core_count ? ` · ${w.gpu_core_count} cores` : ''}`);
    metric(card, 'GPU memory', shared ? `Shares ${gib(w.ram_gb)} system RAM` : gib(w.gpu_memory_gb));
    metric(card, 'Available GPU memory', !online ? 'Offline — unavailable' : shared
      ? `${gib(w.ram_available_gb)} available in shared RAM*` : gib(w.gpu_available_gb));
    metric(card, 'Ollama GPU allocation', online ? gib(w.gpu_model_memory_gb) : 'Offline — unavailable');
    card.append(el('small', w.model_id || 'No model'));
    if (shared) card.append(el('small', '*System memory estimate, not a guaranteed GPU allocation budget. No separate GPU RAM pool.'));
    const seconds = Math.max(0, Math.round((Date.now() - new Date(w.last_heartbeat).getTime()) / 1000));
    card.append(el('small', `Last heartbeat ${seconds}s ago`));
    $('workers').append(card);
  }
  if (!relevant.length) $('workers').append(el('p', 'No workers registered. Start the Gemma worker on Abel’s Mac.'));
  $('online').textContent = `${relevant.filter(w => w.status !== 'OFFLINE').length} online`;
}
function renderResults(data) {
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
    card.append(el('p', result?.text || (task.status === 'FAILED' ? 'Summary failed after retries.' : 'Waiting for the document summary…')));
    card.append(el('small', `${task.worker_name || 'Unassigned'}${task.execution_time_ms !== null ? ' · ' + (task.execution_time_ms / 1000).toFixed(1) + 's' : ''} · attempt ${task.attempt_count}`));
    $('results').append(card);
  }
}
async function refresh() {
  if (polling || !connected) return;
  polling = true;
  try {
    renderWorkers(await api('/workers?limit=100'));
    if (jobId) renderResults(await api(`/jobs/${jobId}/results`));
    $('connection').textContent = 'Connected';
  } catch (error) {
    $('connection').textContent = 'Connection interrupted';
    $('error').textContent = error.message;
  } finally { polling = false; }
}
$('connect').onclick = async () => {
  token = $('token').value;
  try {
    await api('/workers?limit=1');
    connected = true;
    $('submit').disabled = false;
    $('error').textContent = '';
    await refresh();
  } catch (error) {
    connected = false;
    $('submit').disabled = true;
    $('connection').textContent = 'Not connected';
    $('error').textContent = error.message;
  }
};
$('submit').onclick = async () => {
  const document = $('inputs').value.trim();
  if (!document) { $('error').textContent = 'Add a document first.'; return; }
  if (new TextEncoder().encode(document).length > 6000) {
    $('error').textContent = 'Keep the document under 6,000 UTF-8 bytes for this demo. It will not be silently truncated.';
    return;
  }
  $('submit').disabled = true;
  $('error').textContent = '';
  try {
    const job = await api('/jobs', { task_type: 'summarization', inputs: [document], optimization: 'fastest' });
    jobId = job.job_id;
    await refresh();
  } catch (error) { $('error').textContent = error.message; }
  finally { $('submit').disabled = !connected; }
};
setInterval(refresh, 2000);
