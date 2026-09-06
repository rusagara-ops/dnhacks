# Backend and worker work split — Abel, Kevin, Ronald

Scope: `backend/` and `worker/` only. No frontend work is assigned here.

Base: PR #4, branch `backend-worker-updates`, targeting `main`. Branch from its latest commit until it merges; afterward branch from updated `main`. Preserve existing local changes. Each owner opens a separate small PR and coordinates shared contract changes before implementation.

## Existing foundation

- Gemma 3 12B on Abel's Apple GPU; four task types: summary, document Q&A, extraction, coding help.
- Persistent device IDs, idempotent registration, process locking, heartbeat leases, retries, and saved results.
- `GET /api/workers` suppresses superseded offline legacy registrations by default. `?include_history=true` returns historical rows. Real modern device IDs stay distinct even if names/hostnames match.
- `GET /api/activity` reports current task ownership, recent tasks, state totals, retries, and per-worker completion counts and mean execution time.
- RAM/GPU telemetry is carried in heartbeats. Apple memory is unified; no invented separate free-GPU-memory pool.
- `GET /api/connection` validates the existing bearer token and returns non-secret model/limit/heartbeat configuration.
- `worker/connect.py` prompts for the token without echoing or storing it. Validation alone does not start compute; `--start-worker` does.

## Abel — coordinator identity, scheduling, and database

Own: `backend/app/services/worker_service.py`, scheduler/recovery/task lifecycle services, models, migrations, and their tests.

Next work:
1. Rehearse concurrent registration retries and worker restarts; verify stable worker IDs and preserved active assignments.
2. Add job cancellation with an explicit terminal state and safe treatment of late completions. Agree on the contract before migrating anything.
3. Add request idempotency for job submission so network retries cannot submit duplicate jobs.
4. Verify failure recovery and successful partial results using isolated database tests.

Acceptance: no duplicate modern workers or jobs from retries; task counters remain correct; late or duplicate results cannot overwrite accepted results. Cancellation must not be reported as completed work. Apply schema changes only through Alembic.

## Kevin — worker runtime, telemetry, and reliability

Own: `worker/run.py`, `worker/inference.py`, `worker/hardware.py`, worker startup scripts, and `worker/tests/`. Coordinate changes to heartbeat fields with Abel and Ronald.

Next work:
1. Extend reconnect testing to interrupted result uploads and heartbeat outages; reuse the same assignment and result on retry.
2. Add Ollama prompt-token/output-token counts, generation duration, and tokens-per-second telemetry. Report unknown measurements as null.
3. Benchmark the four task types on Abel's GPU and document latency and memory observations. Do not claim results for untested computers.
4. Produce a reliable startup/shutdown and recovery checklist, including model digest mismatch and unavailable GPU cases.

Acceptance: one process per installation, one active task per worker, heartbeats continue during generation, no automatic code execution, and no credential leakage. Never copy `.cache/device-id` between computers.

## Ronald — backend observability, connection tooling, and API integration

Own: `backend/app/api/activity.py`, `backend/app/api/connection.py`, a new backend observability service/module and its tests, plus `worker/connect.py`. Coordinate with Kevin before changing other worker files.

Next work:
1. Add time-windowed metrics: throughput, median/p95 execution duration, queue delay, failure rate, and last successful completion per worker. Define windows and denominators explicitly.
2. Add paginated/filterable task activity by worker, job, type, and status. Preserve current fields for consumers.
3. Add backend correlation/request IDs for tracing a submission through assignment and completion; keep source text and tokens out of routine logs.
4. Extend the connection helper with precise timeout/401/model-mismatch diagnostics and automated tests. Never save tokens by default or place them in URLs.

Acceptance: activity identifies the exact worker and task; metrics use measured timestamps; retry time is not mislabeled pure queue time; APIs require authentication; diagnostics do not disclose credentials.

## Shared contracts and coordination

All `/api/*` routes require `Authorization: Bearer <API_TOKEN>` when configured. Share this token privately. Worker/client machines never need `DATABASE_URL`.

- `POST /api/workers/register`: optional UUID `device_id` identifies modern installations. Legacy retries reuse matching hostname/name/model/revision records; these fields are a compatibility fallback, not strong physical-machine identity.
- `POST /api/jobs`: `task_type`, `inputs: [source]`, optional `instruction`. Q&A requires a question; coding optionally accepts a request.
- `GET /api/jobs/{id}/results`: results, status, counters and attribution.
- `GET /api/activity`: active tasks (up to 100), recent tasks (up to 30), task counts, retry total and worker metrics.
- `GET /api/connection`: authenticated configuration check, with no token or database URL in its response.

Current timing caveat: `queue_seconds` on retried tasks includes previous attempts; `elapsed_seconds` describes the current/latest execution. Existing completion averages cover retained history, not a rolling window. Historical registrations are not silently merged into a modern worker's lifetime counters.

Before editing shared schemas, post the proposed request/response shape in your PR for the other two owners. Additive changes should remain compatible with older workers. Each PR should state tests run and any migration or restart requirement. Do not merge your own breaking contract change before the other owners review it.

## Joint acceptance rehearsal

1. Verify `/ready` and authenticate with `worker/connect.py --url http://ABEL_LAN_IP:8000`.
2. Restart Abel's worker twice and confirm the same worker ID and one default listing entry.
3. Submit different task types concurrently through the API; verify ownership and queue transitions in `/api/activity`.
4. Interrupt one worker in a controlled test and confirm recovery without duplicate saved results.
5. Confirm persisted results, failure reporting, token rejection, and no secrets in logs.

Current deployment uses one GPU compute host. Kevin's and Ronald's laptops can submit API requests without running a model. Testing with three clients is not the same as distributing computation across three GPU workers.
