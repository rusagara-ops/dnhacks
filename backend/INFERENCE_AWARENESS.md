# Inference-aware orchestration: registry and eligibility milestone

Implemented without database migrations:

- `GET /api/models` lists hardcoded model/task/resource policies, metrics, configured availability, and the pinned revision. It uses the existing demo bearer authentication.
- `POST /api/jobs` accepts optional `model_id`. Explicit IDs must be registered and match the coordinator's configured model. Unknown IDs and unsupported model/task pairs return 422; a known but unavailable model returns 503. Omitting the field preserves existing clients and still snapshots the configured model/revision.
- Registered-model assignment checks free RAM, total RAM, CPU load, GPU presence/allocation, and dedicated VRAM availability. Missing required telemetry prevents new assignments. Existing assignments are returned before resource checks, preserving repeat-pull safety.
- `GET /api/jobs/{id}/eligibility?limit=100&offset=0` reports per-worker reason codes using the same rules as scheduling. This is current availability for *new* assignments, not historical attribution or a promise that work exists.
- Existing atomic claims, exact revision matching, one active task per worker, lease recovery, and completion semantics remain in place.

The registry currently covers `gemma3:12b`, `simulation/ui`, and `simulation/sentiment`. Only the one model/revision configured in the coordinator is selectable for new explicit-model jobs. Unknown legacy configured models retain the preexisting model-match-only policy; diagnostics label this fallback. This avoids silently blocking preexisting deployments, but those models do not yet receive resource filtering.

Gemma thresholds are initial demo admission policies, not benchmarked universal model requirements: 16 GiB total RAM, 2 GiB additional free RAM after model loading, GPU allocation confirmed, and CPU utilization at most 85%. Dedicated-memory GPUs additionally require 1 GiB free VRAM. Apple unified-memory machines use shared RAM headroom instead of a fictitious independent VRAM pool. These thresholds require calibration on real workers. Current telemetry has no GPU-utilization measurement, so no GPU-utilization rule is claimed.

Simulated models need no memory headroom and produce no real inference. No existing job pins are rewritten and no model weights are downloaded by the coordinator.

## Validation

`tests/test_inference_awareness.py` checks model selection, resource rejection, unified versus dedicated memory, and task/model compatibility. `tests/test_scheduler_postgres.py` exercises real concurrent claims and resource gating in temporary schemas with `TEST_DATABASE_URL`, including retries of already-issued assignments after load rises.

## Remaining spec milestones

- Exact token counts with the selected model's tokenizer and bounded output budgets.
- Measured, model-specific worker benchmarks and actual runtime/token reporting.
- Multiple loaded models per worker and multiple configured model revisions, when supported by the runtime.
- Frontend model selection and coordinator eligibility reasons (the current matrix shows advertised compatibility only).

Automatic document splitting and final-summary assembly remain deferred as requested. No ranking algorithm, energy scheduler, automatic downloads, or approximate character-count-as-token-count is introduced.

Deploy these backend changes to Abel's coordinator before expecting new endpoints or resource policies there. Local source edits do not modify his running service.
