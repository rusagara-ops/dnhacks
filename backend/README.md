# Abel — Coordinator Backend

> This backend/worker branch excludes the demo UI. References to `/demo/` describe the companion UI on `abel-backend`; use `/docs` to inspect these APIs independently.

Owner: Abel. The coordinator runs on Abel's laptop for the demo. It manages worker presence, jobs, task assignment, retries and results. Kevin's worker performs inference; Ronald's frontend calls this HTTP API. Neither teammate needs the database password.

## Current implementation (v0.5)

Implemented:

- FastAPI application with interactive `/docs` and `/openapi.json`.
- Environment configuration and bounded PostgreSQL connection pooling.
- Versioned Alembic migration for `coordinator.workers`.
- Worker registration, paginated listing and heartbeat updates.
- Atomic job creation with 25-input task chunks and preserved input indexes.
- Job lookup and paginated listing with task counts and progress.
- Worker task pull with database row locking, one active assignment per worker, model matching and retry-safe assignment responses.
- `AVAILABLE`, `BUSY`, `OFFLINE` presence derived from heartbeat age.
- Optional shared demo bearer token and configured CORS origins.
- Liveness and database readiness endpoints; read-only connection check.

Implemented in v0.4: completion/failure endpoints, result storage, assignment-specific lease renewal, offline/expired-task recovery, and partial job results. Implemented in v0.5: dashboard stats and an HTTP-only simulated worker. Real inference integration remains pending. Worker registration/heartbeat/pull and job endpoints are implemented. Completion, failure, job result and stats interfaces are implemented. No model or model revision has been chosen yet.

Database verification (2026-09-05): the worker migration is applied to the shared Supabase project. SELECT 1, readiness, registration, persistence across app restarts/new connection pools, heartbeat BUSY/AVAILABLE transitions, and enabled worker-table RLS were verified. The separate disposable-database integration test remains available. A simulated worker named Abel-Persistence-Test was retained and will become OFFLINE when its heartbeats stop.

## Run on Abel's laptop

Use Python 3.11+ (development was tested on Python 3.14). From the repository root:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

Edit `.env` locally:

- `DATABASE_URL`: a PostgreSQL connection URI from Supabase **Connect**. Use `postgresql+psycopg://...`; ordinary `postgresql://...` is normalized automatically. URL-encode special password characters and include `sslmode=require` for Supabase. Prefer direct connections when reachable or the session pooler on IPv4-only Wi-Fi. MCP login does not configure this application credential.
- `API_TOKEN`: replace the example with a random shared demo token before enabling LAN access. All `/api/*` requests then require `Authorization: Bearer <token>`. If unset, the API has no authentication; use that only for local development. This is a trusted-team demo token, not per-user authorization.
- `CORS_ORIGINS`: JSON array of frontend origins, including scheme and port. Add Ronald's actual frontend origin if it differs from the defaults.
- Heartbeats default to 5 seconds; workers become offline after more than 15 seconds without a heartbeat.

Check connectivity before migrating:

```bash
python -m app.db.check
alembic upgrade head
uvicorn app.main:app --reload
```

The migration creates the private `coordinator` schema. Run migrations and the demo backend as the table owner. RLS is enabled with no public policies; the table owner can access it. Do not expose this schema through the Supabase Data API. Future deployment with a separate runtime role requires explicit grants/policies.

No schema changes happen automatically on API startup. Keep future schema changes in Alembic migrations. Do not use `create_all()` to update a shared database.

Open http://127.0.0.1:8000/docs. Use **Authorize** to enter the demo token when configured. `/health` indicates the process is alive. `/ready` also checks the database connection and all coordinator tables. A missing connection or migration returns 503, not a false readiness success.

For the two-laptop demo, after localhost works:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Kevin and Ronald use `http://<ABEL_LAN_IP>:8000` as the backend base URL. On their laptops, `localhost` refers to their own machine, not Abel's. Confirm campus Wi-Fi permits peer connections before the demo. Use a trusted network; this LAN HTTP setup is not a public deployment.

## Implemented worker API — Kevin

All request/response bodies use JSON. Timestamps are timezone-aware. IDs are UUID strings. Utilization is a percentage from 0 to 100. Memory values use GB. Unknown input fields and invalid values return 422.

### POST /api/workers/register

Register after the worker is ready. Each successful request creates a new worker ID; persist that ID for heartbeats during the process lifetime. Registration retries are not idempotent yet, and a restart can leave an old row that becomes offline.

```json
{
  "name": "Kevin-Laptop",
  "hostname": "kevin-laptop",
  "cpu": "Apple Silicon",
  "cpu_cores": 8,
  "ram_gb": 16,
  "gpu": null,
  "gpu_memory_gb": null,
  "supported_tasks": ["sentiment-classification"],
  "model_id": null,
  "model_revision": null,
  "benchmark_score": 1
}
```

`model_id` and `model_revision` are optional for registration, but required before receiving assignments. `benchmark_score` defaults to 1 and is currently informational.

Response: **201 Created**.

```json
{"worker_id": "<uuid>", "heartbeat_interval_seconds": 5}
```

### POST /api/workers/{worker_id}/heartbeat

```json
{"cpu_utilization": 35.2, "memory_utilization": 41.0, "active_tasks": 0}
```

Response: **200 OK**, `{"status":"ok"}`. An unknown worker returns 404. `active_tasks` must be 0 or 1 for the MVP.

Continue sending heartbeats independently of the inference loop. A fresh heartbeat restores an offline worker's presence. When idle, use the simple heartbeat above. While executing, send `task_id` and `assignment_id` with `active_tasks: 1`:

```json
{"cpu_utilization":35.2,"memory_utilization":41.0,"active_tasks":1,"task_id":"<uuid>","assignment_id":"<uuid>"}
```

The response includes `lease_expires_at`. Both IDs are required together. An assignment heartbeat renews only the current unexpired lease and moves the task to RUNNING. A stale assignment returns 409. Stop submitting results for a rejected assignment and resume idle heartbeats/polling. Ordinary heartbeats update presence but do not renew a task lease.

### GET /api/workers?limit=100&offset=0

Returns a JSON array, newest registrations first. `limit` is 1–500; `offset` is nonnegative.

Each item contains the registration fields plus `id`, `status`, `cpu_utilization`, `memory_utilization`, `active_tasks`, `last_heartbeat`, `created_at`, and `updated_at`.

- `OFFLINE`: last heartbeat is older than the configured timeout.
- `BUSY`: heartbeat is recent and `active_tasks` is 1.
- `AVAILABLE`: heartbeat is recent and `active_tasks` is 0.

Status is computed when read, so dashboard polling does not write to the database. Presence does not yet guarantee the worker has the required inference model.

## Frontend integration — Ronald

Start with `/health`, `/ready`, `GET /api/workers`, `POST /api/jobs`, `GET /api/jobs` and `GET /api/jobs/{job_id}`. Polling workers every second is fine for the demo. Use the exact property names above (`ram_gb`, `benchmark_score`, etc.). Display connection errors separately from an empty worker list.

When configured, send the shared demo token in the Authorization header. Do not put a database password or Supabase service-role key in frontend code. The shared demo token is visible to the browser user; this MVP assumes trusted teammates.

## Job and task API — implemented

Job submission, listing, lookup, task assignment, completion, failure and results are implemented. Kevin still needs to confirm the model ID, pinned revision, token limit and truncation behavior. All workers must run the same model/revision. CPU execution is required; GPU use is optional.

### POST /api/jobs

```json
{
  "task_type": "sentiment-classification",
  "inputs": ["I love this.", "This is terrible."],
  "optimization": "fastest"
}
```

Implemented: reject empty/blank inputs and unsupported task types/optimization values with 422; create the job and its tasks atomically. Each task contains at most 25 inputs. Limits: 1–1,000 inputs, at most 10,000 characters each, and at most 1,000,000 combined UTF-8 text bytes. Original text and indexes are preserved.

Response: **201 Created** with a `Location: /api/jobs/<uuid>` header:

```json
{"job_id":"<uuid>","status":"QUEUED","total_inputs":100,"total_tasks":4}
```

Each POST creates a new job. Submission idempotency is not implemented, so do not automatically retry an ambiguous submission without checking the job list.

### GET /api/jobs and GET /api/jobs/{job_id}

List returns a JSON array, newest first, with `limit` (default 100, maximum 500) and `offset` (default 0). Lookup returns one object; a missing UUID returns 404 and malformed UUID returns 422. Both require the same configured demo token as workers.

```json
{
  "id":"<uuid>",
  "task_type":"sentiment-classification",
  "optimization":"fastest",
  "status":"QUEUED",
  "total_inputs":100,
  "total_tasks":4,
  "completed_tasks":0,
  "failed_tasks":0,
  "progress_percentage":0.0,
  "created_at":"2026-09-05T20:00:00Z",
  "started_at":null,
  "completed_at":null
}
```

`progress_percentage` is 0–100, calculated from successfully completed tasks. It may be below 100 for a final failed job; use status to determine finality. Jobs move to RUNNING on their first assignment. Jobs become terminal once every task completes or permanently fails. No raw input text is returned by these dashboard reads.

### Task scheduling behavior
 `fastest` means eligible workers pull the oldest queued task; no benchmark optimizer is promised.

### POST /api/workers/{worker_id}/next-task — implemented

```json
{
  "task": {
    "task_id": "<uuid>",
    "job_id": "<uuid>",
    "assignment_id": "<uuid>",
    "lease_expires_at": "2026-09-05T18:00:30Z",
    "task_type": "sentiment-classification",
    "model_id": "<agreed-model-id>",
    "model_revision": "<pinned-revision>",
    "inputs": [{"index": 0, "text": "I love this."}]
  }
}
```

No work returns `{"task":null}`. Poll only while idle, with a short delay when no work is available. The backend enforces one active assignment per worker and selects eligible tasks with a database transaction and `FOR UPDATE SKIP LOCKED`.

Indexes refer to positions in the original job. Each assignment receives a new ID. `TASK_LEASE_SECONDS` defaults to 300 (allowed 30–3600). Retrying the pull while an assignment is live returns the same task, assignment ID and expiry without consuming another attempt. Treat that as the same work; do not launch duplicate inference. Heartbeat with the matching task/assignment IDs extends the lease up to the maximum runtime. Expired or offline-worker assignments are recovered before task pulls and by a periodic loop (default every five seconds). A maximum of three assignments is allowed; attempts increment only on assignment. Two backend instances can safely run recovery concurrently.

Unknown worker → 404. Offline worker → 409 (send a heartbeat first). Missing loaded-model registration → 409. Missing coordinator model configuration → 503. No compatible work, or a worker reporting busy without a recorded assignment → `{"task":null}`. A recorded active assignment takes precedence over stale heartbeat `active_tasks` values.

Configure `INFERENCE_MODEL_ID` and `INFERENCE_MODEL_REVISION` together in `.env` **before creating execution jobs**. The backend snapshots those values onto each new job and returns them in job reads. Both are intentionally unset until Kevin confirms the model. Jobs submitted without a model remain visible but unschedulable; submit a new job after configuration rather than silently changing old jobs. Workers receive only jobs matching their loaded model/revision and supported task type. Changing configuration does not change existing job pins.

### POST /api/tasks/{task_id}/complete — implemented

```json
{
  "worker_id": "<uuid>",
  "assignment_id": "<uuid>",
  "results": [{"index": 0, "label": "POSITIVE", "score": 0.998}],
  "execution_time_ms": 812
}
```

Labels are `POSITIVE` or `NEGATIVE`; score is the model score for that label in [0, 1]. Return exactly one result per assigned index. Execution time includes preprocessing and inference, excluding model loading and network calls.

The completion transaction validates the current assignment, inserts a unique result per task and updates job progress atomically. Retrying an accepted completion is safe; expired/superseded assignments return 409. Workers must not report inference failure merely because a completion upload timed out: retry the same completion first.

### POST /api/tasks/{task_id}/fail — implemented

```json
{
  "worker_id": "<uuid>",
  "assignment_id": "<uuid>",
  "error": {"code": "INFERENCE_ERROR", "message": "Model execution failed"}
}
```

A chunk succeeds or fails as a whole. Maximum three assignments per task; increment attempts only upon assignment, never again on timeout. Old assignments cannot fail a newly assigned task.

### GET /api/jobs/{job_id}/results — implemented

Returns `job_id`, `status`, `is_final`, `total_inputs`, `completed_inputs`, `failed_inputs`, ordered `results` (`index`, `label`, `score`), and `failed_tasks` (`task_id`, `input_start_index`, `input_count`, `error_code`). Partial results are available while processing. Predictions remain in original input order even when tasks finish out of order.

`GET /api/stats` is implemented; see the dashboard statistics section below.

Job statuses: `QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`.

If a task permanently fails, continue the remaining tasks. Once all tasks are terminal, mark the job `FAILED` if any failed; otherwise `COMPLETED`. Results remain available for successful tasks. Return `is_final: false` while processing and `is_final: true` at the end. Never invent predictions for failed inputs. Distinguish completed input counts from completed task counts.

## Tests and development

```bash
python -m pytest -q
```

The PostgreSQL integration test is skipped unless `TEST_DATABASE_URL` is set. To run it, provision a **disposable** PostgreSQL database (never the shared project), then:

```bash
DATABASE_URL="$TEST_DATABASE_URL" alembic upgrade head
python -m pytest -q
```

It covers registration, persistence, heartbeat, offline detection, reconnection and validation. It creates and removes its own worker row. Unit/API tests cover authentication, configuration, CORS, state calculation and sanitized database errors. Dependency versions are pinned in the requirements files; `requirements.lock` records the tested full dependency set.

Primary files:

- `app/main.py`: app setup, auth, CORS and health checks.
- `app/core/config.py`: environment settings.
- `app/db/database.py`: connection pool and per-request sessions.
- `app/db/check.py`: read-only database connectivity check.
- `app/models/worker.py`: persisted worker fields and constraints.
- `app/schemas/worker.py`: validated API fields.
- `app/api/workers.py`: implemented worker routes.
- `app/services/worker_service.py`: registration and presence logic.
- `migrations/`: reproducible schema history.

Work on `abel-backend`, make focused commits and coordinate changes to the API examples before Kevin or Ronald depends on them. Next milestone: Kevin confirms model ID/revision and we run his real worker on two laptops; Ronald can integrate the implemented result endpoints.


## Job milestone verification (2026-09-05)

Migration `1781ed678f6b` adds `coordinator.jobs` and `coordinator.tasks`, including foreign keys, uniqueness/check constraints, indexes and RLS. `task_results` was added in v0.4. Assignment IDs and lease fields are populated by the task pull endpoint.

Automated PostgreSQL tests in `tests/test_jobs_postgres.py` create a uniquely named temporary schema and roll back all changes, leaving application rows untouched. They verify the exact migration SQL, real API creation/read behavior, chunk ordering, pagination, constraints, RLS and atomic rollback after an injected task-insert failure. Run them with a configured `TEST_DATABASE_URL`:

```bash
python -m pytest tests/test_jobs_postgres.py -q
```

A live coordinator-schema smoke test also verified 100 inputs → four queued tasks, reads across a new app/connection pool and RLS. The synthetic job and its tasks were removed afterward. Credentials remain in the ignored local `.env`.


## Assignment verification

`tests/test_scheduler_postgres.py` uses independent PostgreSQL connections and uniquely named temporary schemas, cleaned up afterward. It exercises simultaneous pulls for one task, duplicate pulls from the same worker, two workers claiming distinct tasks, model filtering, empty queues, offline workers and expired assignments. Never run it with another scheduler pointed at its generated test schema.

Migration `9e9ad9dc65c4` adds model pins to jobs and a partial unique index preventing more than one ASSIGNED/RUNNING task per worker. Existing jobs are not assigned an invented model. `coordinator.task_results` is now added by migration `7e2242ffb4de`. Its task ID is the primary key, enforcing one accepted result per task.

Verification: 25 unit/API tests and eight PostgreSQL tests passed for this milestone. A live HTTP smoke test confirmed assignment, repeat-pull stability and the job RUNNING transition; synthetic data was removed.


## Completion and recovery details (v0.4)

Completion returns `{"status":"completed"}`; a repeated completion for the same accepted assignment returns `{"status":"already_completed"}`. The first accepted result wins. Exactly one valid prediction per assigned index is required; missing/duplicate/foreign indexes return 422. Model labels must be POSITIVE/NEGATIVE and scores finite in [0,1]. A result, task state and job counter are committed in one transaction.

Failure returns `requeued` or `failed`; retrying the most recently recorded failure returns `already_failed`. Superseded assignment reports cannot modify newer work. Recovery follows the same retry limit as explicit failure. It releases worker capacity, clears assignment ownership, and either requeues work or marks it permanently failed. The job continues other tasks and finishes FAILED with successful partial results when any task permanently fails.

`RECOVERY_INTERVAL_SECONDS` defaults to 5. `TASK_MAX_RUNTIME_SECONDS` defaults to 1800 and must be at least TASK_LEASE_SECONDS (default 300). Renewal never extends an assignment beyond its maximum runtime. These are per-assignment limits, reset on retry. Old worker registrations remain visible as OFFLINE.

The periodic recovery loop runs with the API process and stops on shutdown. Pull requests also recover expired work. No Redis or separate scheduler process is required. API request handlers use a consistent worker → task → job write-lock order. Readiness now checks the result table as well.

No `/start` call is required: assignment is ASSIGNED, and an assignment-specific heartbeat marks it RUNNING. A worker can also complete an ASSIGNED task directly if it finishes before the next heartbeat.

Lifecycle verification: 48 automated checks passed across unit/API validation and isolated PostgreSQL tests. A live HTTP test also passed completion, duplicate completion, lease renewal, periodic background recovery, retry exhaustion, ordered partial FAILED results, persistence across app restarts, and result-table RLS. Only synthetic verification rows were removed afterward. Real model execution on two laptops remains to be tested.


## Dashboard statistics — Ronald

`GET /api/stats` requires the configured bearer token and returns one consistent database snapshot:

```json
{
  "workers_online": 2,
  "workers_available": 1,
  "workers_busy": 1,
  "jobs_queued": 0,
  "jobs_running": 1,
  "jobs_completed": 2,
  "jobs_failed": 0,
  "tasks_completed": 8,
  "total_inferences": 200
}
```

Worker counts exclude timed-out registrations. AVAILABLE/BUSY use the heartbeat-reported active-task count, matching the worker-list API. `total_inferences` counts accepted input predictions, not task attempts, model loads, retries or failed inputs. Simulated predictions count too; this is not a measure of verified real model execution. Job/task counters cover the whole repository database, including any retained demo jobs. Empty databases return zeros. Poll once per second for the demo.

## Simulated worker — test without Kevin

This script generates deterministic fake predictions (alternating labels by input index, score 0.5). It is not sentiment inference. Its fixed model is `simulation/sentiment`, revision `v1`, so it cannot claim jobs pinned to a real model.

Install the backend development dependencies, then start a simulation coordinator from `backend/`:

```bash
source .venv/bin/activate
INFERENCE_MODEL_ID=simulation/sentiment INFERENCE_MODEL_REVISION=v1 uvicorn app.main:app --host 127.0.0.1 --port 8000
```

These command-scoped settings do not edit `.env`. The coordinator uses the configured database and creates persistent demo data. Stop any existing server on port 8000 first. Old jobs without these exact model pins are not eligible.

In each worker terminal, from `backend/`:

```bash
source .venv/bin/activate
export API_TOKEN='<same demo token configured for the backend>'
python -m scripts.simulated_worker --name Simulator-A --max-tasks 100 --delay 2
```

Start a second terminal with `--name Simulator-B`. The worker reads only the API_TOKEN environment variable; it does not require a database password or Supabase credentials. `httpx` is included in `requirements-dev.txt`.

Create a job using `/docs` (Authorize with the same demo token), or:

```bash
curl -X POST http://127.0.0.1:8000/api/jobs   -H "Authorization: Bearer $API_TOKEN"   -H 'Content-Type: application/json'   -d '{"task_type":"sentiment-classification","inputs":["demo input one","demo input two"],"optimization":"fastest"}'
```

For both workers to participate, submit more than 25 inputs so there is more than one task. A two-input example creates just one task. Use the returned job ID with `GET /api/jobs/{id}/results` and observe `/api/stats`.

The simulator sends independent heartbeats during its delay, includes assignment IDs for renewal, retries ambiguous result uploads with the same payload, and discards results after a stale-assignment response. It exits after 30 seconds with no work by default; increase `--idle-timeout` if preparing a demo slowly. `--max-tasks` bounds the number of claims processed by that process. A repeated assignment response must never trigger parallel execution of the same task.

### Recovery demonstration

1. Create a simulation job with one task.
2. Run `python -m scripts.simulated_worker --name Crash-Test --crash-after-claim`.
3. It exits with code 17 after claiming, without sending a result or more heartbeats.
4. Run `python -m scripts.simulated_worker --name Survivor --max-tasks 1 --idle-timeout 60`.
5. After the configured worker timeout (default 15 seconds) and recovery interval, Survivor receives the work and finishes it.

To exercise explicit failures, use `--fail-tasks --max-tasks 3` on a new one-task simulation job. Three failed assignments exhaust retries and produce FAILED with no predictions. No database edits are needed for either demonstration.

For another laptop, run the coordinator with `--host 0.0.0.0` and pass `--url http://<ABEL_LAN_IP>:8000` to the simulator. This checks the network/HTTP workflow only; final real inference still needs Kevin's worker.

### Automated simulator verification

`tests/test_simulator_postgres.py` starts a real HTTP server and separate worker processes against a uniquely named isolated PostgreSQL schema. It tests two workers completing 100 inputs, crash recovery without manually changing database rows, failure exhaustion, authorization, and stats counts. It drops only its generated test schema afterward. Set TEST_DATABASE_URL to opt in:

```bash
python -m pytest tests/test_simulator_postgres.py -q
```

Simulator milestone verification: 36 checks passed (32 existing unit/API checks, one deterministic offline-pull/upload-retry test, and three real HTTP/process/PostgreSQL scenarios). Crash recovery required no manual database edits. The simulator retries an offline/expired pull after refreshing its heartbeat and bounds retries by the idle timeout. No database migration was needed for stats or the simulator.

## Gemma remote-compute demo (abel-backend)

Abel's Mac runs the coordinator and one Gemma 3 12B worker; client laptops open `/demo/` remotely. The temporary dashboard is in `backend/demo/`, separate from Ronald's `frontend/`. See `worker/README.md` for startup, model download, GPU verification, and client instructions.

From `backend/`, start the coordinator with:

```sh
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

In `backend/.env`, preserve `DATABASE_URL` and `API_TOKEN`; set `INFERENCE_MODEL_ID=gemma3:12b` and `INFERENCE_MODEL_REVISION` to the installed model's full Ollama digest from `/api/tags`. Restart the backend after changes. Never commit `.env`.

### API contract for teammate agents

`POST /api/jobs` accepts `task_type: "summarization"` and `inputs: [document]`. Paragraph breaks are preserved. The dashboard submits the entire document as one input, producing one summary paragraph. Each input is limited to 6,000 UTF-8 bytes; the server rejects longer documents. Batch API clients can still send multiple independent documents. Each document is one task; sentiment tasks retain 25-input chunks.

`POST /api/tasks/{task_id}/complete` accepts summary `{index,text}` results and validates their shape against the job type. Existing sentiment `{index,label,score}` results remain supported. Jobs pin model ID and revision at creation.

`GET /api/jobs/{job_id}/results` includes summary results plus a `tasks` array containing task ID, input start index/count, status, worker ID/name, attempt count and execution time. The worker identity is the current/final owner, not a full attempt history.

The existing three-attempt retry and partial-result behavior is unchanged: once all tasks finish, any permanently failed task makes the job `FAILED`, with successful results retained.

### Resource reporting

Migration `47bc91eea204` adds nullable worker fields, preserving compatibility with old workers. Run migrations before starting the updated backend.

Registration adds `gpu_core_count` and `gpu_memory_kind` (`unified`, `dedicated`, or `unknown`). Total RAM remains `ram_gb`; GPU identity is `gpu`. For Apple Silicon, `gpu_memory_gb` is null because GPU memory is shared with RAM.

Heartbeats add `ram_available_gb`, `gpu_available_gb`, and `gpu_model_memory_gb`; `/api/workers` returns them. Units are GiB despite the legacy `_gb` names. Missing telemetry is null. Available RAM cannot exceed registered total RAM. Unified-memory workers cannot report a separate available GPU pool. `gpu_model_memory_gb` comes from Ollama's model allocation, not a whole-system GPU usage meter.

The dashboard refreshes every two seconds; measurements update at the configured worker heartbeat interval. Offline worker availability is shown as unavailable. The scheduler still assigns one matching task at a time; these metrics are observability, not memory-based admission control.

### Verification

Check `/ready`, verify the Gemma worker is online, submit a multi-paragraph document, and confirm a single summary with persisted worker attribution and runtime. Verify GPU placement using Ollama, and compare available-memory readings over successive heartbeats. Browser clients need only the coordinator token, never database credentials.

## Document Q&A, extraction, and coding assistance

The demo now offers four task choices. All use the same pinned Gemma model, existing HTTP queue, result storage, retry logic, and heartbeat telemetry. No new migration is required for these task types; instructions are stored in each task's existing JSON payload.

Use `POST /api/jobs` with `inputs: [source]` and one of:

- `summarization`: unchanged; returns `{index,text}`.
- `document-qa`: requires a nonblank `instruction` containing the question; returns `{index,text}`. The prompt asks for document-grounded answers and an explicit missing-information response.
- `information-extraction`: returns `{index,names,dates,amounts,action_items}`. Every category is an array of strings, empty when nothing is found. Each array has at most 20 items; each item at most 300 characters. The worker uses Ollama structured output, validates it locally, and the coordinator validates it again before persistence.
- `coding-assistance`: optional `instruction` describing the requested explanation or bug fix; defaults to explaining the code and identifying likely bugs. Returns `{index,text}` with whitespace and code fences preserved. Code is never executed.

Example Q&A request:

```json
{
  "task_type": "document-qa",
  "inputs": ["The approved project budget is $18,000."],
  "instruction": "What is the approved budget?"
}
```

`instruction` is rejected for summary, extraction, and sentiment tasks. For Q&A/coding it is limited to 1,000 characters; each source is limited to 6,000 UTF-8 bytes, with a combined source-plus-instruction limit of 6,500 bytes. Assignments include optional `instruction`, captured at job creation. A batch shares the instruction across its independent inputs.

Workers advertise all supported task types at registration. Existing workers must restart to advertise the new capabilities. Result rendering uses text nodes, so model-generated HTML and code are displayed without execution. The task selector does not replace pasted content; use **Load example** to deliberately load a sample for the selected mode.

Generation limits: 320 tokens for summary/Q&A, 512 for extraction, 700 for coding assistance; context remains 8,192 tokens and temperature 0. Incomplete generation and malformed structured output follow the existing failure/retry flow. These limits bound the demo, not the model's full capabilities. Factual grounding is prompted and tested with examples, not guaranteed.

## Reconnect identity and activity dashboard

Migration `78ccab156bc1` adds a nullable unique `workers.device_id`. Updated workers send a persisted UUID. Registration performs a PostgreSQL upsert and preserves active assignments and counters. Legacy clients without an ID remain compatible. Existing historical worker rows are not deleted. The demo suppresses redundant offline legacy hostname entries and uses distinct modern device IDs, so two distinct modern devices sharing a display name stay separate.

`GET /api/activity` exposes authenticated current ownership (up to 100 active tasks), the 30 most recently created tasks, task-state totals, retries, and per-worker completed-task/input counts with average execution milliseconds. Historical metrics span retained data; they are not a real-time throughput benchmark. Queue seconds for retries include prior attempts, and elapsed seconds are for the current/latest attempt. All metric requests remain read-only.

The dashboard adds recent jobs, result JSON download, connection status, show/hide token, Enter-to-connect, optional sessionStorage remembering, and Disconnect. Remembering is opt-in and tab-scoped; Disconnect removes the stored token. The token is never put in a URL or downloaded result.

See `backend/TEAM_HANDOFF.md` for Abel/Kevin/Ronald ownership and acceptance checks.

See [GPU discovery and shared contract](../docs/COMPUTE_LOCATIONS.md) for optional worker locations, the map in `/demo/`, explicit job targeting, saved inference measurements, migration `a92e8f37d610`, and rollout/review notes.

The map uses bundled Leaflet with OpenStreetMap tiles and supports zoom/pan. Visitors get an opt-in location prompt and can choose an approximate area on the map when browser geolocation is unavailable. Automatic geolocation on a LAN address requires trusted HTTPS. Owners can save a worker's missing site through **Place this worker on map**; visitor location sharing alone does not publish a GPU location. If `/api/workers` works but `/api/workers/locations` returns 404, restart the backend on the updated code (fresh static files do not reload Python routes).

### Backend-only connection and legacy-registration cleanup

`GET /api/workers` now filters superseded offline legacy records before pagination. Add `include_history=true` for historical registrations. Modern device IDs are never collapsed by name or hostname. Old clients without device IDs reuse an exact hostname/name/model/revision registration under a transaction lock; upgrading to persistent device IDs is still preferred.

`GET /api/connection` checks the bearer token and returns non-secret model, task-type, size-limit and heartbeat configuration. `worker/connect.py --url http://COORDINATOR:8000` prompts privately for a token and verifies the connection. Add `--start-worker --name NAME` only on the compute host. It does not persist the token or put it in command-line arguments.

`TEAM_HANDOFF.md` now assigns backend/worker work to all three teammates: Abel owns coordinator lifecycle and identity; Kevin owns worker runtime/telemetry; Ronald owns backend observability and connection tooling. No frontend work is assigned.

## Two models on one machine

Migration `b731c5ae204f` adds `workers.models` and a per-model task slot. Apply `alembic upgrade head` before restarting the coordinator. A machine keeps its existing device/worker ID. Legacy workers still claim one task at a time; a multi-model worker may claim one task per registered model, at most two total.

`GET /api/workers` now includes `models: [{model_id, model_revision, supported_tasks}]`. Empty `models` means a legacy worker using its existing top-level model fields. Models must be loaded and GPU-verified before registration. Changing the inventory while tasks are active returns 409.

`POST /api/jobs` accepts optional `model_id`, for example:

```json
{"task_type":"coding-assistance","model_id":"qwen2.5-coder:3b","inputs":["def average(xs): return sum(xs)/len(xs)"],"instruction":"Explain the empty-list case."}
```

Omitting `model_id` preserves the coordinator's configured default. Explicit selection requires an online compatible worker; the job snapshots its exact digest. Conflicting online digests require selecting a worker. The existing `target_worker_id` still pins a job strictly.

Workers claim with `POST /api/workers/{id}/next-task?model_id=qwen2.5-coder:3b`. Retrying a claim returns the same active assignment for that model. Heartbeats renew each assignment separately; the coordinator computes the machine's active task count from current assignments, so an idle model cannot mark the other model idle. Completion, failure and expiry release only the corresponding slot. Three exhausted attempts still produce FAILED with partial results.

Frontend integration: populate model choices from each worker's `models`, filtered by supported task, and send `model_id` when submitting. The demo dashboard includes a model selector below the task selector, filters models by task and selected worker, and disables unavailable explicit selections. Model speed measurements remain informational; geographic distance does not determine model assignment.
