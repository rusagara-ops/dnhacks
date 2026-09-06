# Gemma remote-compute worker

> This backend/worker branch excludes the demo UI. References to `/demo/` describe the companion UI on `abel-backend`; use `/docs` to inspect these APIs independently.

Abel's 24 GB Mac runs **Gemma 3 12B through Ollama**. Other laptops use the coordinator dashboard in a browser; they do not need Python, Ollama, a model download, or a running worker. This is remote inference on one compute host. Requests are queued and each worker handles one task at a time.

## Start on the compute Mac

Install Ollama for macOS and Python 3.12. From the repository root:

```sh
python3.12 -m venv worker/.venv
worker/.venv/bin/python -m pip install -r worker/requirements.txt
```

Start `worker/start-ollama.command` in Terminal. It sets one loaded model, one concurrent inference, an 8,192-token context, and a loopback-only Ollama server. On Abel's machine the runtime was downloaded to `worker/.cache/ollama/`; elsewhere it uses an installed `ollama` command. Model weights are stored in `worker/.cache/ollama-models/`.

In another terminal, download the model once:

```sh
ollama pull gemma3:12b
```

For the repository-local runtime on Abel's Mac, use `worker/.cache/ollama/ollama pull gemma3:12b` instead. Allow approximately 8.1 GB for weights plus runtime files and working memory. Do not start a second Ollama server on the same port.

Read the installed model's full `digest` from `http://127.0.0.1:11434/api/tags`. Configure `backend/.env` with `INFERENCE_MODEL_ID=gemma3:12b` and that digest as `INFERENCE_MODEL_REVISION`, preserving the existing database URL and API token. Restart the coordinator after changing these values. The worker advertises the installed digest; mismatched jobs are not claimed.

Enter the same coordinator API token privately in zsh:

```sh
read -s "API_TOKEN?Coordinator API token: "
export API_TOKEN
echo
worker/.venv/bin/python worker/run.py --url http://127.0.0.1:8000 --name Abel-Mac
```

Hardware capacity is detected automatically. The old `--ram-gb` flag has been removed. Model warmup happens before registration. Inference runs off the heartbeat loop; heartbeats continue while generating. Stop with Ctrl+C. Restarting from the same installation reuses its persistent worker identity.

## Client laptops

Open `http://ABEL_LAN_IP:8000/demo/` and enter the coordinator API token. Paste the entire document and click **Summarize document**. Keep the computers on a network that permits connectivity. Clients must use Abel's address, not `localhost`. Stop old Qwen workers on the client laptops.

## Summary contract

- `task_type`: `summarization`.
- `model_id`: `gemma3:12b`; revision is the installed Ollama manifest digest.
- Each input is a complete document, preserving paragraph breaks.
- Demo dashboard submits `inputs: [document]`, so one document produces one summary.
- Limit: 6,000 UTF-8 bytes per document, rejected rather than silently truncated.
- Context: 8,192 tokens; maximum generated output: 320 tokens; temperature: 0.
- Prompt requests a coherent paragraph of approximately 100–150 words, or fewer for short sources.
- Result: `{ "index": 0, "text": "The document summary." }`.
- A generation that reaches the output limit is treated as incomplete and reported as failure, not stored as a successful truncated summary.

The API still supports a batch of separate documents; these produce separate summaries. Existing sentiment jobs and results remain compatible. Model output is untrusted text and the dashboard renders it as text, never HTML.

## RAM and GPU telemetry

All API fields ending in `_gb` use binary GiB (bytes divided by 1024³); the dashboard labels units explicitly.

Registration detects total RAM, GPU name, GPU core count, and whether memory is unified. Heartbeats update `ram_available_gb`, `cpu_utilization`, `memory_utilization`, and `gpu_model_memory_gb` (Ollama's reported GPU allocation for this model).

Apple Silicon uses one shared memory pool. `gpu_memory_gb` and `gpu_available_gb` remain null instead of inventing separate VRAM. The dashboard shows available shared RAM as an estimate and states that it is not a guaranteed GPU allocation budget. Free GPU cores/utilization are not reported. Offline or unsupported live measurements show unavailable, not zero.

Use `ollama ps` to verify GPU placement. Detecting the GPU name alone does not prove the model is GPU accelerated. The Gemma worker requires a positive Ollama GPU allocation after warmup before registering. If a sandbox-launched server sees only CPU, stop that server and start `worker/start-ollama.command` in normal Terminal, then verify again.

## Tests

Backend tests cover shape validation, exact model identity, full-document forwarding, output truncation rejection, and persisted heartbeat telemetry. The opt-in `RUN_REAL_MODEL_TEST=1` test requires the downloaded model, a running Ollama server, the worker environment, and `TEST_DATABASE_URL`. It uses an isolated temporary schema. Physical client-to-host connectivity must also be tested separately.

## Additional task modes

This worker now advertises `summarization`, `document-qa`, `information-extraction`, and `coding-assistance`. Restart an older worker to register the new capabilities. All modes reuse Gemma and keep one assignment active at a time.

Q&A uses the assignment's `instruction` as its question, asks for answers grounded in the source, and returns a missing-information response when appropriate. Coding assistance accepts an optional request and preserves code formatting; it never runs the supplied or generated code. Extraction uses a JSON schema and returns arrays for `names`, `dates`, `amounts`, and `action_items`; malformed output is reported as an inference failure.

The source limit remains 6,000 UTF-8 bytes. Source plus instruction must fit within 6,500 bytes. Output budgets are 320 tokens for summary/Q&A, 512 for extraction, and 700 for coding. These are selected automatically by task type. Model output is still fallible; inspect important answers and suggested fixes.

See the backend README for request and response examples. `tests/test_real_modes_postgres.py` is an opt-in test covering known-answer Q&A, missing-answer Q&A, structured extraction, and code help through real GPU inference and persisted results.

## Stable reconnects

See [RECOVERY_CHECKLIST.md](RECOVERY_CHECKLIST.md) for startup/shutdown, interrupted uploads, model/GPU checks and the four-mode benchmark command. [GPU discovery and shared contract](../docs/COMPUTE_LOCATIONS.md) documents optional `--site`, `--region`, `--latitude`, `--longitude` registration and per-result inference telemetry. Deploy the updated coordinator before updated workers.

A worker can be online without a map pin if it has no saved location. Its owner can choose **Place this worker on map** in the demo, pick the machine's approximate campus/city and confirm before saving. Restarting a worker without location flags preserves that saved site. Explicit startup flags replace it; an explicit null sent to the location API clears it. Sharing a browser's own location only sets the visitor's distance reference and never silently moves a worker.

Worker identity is persisted in `.cache/device-id` and sent as `device_id` during registration. Restarting reuses the same database worker ID and retains task history. Do not delete or copy this file to another machine. A local `.cache/worker.lock` prevents simultaneous worker processes from the same installation. For isolated tests only, `WORKER_STATE_DIR` selects a separate state directory. Existing legacy registrations remain in the database for historical attribution; the demo hides redundant offline legacy cards.

## Run Gemma and Qwen concurrently

Download `gemma3:12b` and `qwen2.5-coder:3b` into the same Ollama server. Restart `start-ollama.command`: it allows two loaded models and one request per model (`OLLAMA_MAX_LOADED_MODELS=2`, `OLLAMA_NUM_PARALLEL=1`). Stop the old worker before starting this process; the existing device lock prevents duplicate installations from running concurrently.

From the repository root, with the existing `API_TOKEN` environment variable:

```bash
worker/.venv/bin/python worker/run.py --name Abel-Mac --url http://127.0.0.1:8000 --models gemma3:12b qwen2.5-coder:3b
```

Gemma supports the four existing tasks with an 8192-token context. Qwen supports coding assistance with a 4096-token context. Both must remain GPU-loaded before registration succeeds. One machine row advertises both models, with one independent assignment per model. Heartbeats report combined model GPU allocation (unified memory, not a separate free VRAM pool). Closing the worker stops both model loops; leases recover unfinished work.

Omitting `--models` preserves the Gemma-only worker. Concurrent generation shares GPU resources and is not a speedup guarantee. `--max-tasks` and `--idle-timeout` apply independently to each model loop. Keep ordinary applications' memory usage in mind when testing both models.

Registered models use `keep_alive=-1` on warmup and generation so idle expiration cannot stall GPU eligibility. They retain memory until explicitly unloaded or Ollama is stopped. Restart the worker after restarting Ollama.

On macOS, registration uses an application-specific UUID derived from the machine's platform UUID, so copying the repository does not create another machine identity. The raw hardware UUID is never transmitted. The previous cached installation UUID is retained as a migration alias: registration updates that existing database row rather than inserting another. A per-user machine lock prevents two updated worker copies from running concurrently. `WORKER_STATE_DIR` explicitly opts into isolated identities for tests; non-Mac hosts retain the cached installation ID fallback.
# Controlled sharing enrollment

For an individually owned worker, print its enrollment ID with
`worker/.venv/bin/python worker/run.py --show-device-id`, issue a worker credential
under your account in `/demo/sharing.html`, and launch with `--scoped-credential`.
Put that credential in `API_TOKEN` privately. New owned workers start paused until
their provider enables sharing. Existing shared-token demo launch commands remain
supported. See [the rollout and trust guide](../docs/CONTROLLED_COMPUTE.md) before
switching a coordinator to controlled mode.
