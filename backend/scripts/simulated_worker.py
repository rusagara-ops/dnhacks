"""HTTP-only fake worker. Never performs inference or reads database credentials."""
import argparse
import asyncio
import contextlib
import os
import time

import httpx

MODEL_ID = 'simulation/sentiment'
MODEL_REVISION = 'v1'


def predictions(task):
    kind = task.get('task_type', 'sentiment-classification')
    if kind == 'information-extraction':
        return [{'index': item['index'], 'names': ['SIMULATION: Example Person'],
                 'dates': [], 'amounts': [], 'action_items': ['SIMULATION: review this test fixture.']}
                for item in task['inputs']]
    if kind != 'sentiment-classification':
        return [{'index': item['index'], 'text':
                 f"SIMULATION ONLY — {kind}. No AI model was run.\n\n"
                 'This fixture confirms submission, assignment, and result display.\n'
                 + ('\n# Simulated code output\ndef example():\n    return 42\n' if kind == 'coding-assistance' else '')}
                for item in task['inputs']]
    return [{'index': item['index'], 'label': 'POSITIVE' if item['index'] % 2 == 0 else 'NEGATIVE',
             'score': 0.5} for item in task['inputs']]


async def run(args):
    ui_modes = getattr(args, 'ui_modes', False)
    model_id = 'simulation/ui' if ui_modes else MODEL_ID
    supported = ['sentiment-classification', 'summarization', 'document-qa', 'information-extraction', 'coding-assistance'] if ui_modes else ['sentiment-classification']
    token = os.environ.get('API_TOKEN', '')
    headers = {'Authorization': f'Bearer {token}'} if token else {}
    async with httpx.AsyncClient(base_url=args.url.rstrip('/'), headers=headers, timeout=10) as client:
        response = await client.post('/api/workers/register', json={
            'name': args.name, 'hostname': 'simulated-worker', 'cpu': 'SIMULATED', 'cpu_cores': 1,
            'ram_gb': 1, 'supported_tasks': supported,
            'model_id': model_id, 'model_revision': MODEL_REVISION,
        })
        response.raise_for_status()
        worker = response.json()['worker_id']
        interval = response.json()['heartbeat_interval_seconds']
        print(f'SIMULATION registered {worker}', flush=True)
        active = None
        lost = asyncio.Event()

        async def heartbeat():
            while True:
                current = active
                payload = {'cpu_utilization': 0, 'memory_utilization': 0, 'active_tasks': int(current is not None)}
                if current:
                    payload.update(task_id=current['task_id'], assignment_id=current['assignment_id'])
                try:
                    r = await client.post(f'/api/workers/{worker}/heartbeat', json=payload)
                    if r.status_code == 409 and current is active and current:
                        lost.set()
                    elif r.status_code != 409:
                        r.raise_for_status()
                except httpx.HTTPError:
                    print('Heartbeat unavailable; lease expiry remains authoritative.', flush=True)
                await asyncio.sleep(interval)

        beat = asyncio.create_task(heartbeat())
        processed = 0
        idle_since = time.monotonic()
        try:
            while processed < args.max_tasks:
                response = await client.post(f'/api/workers/{worker}/next-task')
                if response.status_code == 409:
                    # A delayed heartbeat or just-expired lease can race the next pull.
                    # Restore idle presence and let the coordinator recover ownership.
                    refresh = await client.post(f'/api/workers/{worker}/heartbeat', json={
                        'cpu_utilization': 0, 'memory_utilization': 0, 'active_tasks': 0})
                    refresh.raise_for_status()
                    if time.monotonic() - idle_since >= args.idle_timeout:
                        raise RuntimeError('Coordinator kept rejecting task pulls')
                    await asyncio.sleep(args.poll_seconds)
                    continue
                response.raise_for_status()
                task = response.json()['task']
                if task is None:
                    if time.monotonic() - idle_since >= args.idle_timeout:
                        return 0
                    await asyncio.sleep(args.poll_seconds)
                    continue
                if task['model_id'] != model_id or task['model_revision'] != MODEL_REVISION:
                    raise RuntimeError('Simulator received a non-simulation model')
                active = task
                lost.clear()
                print(f"SIMULATION claimed {task['task_id']}", flush=True)
                if args.crash_after_claim:
                    print('SIMULATION stopping without a result or further heartbeats.', flush=True)
                    return 17
                started = time.monotonic()
                try:
                    await asyncio.wait_for(lost.wait(), timeout=args.delay)
                except TimeoutError:
                    pass
                if not lost.is_set():
                    endpoint = 'fail' if args.fail_tasks else 'complete'
                    body = {'worker_id': worker, 'assignment_id': task['assignment_id']}
                    if args.fail_tasks:
                        body['error'] = {'code': 'SIMULATED_FAILURE', 'message': 'Intentional test failure'}
                    else:
                        body.update(results=predictions(task), execution_time_ms=int((time.monotonic()-started)*1000))
                    # Retry ambiguous uploads with exactly the same assignment and result.
                    for attempt in range(3):
                        try:
                            r = await client.post(f"/api/tasks/{task['task_id']}/{endpoint}", json=body)
                            if r.status_code == 409:
                                print('Assignment superseded; discarding simulated result.', flush=True)
                                break
                            r.raise_for_status()
                            print(f"SIMULATION {r.json()['status']}", flush=True)
                            break
                        except httpx.HTTPError:
                            if attempt == 2:
                                raise
                            await asyncio.sleep(args.poll_seconds)
                active = None
                processed += 1
                idle_since = time.monotonic()
        finally:
            beat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await beat
        return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8000')
    parser.add_argument('--name', default='Simulated-Worker')
    parser.add_argument('--delay', type=float, default=2)
    parser.add_argument('--poll-seconds', type=float, default=1)
    parser.add_argument('--idle-timeout', type=float, default=30)
    parser.add_argument('--max-tasks', type=int, default=100)
    parser.add_argument('--crash-after-claim', action='store_true')
    parser.add_argument('--fail-tasks', action='store_true')
    parser.add_argument('--ui-modes', action='store_true', help='Fabricated fixtures for all UI modes; requires simulation/ui model with revision v1')
    args = parser.parse_args()
    if min(args.delay,args.poll_seconds,args.idle_timeout) <= 0 or args.max_tasks < 1:
        parser.error('Durations and max-tasks must be positive')
    try:
        raise SystemExit(asyncio.run(run(args)))
    except (httpx.HTTPError, RuntimeError) as exc:
        print(f'Simulator stopped: {type(exc).__name__}. Check backend configuration and availability.')
        raise SystemExit(1)
    except KeyboardInterrupt:
        raise SystemExit(130)


if __name__ == '__main__':
    main()
