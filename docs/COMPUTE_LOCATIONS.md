# GPU discovery and Kevin's worker handoff

Initial feature: PR #7. Interactive map follow-up: `kevin/interactive-compute-map`, based on `main` at `b8e0da5`.

Users can inspect registered GPU hosts by campus/city, see GPUs ordered closest to furthest from the coordinator, inspect the installed model and revision, and submit a job to a chosen worker. The coordinator enforces the choice. Existing jobs without a selection continue to use the existing pull scheduler.

The UI lives in `backend/demo/`, the repository's working frontend; `frontend/` is currently a placeholder. The inspiration is the [NRP site map](https://dash.nrp-nautilus.io/), but this feature lists only this coordinator's registered workers. It does not claim access to NRP resources or populate fictitious university GPUs.

## Shared API contract for Abel and Ronald to review

All routes use the existing bearer-token authentication. No new database credentials are needed by workers or browsers. These are additive fields; older workers and clients can continue omitting them after the coordinator is upgraded.

`POST /api/workers/register` optionally accepts:

```json
{
  "location": {
    "site": "Example campus",
    "region": "New York, US",
    "latitude": 40.71,
    "longitude": -74.01
  }
}
```

This fragment supplements the existing registration fields. `site` and both finite coordinates are required when a location is supplied. Latitude is −90…90 and longitude −180…180. `region` is optional. The persisted worker response includes `location`, null when not shared. Re-registering with explicit coordinates updates the location; explicit null clears it. Omitting the location preserves any saved site, including one placed through the map. Locations are operator-provided reference points, not verified physical addresses. No IP geolocation is performed.

`GET /api/workers/locations` accepts optional paired `latitude`/`longitude`, `task_type`, `gpu_only`, `online_only`, `limit` (1–500, default 100), and `offset`. Response:

```json
{
  "items": [{"worker": {"id": "UUID", "location": null}, "distance_km": null, "compatible": true}],
  "total": 1,
  "limit": 100,
  "offset": 0,
  "distance_kind": "great_circle"
}
```

`worker` contains the full existing worker response (abbreviated above). `compatible` means the worker's model ID and revision match the configured coordinator model; `task_type` filters advertised capabilities. GPU filtering includes a reported GPU name or a positive reported model GPU allocation. A name alone is not proof of GPU acceleration. Online status still derives from heartbeat freshness. Historical suppression follows `/api/workers`; distinct modern installations remain distinct. Filtering and distance ordering happen before pagination, with unknown distances last. Before a visitor shares an area, the backend uses `COMPUTE_ORIGIN_LATITUDE` and `COMPUTE_ORIGIN_LONGITUDE`, a paired, optional server setting for the coordinator’s approximate location. Explicit API query coordinates remain supported for other clients and override this default. The response adds `distance_reference`: `coordinator`, `request`, or `unavailable`. Without either reference, ordering is by name and ID and distances are null; the UI labels distance unavailable.


`POST /api/workers/locations/search` accepts required finite `latitude` and `longitude` with the same optional filters/pagination, and returns the same response. After explicit consent, the browser rounds its location to two decimal places and uses this endpoint. Coordinates go in the request body rather than routine URL access logs; the backend calculates and sorts distances. No visitor location is written to the application database. The response identifies `distance_reference: "request"`, displayed as “Closest to you”.

`POST /api/workers/{worker_id}/location` accepts `{"location": {"site": "Campus", "latitude": 40.71, "longitude": -74.01}}`, or `{"location": null}` to clear. It persists the worker's map location without changing heartbeat freshness or assignment ownership. It uses the existing shared bearer-token authorization; the demo does not have separate user/worker ownership credentials. The UI therefore explicitly asks the operator to confirm they manage the worker and that the chosen point is its physical site. A visitor's location must never be copied automatically to all workers. The worker's normal startup preserves this map setting when its registration omits location.

`POST /api/jobs` optionally accepts `target_worker_id: UUID`. The backend rejects nonexistent or incompatible selections with 422 and an already-offline selection with 409. Busy compatible workers can be selected. Job detail/list responses include the target. The scheduler only assigns that job to the selected worker, including after a lease expires. It does not silently fail over to a different site. If a selected host stays offline, the job stays queued; the UI explains this. Automatic assignment (`target_worker_id` absent/null) preserves cross-worker recovery. This is an explicit host restriction, not a nearest-worker scheduling algorithm. The coordinator still supports its existing single configured model/digest for new jobs.

`POST /api/tasks/{id}/complete` optionally accepts:

```json
{
  "inference_metrics": {
    "prompt_tokens": 100,
    "output_tokens": 20,
    "generation_duration_ms": 1000
  }
}
```

The result transaction saves these with attribution. Duplicate completions cannot overwrite them. `GET /api/jobs/{id}/results` includes the measurements in each task's `inference_metrics`, plus calculated `tokens_per_second` (20 in this example). Each absent measurement is null; zero duration gives null throughput. Legacy completions have null metrics. No heartbeat contract fields changed.

Measurements come from Ollama's `prompt_eval_count`, `eval_count`, and `eval_duration`. Duration is converted from nanoseconds to milliseconds; output tokens per second uses token-generation time, excluding prompt evaluation, loading, network time and upload retries. It differs from whole-task `execution_time_ms`. For multi-input assignments, counts and generation duration are summed only if every response reports a valid measurement. See the [Ollama chat API](https://docs.ollama.com/api/chat).

## Distance and privacy

Distance uses a spherical great-circle calculation (mean Earth radius 6,371.0088 km), rounded to 0.1 km by the API. The UI rounds to whole kilometres. It is not a measurement of cable length, route, RTT, or end-to-end performance. All input and result traffic still goes through the coordinator. Load, hardware, model and both network legs affect turnaround time.

On page load an inline notification offers **Share location**, **Choose on map**, and **Not now**. Nothing requests browser coordinates until the visitor clicks Share location. The resulting approximate point is held only in page memory, can be forgotten, and is cleared on disconnect/reload. Denied, unavailable, timed-out, and stale permission callbacks are handled without losing the compute list. There are no numeric coordinate inputs.

Browser geolocation requires a secure context. `http://localhost` and loopback are exceptions, but `http://192.168.11.139:8000` is not. On ordinary LAN HTTP, explain the HTTPS requirement and let visitors pan/zoom and explicitly choose an approximate point. Do not disable browser security flags. For automatic location sharing on other laptops, deploy behind HTTPS with a certificate those devices trust. See [MDN geolocation](https://developer.mozilla.org/en-US/docs/Web/API/Geolocation/getCurrentPosition).

Worker owners can use startup flags or **Place this worker on map** / **Edit map location**. They pan/zoom, pick a point, name the site, confirm ownership and save. A missing worker location stays unknown until explicitly set. User distance sorting and worker-site publication are separate actions.

The map uses locally bundled **Leaflet 1.9.4**, with its BSD license in `backend/demo/vendor/leaflet/LICENSE`. Normal interactive map viewing fetches OpenStreetMap tiles for the visible viewport, with visible attribution and normal browser caching/referrer behavior. It supports zoom, pan, keyboard navigation, grouped same-site workers, popups and a fit-to-workers control. Polling does not reset a visitor's zoom. The tile provider receives ordinary map requests (including IP address and viewed tile area), but receives no coordinator token, source documents, or result payloads. Internet access is required for detailed map tiles. Tile failures show a specific message while worker cards remain usable.

OpenStreetMap public tiles are best-effort and governed by the [tile usage policy](https://operations.osmfoundation.org/policies/tiles/). Do not add bulk downloads or offline prefetching; choose an appropriate provider for large production traffic. Browser tests mock tile responses and never crawl the public tile service.

### Diagnose an empty map on a teammate's host

- If `/api/workers` works but `/api/workers/locations` returns **404**, the running backend is older than the frontend files. Pull the updated code, apply any pending migrations and restart the actual Uvicorn process. Serving fresh static files does not reload Python route definitions.
- If the discovery route works but `location` is null, the worker owner needs to place the worker on the map or supply startup site flags.
- If pins work but the base map is blank, check access to the tile provider; the UI reports tile failures.
- If automatic visitor location is blocked at a LAN HTTP address, use the map picker or deploy trusted HTTPS.

The teammate's address `http://192.168.11.139:8000/demo/` was reachable during diagnosis, but its discovery endpoint returned 404 and its OpenAPI document omitted that route. No credentials or remote database writes were used in diagnosis.

## Rollout and ownership

Review the shared request/response additions with Abel (registry, schema, scheduler, lifecycle) and Ronald (API consumers, observability). PR #7 contains the initial migration. This follow-up adds routes and UI behavior without a new migration. No shared database or remote service was changed during implementation.

1. Stop coordinator request handling for the migration, following the team's deployment procedure.
2. On the coordinator, run the existing Alembic upgrade procedure to `a92e8f37d610`, then restart the updated backend. The migration adds nullable worker location, job target with a foreign key/index, and task-result inference metrics. It does not rewrite historical jobs/results or create another schema.
3. Set `COMPUTE_ORIGIN_LATITUDE` and `COMPUTE_ORIGIN_LONGITUDE` to the coordinator’s approximate campus/city reference point. Both must be finite and in range; zero is valid. Verify `/ready` and the authenticated `/api/workers/locations` route. Older workers continue working; their owners can place missing sites through the map.
4. Restart updated workers with optional site flags, preserving each installation's `.cache/device-id`. Upgrade the coordinator first: an older coordinator rejects the new optional request fields.
5. Open `/demo/`, connect, check the closest-first list, choose a machine, submit a document, and verify the results' worker ID matches the selection. Also test automatic assignment and an offline selection. Use two real compute hosts before claiming distributed execution.

Rollback requires stopping the updated services and returning to old code before downgrading to `78ccab156bc1`. Downgrade removes location, targeting, and inference metrics metadata; saved task output remains. It removes host restrictions, so assess queued jobs before rollback. Migration upgrade/downgrade/re-upgrade was tested only on a disposable local database.

## Validation and remaining real-host work

The Python suite covers location validation/authentication, global distance ordering before pagination, missing locations, antipodes/dateline, persisted registration updates, target rejection/enforcement/recovery, legacy submissions, idempotent result telemetry, API serialization, and heartbeat/upload outages during generation. Browser tests cover desktop/mobile layout, pins, disabled incompatible/offline selections, submission targeting, automatic reset, filters, the absence of numeric coordinate controls, permission success/denial, insecure-context fallback, worker pin editing, zoom preservation, missing-route diagnostics, and disconnect clearing.

Run Python checks from the repository root with the backend's test environment:

```sh
PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/tests worker/tests -q
```

Database checks require `TEST_DATABASE_URL` pointing to a **disposable, migrated PostgreSQL database**. They must never use the team's shared Supabase database. The model-dependent tests are separately opt-in and were not run on Abel's GPU in this implementation session.

Browser checks use route fixtures, not a production coordinator:

```sh
cd backend/demo
npm ci
npx playwright install chromium
npm test
```

Kevin's real-host benchmark and startup/recovery rehearsal are in [worker/RECOVERY_CHECKLIST.md](../worker/RECOVERY_CHECKLIST.md). The benchmark runner is ready; no new latency, memory, GPU throughput, or multi-host performance claims have been made for Abel's machine.
