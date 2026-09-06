import { StrictMode, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ApiError, request, type Connection, type Job, type Worker, type Results, type Activity, type Identity, type CreditQuote } from './api';
import { createPayload, type TaskType } from './validation';
import './style.css';
import { Distribution } from './WorkDistribution';

const modes: Record<TaskType, string> = { summarization: 'Summarize document', 'document-qa': 'Ask about a document', 'information-extraction': 'Extract information', 'coding-assistance': 'Get coding assistance', 'sentiment-classification': 'Classify sentiment (legacy)' };
function savedConnection(): Connection | null {
  try { const value = JSON.parse(sessionStorage.getItem('sc-connection') || 'null'); return value && typeof value.url === 'string' && typeof value.token === 'string' ? value : null; } catch { return null; }
}
function App() {
  const [saved] = useState(savedConnection);
  const [url, setUrl] = useState(saved?.url ?? 'http://192.168.11.139:8000');
  const [token, setToken] = useState(saved?.token ?? '');
  const [remember, setRemember] = useState(!!saved);
  const [connection, setConnection] = useState<Connection | null>(null);
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [sharingUrl, setSharingUrl] = useState((saved?.url ?? 'http://192.168.11.139:8000') + '/demo/sharing.html');
  const [quote, setQuote] = useState<{payload: string; value: CreditQuote} | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [connectionError, setConnectionError] = useState('');
  const [mode, setMode] = useState<TaskType>('summarization');
  const [sections, setSections] = useState(false);
  const [source, setSource] = useState('');
  const [instruction, setInstruction] = useState('');
  const [jobs, setJobs] = useState<Job[]>([]);
  const [workers, setWorkers] = useState<Worker[]>([]);
  const [activity, setActivity] = useState<Activity | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [results, setResults] = useState<Results | null>(null);
  const [pollError, setPollError] = useState('');
  const [submitError, setSubmitError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [ambiguous, setAmbiguous] = useState(false);
  const submitLock = useRef(false);
  const generation = useRef(0);
  const pollGeneration = useRef(0);

  function disconnect() {
    generation.current++; pollGeneration.current++; setConnection(null); setToken(''); setRemember(false); setIdentity(null); setQuote(null);
    setJobs([]); setWorkers([]); setActivity(null); setSelectedId(null); setJob(null); setResults(null); setPollError(''); setSubmitError(''); setAmbiguous(false); setConnectionError('');
    try { sessionStorage.removeItem('sc-connection'); } catch { /* Storage may be disabled. */ }
  }
  async function connect(event: React.FormEvent) {
    event.preventDefault(); setConnecting(true); setConnectionError('');
    try {
      const parsed = new URL(url);
      if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password || parsed.search || parsed.hash || parsed.pathname !== '/') throw new Error('Use a backend origin such as http://192.168.1.5:8000.');
      const next = { url: parsed.origin, token: token.trim() };
      setSharingUrl(parsed.origin + '/demo/sharing.html');
      await request(next, '/health'); await request(next, '/ready');
      let me: Identity | null = null;
      try { me = await request<Identity>(next, '/api/me'); } catch (error) { if (!(error instanceof ApiError) || error.status !== 404) throw error; }
      if (me?.credential_kind === 'worker') throw new Error('Use an account token in the dashboard. Worker credentials belong in the worker terminal.');
      if (me?.credential_kind === 'bootstrap') throw new Error('This is a setup token. Open Sharing and credits below to create an administrator account, then connect with its account token.');
      const list = await request<Job[]>(next, '/api/jobs?limit=100&offset=0');
      setIdentity(me); setQuote(null);
      generation.current++; pollGeneration.current++; setConnection(next); setJobs(list); setWorkers([]); setActivity(null); setSelectedId(null); setJob(null); setResults(null); setPollError(''); setSubmitError(''); setAmbiguous(false);
      if (me?.auth_mode === 'controlled') { setRemember(false); setToken(''); }
      try { if (remember && me?.auth_mode !== 'controlled') sessionStorage.setItem('sc-connection', JSON.stringify(next)); else sessionStorage.removeItem('sc-connection'); } catch { setConnectionError('Connected, but this browser could not remember settings for this tab.'); }
    } catch (error) { setConnectionError((error as Error).message); }
    finally { setConnecting(false); }
  }
  useEffect(() => {
    if (!connection) return;
    const current = ++pollGeneration.current;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      const reads = await Promise.allSettled([
        request<Job[]>(connection!, '/api/jobs?limit=100&offset=0'), request<Worker[]>(connection!, '/api/workers?limit=500&offset=0'), request<Activity>(connection!, '/api/activity'),
        selectedId ? request<Job>(connection!, `/api/jobs/${selectedId}`) : Promise.resolve(null),
        selectedId ? request<Results>(connection!, `/api/jobs/${selectedId}/results`) : Promise.resolve(null),
      ]);
      if (current !== pollGeneration.current) return;
      const [list, machines, running, detail, output] = reads;
      if (list.status === 'fulfilled') setJobs(list.value);
      if (machines.status === 'fulfilled') setWorkers(machines.value);
      if (running.status === 'fulfilled') setActivity(running.value);
      if (detail.status === 'fulfilled') setJob(detail.value);
      if (output.status === 'fulfilled') setResults(output.value);
      const errors = reads.flatMap((read, i) => read.status === 'rejected' ? [`${['Jobs', 'Workers', 'Activity', 'Job details', 'Results'][i]}: ${(read.reason as Error).message}`] : []);
      setPollError(errors.join(' '));
      timer = setTimeout(poll, 1000);
    }
    void poll();
    return () => { pollGeneration.current++; clearTimeout(timer); };
  }, [connection, selectedId]);
  useEffect(() => { setQuote(null); }, [mode, source, instruction, sections]);
  function select(id: string, detail: Job | null = null) { if (id === selectedId) return; pollGeneration.current++; setSelectedId(id); setJob(detail); setResults(null); }
  async function submit(event: React.FormEvent) {
    event.preventDefault(); if (!connection || submitLock.current || ambiguous) return;
    setSubmitError(''); let payload;
    try { payload = createPayload(mode, source, instruction, sections); } catch (error) { setSubmitError((error as Error).message); return; }
    submitLock.current = true; setSubmitting(true); const current = generation.current;
    let submittingJob = false;
    try {
      const encoded = JSON.stringify(payload);
      if (identity?.auth_mode === 'controlled' && quote?.payload !== encoded) {
        const value = await request<CreditQuote>(connection, '/api/credits/quote', {method: 'POST', body: encoded});
        if (current === generation.current) setQuote({payload: encoded, value});
        return;
      }
      submittingJob = true;
      const created = await request<{job_id: string}>(connection, '/api/jobs', {method: 'POST', body: JSON.stringify(payload)});
      if (current === generation.current) { select(created.job_id); setQuote(null); }
    } catch (error) {
      if (current !== generation.current) return;
      const uncertain = submittingJob && (!(error instanceof ApiError) || error.status >= 500);
      setAmbiguous(uncertain); setSubmitError(uncertain ? 'Submission could not be confirmed. A job may already exist. Check recent jobs before submitting again.' : (error as Error).message);
    } finally { submitLock.current = false; setSubmitting(false); }
  }
  function download() {
    if (!results) return;
    const blobUrl = URL.createObjectURL(new Blob([JSON.stringify(results, null, 2)], {type: 'application/json'}));
    const anchor = document.createElement('a'); anchor.href = blobUrl; anchor.download = `job-${results.job_id}.json`; anchor.click(); setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
  }
  const visibleWorkers = workers.filter(worker => !(worker.status === 'OFFLINE' && !worker.device_id && workers.some(other => other.hostname === worker.hostname && other.device_id)));
  return <div className="shell"><header><a className="brand" href="/"><span className="logo">s/c</span> STRANDED COMPUTE</a><span className="edition">DNHACKS / 2026</span></header><main>
    <div className="intro"><div><p className="eyebrow">SHARED AI COMPUTE</p><h1>Your work.<br/><span>Powered by the network.</span></h1><p className="lede">Send documents and code to a connected compute worker.<br/>Follow execution and explore the results in one place.</p></div><div className="network" aria-hidden="true"><i/><i/><b>SC</b><i/><i/></div></div>
    <section className="panel"><div className="section-heading"><h2>Backend connection</h2><span className={`badge ${connection && !pollError ? 'good' : ''}`}>{connection ? pollError ? 'Connection interrupted' : 'Connected' : 'Not connected'}</span></div>
      <form onSubmit={connect}><div className="connection-form"><label>Backend URL<input type="url" required value={url} onChange={e => setUrl(e.target.value)} disabled={submitting || connecting}/></label><label>Account or demo token<input type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)} disabled={submitting || connecting}/></label><button disabled={connecting || submitting}>{connecting ? 'Connecting…' : 'Connect'}</button></div><label className="remember"><input type="checkbox" checked={remember} disabled={connecting || identity?.auth_mode === 'controlled'} onChange={e => { setRemember(e.target.checked); if (!e.target.checked) { try { sessionStorage.removeItem('sc-connection'); } catch {} } }}/> Remember demo connection in this tab after connecting</label></form>
      <p className="hint">Use Abel’s LAN address. {identity?.auth_mode === 'controlled' ? 'Account credentials stay in memory only.' : 'The demo token is browser-visible.'} {connection && `Active backend: ${connection.url}`}</p><p><a href={sharingUrl} target="_blank" rel="noopener noreferrer">Sharing and credits ↗</a><span className="hint"> · provider controls, worker access, and demo earnings</span></p>{connection && <button className="secondary" disabled={connecting || submitting} onClick={disconnect}>Disconnect and forget token</button>}{connectionError && <p className="error" role="alert">{connectionError}</p>}
    </section>
    {pollError && <p className="error" role="alert">{pollError} Some displayed data may be stale. Retrying automatically.</p>}
    <div className="workspace"><section className="panel composer"><h2>Create a job</h2><form onSubmit={submit}><label className="field">Task<select value={mode} disabled={submitting} onChange={e => { setMode(e.target.value as TaskType); setSubmitError(''); }}>{Object.entries(modes).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      {mode !== 'sentiment-classification' && <label className="remember"><input type="checkbox" checked={sections} disabled={submitting} onChange={e => setSections(e.target.checked)}/> Split into independent sections</label>}
      {sections && mode !== 'sentiment-classification' && <p className="notice">Put --- on its own line between sections. Each section becomes one task and returns its own result, not a combined document summary. {source.split(/\r?\n[ \t]*---[ \t]*\r?\n/).length} sections · at most 6,000 UTF-8 bytes per section. Workers pull tasks dynamically; the split between computers is not predetermined.</p>}
      <label htmlFor="source">{mode === 'coding-assistance' ? 'Code snippet' : mode === 'sentiment-classification' ? 'Text inputs — one per line' : 'Source document'}</label><p className="hint">{mode === 'sentiment-classification' ? 'Blank lines are ignored. Up to 1,000 inputs.' : sections ? 'Each marked section is one input. Paragraphs and formatting within sections are preserved.' : 'The entire source is one input. Paragraphs and code formatting are preserved.'}</p>
      <textarea id="source" value={source} onChange={e => setSource(e.target.value)} disabled={submitting} placeholder={mode === 'coding-assistance' ? 'Paste code to explain, review, or improve…' : 'Paste your source document here…'}/><p className="hint">{new TextEncoder().encode(source).length.toLocaleString()} UTF-8 bytes{mode !== 'sentiment-classification' && !sections && ' / 6,000 maximum'}</p>
      {['document-qa', 'coding-assistance'].includes(mode) && <label className="field">{mode === 'document-qa' ? 'Question (required)' : 'Request (optional)'}<textarea className="instruction" value={instruction} onChange={e => setInstruction(e.target.value)} disabled={submitting} placeholder="What would you like to know?"/><span className="hint">Up to 1,000 characters; source plus request up to 6,500 UTF-8 bytes.</span></label>}
      {submitError && <p className="error" role="alert">{submitError}</p>}{ambiguous && <button type="button" className="secondary" onClick={() => { setAmbiguous(false); setSubmitError(''); }}>I checked recent jobs — allow another submission</button>}
      {quote && <p className="notice" role="status">Reserve {quote.value.credits} demo credits for {quote.value.total_inputs} inputs. Accepted work is charged once; permanently failed inputs are refunded. Demo credits have no cash value. Confirm below to submit.</p>}
      <button className="submit" disabled={!connection || connecting || submitting || ambiguous || !source.trim()}>{submitting ? 'Working…' : identity?.auth_mode === 'controlled' ? quote ? `Reserve ${quote.value.credits} credits and submit →` : 'Review demo credit cost →' : `${modes[mode]} →`}</button><p className="hint">{connection ? 'The coordinator selects the configured model. A compatible worker must be online to execute the job.' : 'Connect to the backend to submit a job.'}</p>
    </form></section>
    <section className="panel"><div className="section-heading"><h2>Job progress</h2><span className="pill">↻ Every second</span></div>{job ? <><span className="badge">{job.status}</span><p className="job-id">{job.id}</p><p className="hint">{job.task_type} · {job.model_id ?? 'No model configured'}</p><div className="progress-number">{Math.round(job.progress_percentage)}<span>%</span></div><progress max="100" value={job.progress_percentage} aria-label="Successfully completed tasks"/><div className="metrics"><div><strong>{job.total_inputs}</strong><span>Inputs</span></div><div><strong>{job.completed_tasks}/{job.total_tasks}</strong><span>Tasks complete</span></div><div><strong>{job.failed_tasks}</strong><span>Tasks failed</span></div></div>{!job.model_id && <p className="notice">This job cannot run without a model pin. Configure the backend model and submit a new job.</p>}{job.model_id?.startsWith('simulation/') && <p className="notice">Simulation: results are fabricated for testing.</p>}{job.status === 'FAILED' && <p className="error">This job is final with failures. Successful partial results remain available below.</p>}</> : <div className="empty"><span>◎</span><h3>{selectedId ? 'Loading job…' : 'Ready when you are'}</h3><p>{selectedId ?? 'Submit work or select a recent job.'}</p></div>}</section></div>
    {job && results && <Distribution job={job} results={results} workers={workers} stale={!!pollError}/>}
    {selectedId && <section className="panel results"><div className="section-heading"><h2>Results</h2><button className="secondary" disabled={!results} onClick={download}>Download JSON</button></div>{results ? <><p className="hint">{results.is_final ? 'Final' : 'Partial'} results · {results.completed_inputs}/{results.total_inputs} inputs complete · {results.failed_inputs} inputs failed</p>{!results.results.length && <p className="notice">{results.is_final ? 'No successful results were returned.' : 'Waiting for the worker to return results.'}</p>}{results.results.map(item => <article className="result" key={item.index}><h3>Input {item.index + 1}</h3>{'text' in item ? <pre>{item.text}</pre> : 'label' in item ? <p>{item.label} · {(item.score * 100).toFixed(1)}% confidence</p> : <dl>{(['names','dates','amounts','action_items'] as const).map(key => <div key={key}><dt>{key.replace('_', ' ')}</dt><dd>{item[key].length ? <ul>{item[key].map((value, index) => <li key={index}>{value}</li>)}</ul> : 'None found'}</dd></div>)}</dl>}</article>)}{results.failed_tasks.map(task => <p className="error" key={task.task_id}>Inputs {task.input_start_index + 1}–{task.input_start_index + task.input_count}: {task.error_code}</p>)}{results.tasks.map(task => <p className="hint" key={task.task_id}>{task.worker_name ?? 'Unassigned'} · {task.status} · {task.attempt_count} attempts · {task.execution_time_ms == null ? 'Execution time unavailable' : `${task.execution_time_ms} ms`}</p>)}</> : <p className="hint">Loading results…</p>}</section>}
    <section className="panel recent"><div className="section-heading"><h2>Compute workers</h2><span className="hint">Up to 500 registrations</span></div><div className="worker-grid">{visibleWorkers.map(worker => {
      const live = worker.status !== 'OFFLINE' && !pollError;
      const metric = (value: number | null, unit: string) => live && value != null ? `${value.toFixed(1)} ${unit}` : 'Unavailable';
      const totals = activity?.worker_metrics.find(item => item.worker_id === worker.id);
      return <article className="worker-card" key={worker.id}><div className="section-heading"><h3>{worker.name}</h3><span className="badge">{worker.status}</span></div><p>{worker.cpu} · {worker.cpu_cores} CPU cores</p><p>{worker.gpu ?? 'GPU not reported'}{worker.gpu_core_count != null && ` · ${worker.gpu_core_count} GPU cores`}</p><p className="hint">{worker.model_id ?? 'No model registered'}<br/>{worker.supported_tasks.join(', ')}</p><dl><dt>CPU / memory utilization</dt><dd>{metric(worker.cpu_utilization, '%')} / {metric(worker.memory_utilization, '%')}</dd><dt>Available / total RAM</dt><dd>{metric(worker.ram_available_gb, 'GiB')} / {worker.ram_gb.toFixed(1)} GiB</dd><dt>Model GPU allocation</dt><dd>{metric(worker.gpu_model_memory_gb, 'GiB')}</dd><dt>Available dedicated VRAM</dt><dd>{worker.gpu_memory_kind === 'unified' ? 'Not applicable — shared memory' : metric(worker.gpu_available_gb, 'GiB')}</dd></dl>{worker.gpu_memory_kind === 'unified' && <p className="hint">Shared RAM is an estimate, not a guaranteed GPU allocation budget.</p>}<p className="hint">{totals ? `${totals.completed_tasks} tasks · ${totals.completed_inputs} inputs · average ${totals.average_execution_ms} ms per task` : 'No recorded completions for this worker ID.'}</p></article>;
    })}</div>{!visibleWorkers.length && <p className="hint">{!connection ? 'Connect to discover workers.' : pollError ? 'Worker information is unavailable.' : 'No workers registered.'}</p>}</section>
    <section className="panel recent"><div className="section-heading"><h2>Task activity</h2><span className="hint">{activity ? `${activity.active_tasks.length} active · ${activity.retries} retries` : 'Awaiting connection'}</span></div>{activity && <><p className="hint">Updated {new Date(activity.as_of).toLocaleTimeString()} · {Object.entries(activity.task_counts).map(([state, count]) => `${state}: ${count}`).join(' · ')}</p><div className="table-wrap"><table><thead><tr><th>Job / task</th><th>Worker</th><th>Status</th><th>Attempt</th><th>Execution</th><th>Queue / prior attempts</th></tr></thead><tbody>{Array.from(new Map([...activity.active_tasks, ...activity.recent_tasks].map(task => [task.task_id, task])).values()).map(task => <tr key={task.task_id}><td><button className="job-link" onClick={() => select(task.job_id)}>{task.job_id.slice(0,8)} ↗</button><div className="hint">{task.task_type}</div></td><td>{task.worker_name ?? 'Unassigned'}</td><td>{task.status}{task.error_code && <div className="hint">Last error: {task.error_code}</div>}</td><td>{task.attempt_count}</td><td>{task.elapsed_seconds == null ? 'Unavailable' : `${task.elapsed_seconds}s`}</td><td>{task.queue_seconds == null ? 'Unavailable' : `${task.queue_seconds}s`}</td></tr>)}</tbody></table></div>{!activity.recent_tasks.length && !activity.active_tasks.length && <p className="hint">No task activity yet.</p>}</>}</section>
    <section className="panel recent"><div className="section-heading"><h2>Recent jobs</h2><span className="hint">Latest 100</span></div>{jobs.length ? <div className="table-wrap"><table><thead><tr><th>Job</th><th>Task</th><th>Status</th><th>Inputs</th><th>Progress</th><th>Created</th></tr></thead><tbody>{jobs.map(item => <tr key={item.id} className={selectedId === item.id ? 'selected' : ''}><td><button className="job-link" onClick={() => select(item.id, item)}>{item.id.slice(0,8)} ↗</button></td><td>{item.task_type}</td><td>{item.status}</td><td>{item.total_inputs}</td><td>{Math.round(item.progress_percentage)}%</td><td>{new Date(item.created_at).toLocaleString()}</td></tr>)}</tbody></table></div> : <p className="hint">{!connection ? 'Connect to load jobs.' : pollError ? 'Jobs are unavailable.' : 'No jobs yet.'}</p>}</section>
    </main><footer><span>STRANDED COMPUTE</span><span>More machines. One shared workload.</span></footer></div>;
}
createRoot(document.getElementById('root')!).render(<StrictMode><App/></StrictMode>);
