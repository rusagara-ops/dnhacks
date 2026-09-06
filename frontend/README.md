# Frontend applications

- **Demo dashboard:** [`demo/index.html`](demo/index.html), served by the coordinator at `http://localhost:8000/demo/`. This is the dashboard with the compute map, machine cards, and model selector. Edit `demo/app.js`, `demo/locations.js`, and `demo/style.css`. Start the coordinator from `backend/`; this dashboard calls the API on the same origin and needs no separate frontend server.
- **Ronald’s React dashboard:** `src/`, served by Vite at `http://localhost:5173/`. Its setup instructions follow.
- **Sharing and credits:** [`demo/sharing.html`](demo/sharing.html), served at `/demo/sharing.html` on the coordinator and linked from both dashboards. No frontend build or separate server is needed for this page.

The demo lives entirely under `frontend/demo/`; the backend only mounts its static files. The public `/demo/` URL is unchanged.

# Ronald — Stranded Compute frontend

React + TypeScript + Vite. Requires Node.js 22.18+ (or Node.js 24).

```bash
cd frontend
npm ci
npm run dev
```

Open the URL printed by Vite (normally http://localhost:5173). Enter Abel's backend origin (`http://<ABEL_LAN_IP>:8000`) and shared demo token, then Connect. Abel must include this frontend origin in backend `CORS_ORIGINS`.

Connection settings stay in memory by default. The explicit remember checkbox saves them in sessionStorage for this tab after a successful connection. Unchecking removes saved settings; Disconnect clears the token and loaded backend data. No database credentials belong in this application. The shared token is visible to the browser user.

In `AUTH_MODE=controlled`, connect with an **account token**, not a worker credential. Remembering tokens is disabled and any old remembered token is removed after connecting. Both job dashboards first show the server's demo-credit quote; a second click confirms the reservation and submission. Changing an input requires a new quote. Ordinary demo mode remains unmetered and retains its existing submission flow. A `/api/me` 404 is treated as an older demo backend; other authentication errors are not ignored.

## Sharing dashboard

Open `/demo/sharing.html` on Abel's coordinator. This page never stores credentials in browser storage or transfers them from the job dashboard. Enter the account token explicitly. New account and worker credentials are masked, shown only once, and cleared when you disconnect or leave. Use trusted HTTPS to protect credentials and task data on the network.

- Provider settings pause/resume **new assignments**, restrict task types, set a concurrency ceiling of one or two, and set a minimum free-RAM threshold. Existing tasks finish normally. Optional weekly windows use Monday–Sunday in **UTC**; split overnight windows at midnight, with `24:00` allowed as an end time. These settings are admission rules, not OS/GPU isolation or resource reservations.
- Reliability displays accepted tasks, failed/expired attempts, and the worker-reported mean execution duration recorded since tracking was enabled. It is not an independent benchmark, network-latency estimate, result-quality score, or security certification.
- Demo credits show available/reserved balances, earnings, and a paginated ledger. They have no cash value or payouts. The coordinator controls pricing, reservations, settlement, and refunds.
- Worker access binds a new credential to the installation UUID obtained with `worker/.venv/bin/python worker/run.py --show-device-id`. A revoke requires an explicit confirmation click and blocks subsequent worker API requests. Pause and drain work first when possible.
- Administrators enroll accounts, grant demo credits, adopt unowned idle demo workers, inspect credential metadata, and issue replacement account tokens without creating a new balance or identity. Replacement tokens do not automatically revoke previous ones. The setup token can create the first administrator; reconnect using the issued account token before operating jobs or machines.

Provider controls also work in demo mode. Accounts, scoped credentials, and balances are hidden until the backend enables controlled mode. Backend ownership checks are authoritative; hiding a button does not enforce access control. Providers can still inspect the plaintext inputs their own machines process.

## Supported workflows

- Summarization: one complete document, including paragraph breaks.
- Document Q&A: source document plus required question.
- Information extraction: names, dates, amounts, and action items displayed as lists.
- Coding assistance: code plus optional request; output preserves whitespace and is never executed.
- Legacy sentiment classification: one input per nonblank line.

Switching modes preserves source and request text; irrelevant instructions are omitted from submissions. Source is retained after submission. New modes allow at most 6,000 UTF-8 bytes per source; source plus request is limited to 6,500 bytes, and requests to 1,000 Unicode characters. Sentiment retains the backend's original batch limits. The coordinator pins the model; this frontend does not invent a client-selected model contract.

The dashboard polls jobs, workers, activity, and selected-job results one second after the previous refresh finishes. Endpoint failures are surfaced independently while successful reads continue. Existing data is marked potentially stale; live worker measurements show unavailable when disconnected/stale/offline. Apple unified memory is labeled as shared RAM, not dedicated VRAM. Up to 500 workers and the latest 100 jobs are loaded. Redundant offline legacy registrations with a modern identity on the same hostname are hidden; historical metrics are not merged.

Results include partial/final status, completed and failed input counts, task attribution, errors, and a JSON download. Recent jobs can reopen persisted results after refresh. Task activity includes ownership, attempts, execution time, queue/prior-attempt time, and retries. All output is rendered as text, never HTML.

Submissions are never automatically retried. After an uncertain outcome, check recent jobs and explicitly acknowledge before resubmitting. Job status determines finality; a failed job can finish below 100% and retain successful results.

## Verification

```bash
npm test
npm run build
```

The browser suite includes both dashboards and the sharing page. Install dependencies in `frontend/` and `frontend/demo/`, then run `npm test --prefix demo` from `frontend/` with Playwright Chromium installed. The React tests start an ephemeral local Vite server. Coordinator responses and map tiles are mocked; these tests do not prove distributed execution on Abel's machines.

Validation tests cover Unicode/UTF-8 boundaries, document/code preservation, mandatory questions, irrelevant instruction omission, and legacy sentiment compatibility.

Live rehearsal (requires Abel's coordinator and compatible worker):

1. Connect with correct token; verify wrong-token and unavailable-backend errors.
2. Submit each of the four new modes and watch QUEUED → RUNNING → COMPLETED.
3. Switch modes and verify pasted source/request remains intact.
4. Reopen jobs, inspect text/extraction/code results, and download JSON.
5. Observe a controlled worker disconnect: telemetry becomes unavailable, retries/ownership update, and successful partial results remain visible.
6. Verify remember/uncheck/disconnect behavior and layout at a narrow viewport.

A live inference rehearsal is still required; passing local tests/build does not verify Abel's runtime or network. Contracts: [backend README](../backend/README.md) and [team handoff](../backend/TEAM_HANDOFF.md).

## Per-job work distribution

Select a job to see the work distribution matrix: completed tasks / total job tasks, percentage of the job, active/queued/failed tasks, completed inputs, and total/average recorded successful execution time per worker ID. All currently loaded workers appear, including zero-contribution workers, with task/model/revision compatibility. Expand the chunk table for exact task IDs, input ranges, assignment owners, and attempts.

To create a ten-task document job, enable **Split into independent sections** and place `---` on its own line between ten sections. This uses the existing batch API; no backend deployment is needed. Each section has a 6,000-byte limit and produces its own independent result. This does not synthesize a final combined summary. A normal whole-document submission remains one task. Compatible workers dynamically pull tasks; an 8/2 allocation is observable, not guaranteed.

The matrix measures accepted completions rather than all execution attempts. The current backend does not retain prior worker attribution in its results response after reassignment, so previous failed execution cannot be assigned to a computer. Current compatibility is not a historical scheduling audit. Worker results and attribution are also available in the existing JSON download.
