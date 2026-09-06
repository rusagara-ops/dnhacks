# Demo handoff: Abel, Kevin, Ronald

## Current demo architecture

Abel's 24 GB Mac runs the coordinator, Supabase-backed queue, and Gemma 3 12B through Ollama on its Apple GPU. Kevin and Ronald use the website as clients. This demonstrates remote inference from multiple laptops; only registered compute workers execute tasks. Do not start old Qwen workers on the client laptops.

Working branch: `abel-backend`. Before editing, fetch and inspect the latest changes. Preserve local work. Coordinate integration through PRs; do not force-push or merge unfinished frontend changes over the demo.

## Implemented in Abel's branch

- Summary, document Q&A, structured information extraction, and coding assistance.
- Model-pinned jobs, single-task worker leases, heartbeats, retries, and persisted results.
- Stable worker installation IDs: restarting reconnects to the same row. A local lock prevents two processes using the same installation simultaneously.
- Live GPU/shared-memory telemetry and CPU/RAM utilization.
- Authenticated `/api/activity`: current assignments, recent tasks, timings, retry totals, and worker completion metrics.
- Dashboard task ownership, recent-job reopening, result JSON download, and better connection controls.
- Optional token remembering uses sessionStorage for this tab, never localStorage. Disconnect removes it. A shared demo token is not individual user authentication.

Legacy worker rows and their historical results are preserved. The dashboard hides redundant offline legacy registrations by hostname and prefers modern device identities. Metrics on a modern worker cover that worker ID; historical registrations are not silently merged into its totals.

## Abel — backend and compute owner

Own `backend/app/`, `backend/migrations/`, and the running coordinator configuration. Keep database schema changes through Alembic only.

Next tasks:
1. Confirm migration `78ccab156bc1` is applied and one `Abel-Mac` appears after repeated restarts.
2. Keep the coordinator, Ollama Terminal, and Gemma worker running for the rehearsal.
3. Review the final integration PRs and preserve all four task contracts.
4. Own any backend bug fixes discovered in the three-laptop rehearsal.

Acceptance: requests from both client laptops complete through the same GPU worker; results remain available after page refresh through Recent jobs; retries preserve partial-result semantics.

## Kevin — worker reliability and demo verification owner

Own `worker/` and worker-focused tests. Coordinate with Abel before restarting his compute worker or changing model settings. Do not edit Ronald's frontend or alter database schemas independently.

Next tasks:
1. Test repeated worker stops/restarts and verify its worker ID stays constant.
2. Confirm a second process from the same installation is rejected by the local lock.
3. Verify heartbeats continue during coding requests and that GPU allocation is reported.
4. Prepare a small set of English examples for each task type, including one unanswerable document question.
5. Run a controlled disconnect/recovery test with Abel; record job IDs and observed outcomes.

Acceptance: no duplicate modern compute card, no silent CPU fallback, no lost successful results, and a reproducible startup/recovery checklist. Do not copy `worker/.cache/` to another computer; it contains the installation identity and local files.

## Ronald — frontend and client experience owner

Own `frontend/`. Treat `backend/demo/` as a working reference. Build the main frontend against the contracts below; coordinate with Abel before replacing the demo or modifying backend routes.

Next tasks:
1. Port task selection, source/request fields, structured extraction output, and preserved code formatting into the main frontend.
2. Port compute cards, active task ownership, recent jobs, and result download.
3. Port connection handling with explicit tab-only remembering and Disconnect. Never embed the token or place it in a URL.
4. Test on Kevin's laptop and a narrow/mobile-sized viewport, including offline, wrong-token, empty-result, queued, and failed states.
5. Make a PR with screenshots and a short integration checklist.

Acceptance: all four tasks work against Abel's coordinator; switching modes preserves pasted content; model output is rendered as text without execution; offline telemetry is unavailable rather than falsely zero.

## Shared API contract

All `/api/*` routes use `Authorization: Bearer <API_TOKEN>`. Get the token privately from Abel. Never share `DATABASE_URL`, commit `.env`, or include tokens in screenshots or reports.

- `POST /api/jobs`: `{task_type, inputs: [source], instruction?}`. Types: `summarization`, `document-qa`, `information-extraction`, `coding-assistance`. Q&A requires `instruction`; coding optionally accepts it.
- `GET /api/jobs?limit=10`: recent jobs for reopening persisted results.
- `GET /api/jobs/{id}/results`: status, counters, results, and task attribution.
- `GET /api/workers`: stable `id`, optional `device_id`, presence, hardware and live telemetry.
- `GET /api/activity`: `as_of`, `active_tasks` (up to 100), `recent_tasks` (up to 30), `task_counts`, `retries`, and `worker_metrics`.
- Worker registration adds optional UUID `device_id`. Updated workers persist it in their ignored state directory and reuse it.

`active_tasks`/`recent_tasks` include task/job IDs, task type, worker ID/name, status, attempt count, input count, timestamps, elapsed execution seconds, queue/previous-attempt seconds, and the last error code. Timing for retried tasks includes prior attempts in the pre-current-execution interval; do not label it pure queue latency. Error codes may describe earlier recovered attempts.

Extraction results are `{index,names,dates,amounts,action_items}` with string arrays. Other new modes return `{index,text}`. The API retains sentiment compatibility. Read `backend/README.md` for limits and details.

## Rehearsal together

1. Abel confirms `/ready` and the GPU worker.
2. Kevin opens `http://ABEL_LAN_IP:8000/demo/`, Ronald opens the same address, and both connect using the token.
3. Submit different task types together; watch one execute and the other queue.
4. Reopen finished jobs and compare stored results with the original requests.
5. Test one controlled worker restart, then confirm the same worker identity and recovered work.
6. Keep a prepared example for each mode and keep the compute Mac plugged in and awake.
