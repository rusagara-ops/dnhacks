# Kevin's worker: short-summary demo

Runs a complete small model on each Mac and pulls independent paragraphs from Abel's coordinator. This distributes inference tasks; it does not split a single model across machines. M1/M2 Macs use CPU inference by default, including the 8 GB machines. Each process handles one assignment at a time while an independent heartbeat renews its lease.

## Setup on each Mac

Use Python 3.12. From the repository root on `abel-backend`:

```sh
python3.12 -m venv worker/.venv
worker/.venv/bin/python -m pip install -r worker/requirements.txt
```

Set `API_TOKEN` to the same value as the coordinator's `backend/.env` (enter it locally; do not commit it). Then run:

```sh
export API_TOKEN='your-coordinator-token'
worker/.venv/bin/python worker/run.py --url http://COORDINATOR_LAN_IP:8000 --name Kevin-Mac --ram-gb 8
```

Use a distinct name for each Mac; use `--ram-gb 24` on the 24 GB machine. The coordinator must listen on `0.0.0.0`, macOS must allow incoming connections, and the machines must be able to reach one another on the network. Test `http://COORDINATOR_LAN_IP:8000/health` from the second Mac first. Guest Wi-Fi may isolate devices.

First launch downloads model weights to `worker/.cache/huggingface/`, then registers. Allow internet access and several minutes for setup before the demo. Subsequent launches reuse the cache. The worker never needs a Supabase URL or database password. Stop with Ctrl+C; unfinished assignments are recovered after heartbeat/lease expiry. Restarting creates a new worker registration, so old offline entries may remain.

## Fixed inference contract

- Task: `summarization`; one English paragraph per assignment.
- Model: `Qwen/Qwen2.5-0.5B-Instruct`.
- Revision: `7ae557604adf67be50417f59c2c2f167def9a775`.
- Prompt: summarize in one short sentence using only provided facts; return only the summary.
- Source limit: first 512 model tokens. Output limit: 64 new tokens; greedy decoding.
- Result: `{"index": 0, "text": "The summary."}`. Preserve the assigned index.
- Completion includes `worker_id`, `assignment_id`, `results`, and `execution_time_ms`.

The model and revision must match the job snapshot. A worker downloads before registration so it cannot claim work during model loading. CPU inference runs off the asynchronous networking loop. Failed inference is reported through `/api/tasks/{id}/fail`; expired assignments discard their output. Completion retries reuse exactly the same assignment and payload.

The small model prioritizes laptop compatibility over summary quality. Review demo examples beforehand. A successful local two-process test proves the integration; it does not establish connectivity or performance on a second physical Mac.
