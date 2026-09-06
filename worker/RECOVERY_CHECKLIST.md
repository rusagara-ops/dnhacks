# Worker startup, recovery, and GPU benchmark

## Start a compute host

1. Use the team's current branch, Python 3.12 and `worker/requirements.txt`. Upgrade the coordinator and apply its approved migration before using location or inference telemetry fields. Workers never need database credentials.
2. Keep the existing `.cache/device-id` on this installation. Never copy it to another computer. The worker and benchmark share the installation process lock; stop either one before running the other.
3. Start the existing Ollama instance normally and verify `ollama ps` shows GPU allocation for `gemma3:12b`. Do not start a second server. The worker fails before registration if GPU allocation is absent/unknown. A detected Apple GPU name is not sufficient.
4. Confirm the installed model digest from Ollama matches Abel's configured revision. If a tag was replaced, stop and agree on the digest before restarting; do not swap models automatically. A mismatch with coordinator jobs means the worker cannot claim them.
5. Check Abel's `/health` and `/ready`. Enter the API token privately with `read -s`, export it, and never include it in commands, logs, screenshots, reports or commits. Ronald's `worker/connect.py` can validate the connection without starting inference.
6. Start with an optional approximate site (example coordinates only; replace with the host's campus/city):

```zsh
read -s "API_TOKEN?Coordinator API token: "
export API_TOKEN
echo
worker/.venv/bin/python worker/run.py --url http://ABEL_LAN_IP:8000 --name Kevin-Mac \
  --site "Your campus" --region "New York, US" --latitude 40.71 --longitude -74.01
```

Omit all site flags to withhold location. `--site`, `--latitude` and `--longitude` must be supplied together. This Mac's earlier Qwen setup is not the team's current Gemma GPU worker; do not assume an 8 GB Mac can run the 12B model. Use it as a client when it cannot satisfy the worker's GPU warmup requirement.

7. Wait for registration, then verify the worker is online in the dashboard and at the expected site. Keep the host plugged in and awake; `caffeinate -i` can wrap the command. Default idle timeout is 24 hours; registration alone does not prove any task completed.

## Stop and recover

1. For a clean demo pause, wait until the worker is idle, then Ctrl+C. During generation, Ctrl+C stops the worker's networking; an outstanding local inference request may finish while Python shuts down. The coordinator must recover any unfinished assignment by heartbeat/lease expiry. Do not count an unacknowledged result as saved.
2. Restart from the same installation. Verify the same worker ID, one process lock, and one active assignment. Repeated concurrent startup should reject the second process.
3. Rehearse a coordinator outage while generating. Heartbeats must continue to be attempted. Pull transport/5xx failures back off and reconnect. Result uploads retry at most three times using the same assignment, result, telemetry and execution time. After exhaustion, restart and let the coordinator's lease recovery decide ownership.
4. Rehearse a lost completion response. An accepted completion followed by a retry should return `already_completed`; results and counters must not duplicate. A conflicting heartbeat during an ambiguous upload must not prevent retrying the saved completion.
5. Rehearse an expired assignment during generation. The worker discards superseded output. For an automatically assigned job, a different compatible worker can recover it. A job explicitly targeted to one worker waits for that worker; recovery does not move it to another site.
6. Verify both `COMPLETED` jobs and permanent `FAILED` jobs through the results API. A permanent failure must retain successful partial results. Preserve job, task, assignment and worker IDs and status evidence, excluding source text and credentials.

The automated mock tests exercise outages and ownership changes without shutting down the team's coordinator. A physical-machine rehearsal is still required before demo reliability claims.

## Benchmark Abel's GPU

Run only on the agreed compute host while its normal worker is stopped. This directly calls local Ollama, acquires the installation lock, warms the model, verifies the supplied digest and runs each of the four task types. It never executes generated code or contacts the coordinator.

```sh
worker/.venv/bin/python worker/benchmark.py \
  --expected-digest AGREED_OLLAMA_DIGEST --repeats 5 --output /tmp/abel-gpu-benchmark.json
```

The report records model/digest, hardware, Python, timestamp, each task's wall time, prompt/output tokens, token-generation duration, derived tokens/s, and memory snapshots before/after inference. It contains neither tokens for authentication nor source/model output text. Unknown counters are null. GPU model allocation and available system RAM are separate measurements; Apple RAM is unified. Memory snapshots are not a peak measurement. The examples are short synthetic inputs and the model is warm: do not generalize these numbers to large documents, network latency or other computers.

Inspect all four modes' outputs separately during the team rehearsal for factual quality. Record the actual tested machine and compare medians only across equivalent inputs/model revisions. No benchmark results for Abel's GPU were collected while implementing this feature.
