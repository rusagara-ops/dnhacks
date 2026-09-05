# Abel — Coordinator Backend

Owner: Abel. The coordinator runs on Abel's laptop for the demo. It manages worker presence, jobs, task assignment, retries and results. Kevin's worker performs inference; Ronald's frontend calls this HTTP API. Neither teammate needs the database password.

## Current implementation (v0.1)

Implemented:

- FastAPI application with interactive `/docs` and `/openapi.json`.
- Environment configuration and bounded PostgreSQL connection pooling.
- Versioned Alembic migration for `coordinator.workers`.
- Worker registration, paginated listing and heartbeat updates.
- `AVAILABLE`, `BUSY`, `OFFLINE` presence derived from heartbeat age.
- Optional shared demo bearer token and configured CORS origins.
- Liveness and database readiness endpoints; read-only connection check.

Not implemented yet: jobs, task assignment, leases, retries, results, stats and inference. The proposed interfaces below are for coordination; they currently return 404. No model or model revision has been chosen yet.

Database verification: unit/API checks pass locally. The PostgreSQL integration test is included but requires a disposable migrated database. This version has not been applied to or verified against the shared Supabase project.

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

Open http://127.0.0.1:8000/docs. Use **Authorize** to enter the demo token when configured. `/health` indicates the process is alive. `/ready` also checks the database connection and worker table. A missing connection or migration returns 503, not a false readiness success.

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

`model_id` and `model_revision` are optional until we agree on the model. Scheduling will require them when implemented. `benchmark_score` defaults to 1 and is currently informational.

Response: **201 Created**.

```json
{"worker_id": "<uuid>", "heartbeat_interval_seconds": 5}
```

### POST /api/workers/{worker_id}/heartbeat

```json
{"cpu_utilization": 35.2, "memory_utilization": 41.0, "active_tasks": 0}
```

Response: **200 OK**, `{"status":"ok"}`. An unknown worker returns 404. `active_tasks` must be 0 or 1 for the MVP.

Continue sending heartbeats independently of the inference loop. A fresh heartbeat restores an offline worker's presence. This currently reports presence only: task recovery and lease renewal are not implemented.

### GET /api/workers?limit=100&offset=0

Returns a JSON array, newest registrations first. `limit` is 1–500; `offset` is nonnegative.

Each item contains the registration fields plus `id`, `status`, `cpu_utilization`, `memory_utilization`, `active_tasks`, `last_heartbeat`, `created_at`, and `updated_at`.

- `OFFLINE`: last heartbeat is older than the configured timeout.
- `BUSY`: heartbeat is recent and `active_tasks` is 1.
- `AVAILABLE`: heartbeat is recent and `active_tasks` is 0.

Status is computed when read, so dashboard polling does not write to the database. Presence does not yet guarantee the worker has the required inference model.

## Frontend integration — Ronald

Start with `/health`, `/ready` and `GET /api/workers`. Polling workers every second is fine for the demo. Use the exact property names above (`ram_gb`, `benchmark_score`, etc.). Display connection errors separately from an empty worker list.

When configured, send the shared demo token in the Authorization header. Do not put a database password or Supabase service-role key in frontend code. The shared demo token is visible to the browser user; this MVP assumes trusted teammates.

## Proposed job/task API — not implemented

These paths and examples are the agreed direction for the next slice. Kevin still needs to confirm the model ID, pinned revision, token limit and truncation behavior. All workers must run the same model/revision. CPU execution is required; GPU use is optional.

### POST /api/jobs

```json
{
  "task_type": "sentiment-classification",
  "inputs": ["I love this.", "This is terrible."],
  "optimization": "fastest"
}
```

Plan: reject empty input lists and unsupported task types/optimization values; create the job and its tasks atomically. Start with 25 inputs per task. `fastest` means eligible workers pull the oldest queued task; no benchmark optimizer is promised.

### POST /api/workers/{worker_id}/next-task

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

No work returns `{"task":null}`. Poll only while idle, with a short delay when no work is available. The backend will enforce one active assignment per worker and select eligible tasks with a database transaction and `FOR UPDATE SKIP LOCKED`.

Indexes refer to positions in the original job. Each assignment receives a new ID. Lease duration and the heartbeat fields for renewing a specific assignment will be finalized before scheduling is implemented. Do not assume worker presence alone renews every task indefinitely.

### POST /api/tasks/{task_id}/complete

```json
{
  "worker_id": "<uuid>",
  "assignment_id": "<uuid>",
  "results": [{"index": 0, "label": "POSITIVE", "score": 0.998}],
  "execution_time_ms": 812
}
```

Labels are `POSITIVE` or `NEGATIVE`; score is the model score for that label in [0, 1]. Return exactly one result per assigned index. Execution time includes preprocessing and inference, excluding model loading and network calls.

The planned completion transaction validates the current assignment, inserts a unique result per task and updates job progress atomically. Retrying an accepted completion is safe; expired/superseded assignments return 409. Workers must not report inference failure merely because a completion upload timed out: retry the same completion first.

### POST /api/tasks/{task_id}/fail

```json
{
  "worker_id": "<uuid>",
  "assignment_id": "<uuid>",
  "error": {"code": "INFERENCE_ERROR", "message": "Model execution failed"}
}
```

A chunk succeeds or fails as a whole. Maximum three assignments per task; increment attempts only upon assignment, never again on timeout. Old assignments cannot fail a newly assigned task.

### Planned frontend reads

- `GET /api/jobs`: recent jobs.
- `GET /api/jobs/{job_id}`: task counts, progress, timestamps and status.
- `GET /api/jobs/{job_id}/results`: ordered successful predictions, original indexes and failed-task details.
- `GET /api/stats`: dashboard counts, after the core lifecycle works.

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

Work on `abel-backend`, make focused commits and coordinate changes to the API examples before Kevin or Ronald depends on them. Next milestone: verify this slice against Supabase, then implement job creation and the task lifecycle with concurrent-claim and stale-assignment tests.
