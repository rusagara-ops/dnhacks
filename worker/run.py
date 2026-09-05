"""Real summary worker. Uses coordinator HTTP only; no database credentials."""
import argparse
import asyncio
import contextlib
import os
import time
import platform
import socket

from inference import Summarizer, SUPPORTED_TASKS
from hardware import hardware, memory_metrics

import httpx

async def run(args):
    print('Loading pinned summarization model before registration...', flush=True)
    model = await asyncio.to_thread(Summarizer)
    info = await asyncio.to_thread(hardware)
    token = os.environ.get('API_TOKEN', '')
    headers = {'Authorization': f'Bearer {token}'} if token else {}
    async with httpx.AsyncClient(base_url=args.url.rstrip('/'), headers=headers, timeout=10) as client:
        response = await client.post('/api/workers/register', json={
            'name': args.name, 'hostname': socket.gethostname(), 'cpu': platform.machine(), 'cpu_cores': os.cpu_count() or 1,
            **info, 'supported_tasks': SUPPORTED_TASKS,
            'model_id': model.model_id, 'model_revision': model.model_revision,
        })
        response.raise_for_status()
        worker = response.json()['worker_id']
        interval = response.json()['heartbeat_interval_seconds']
        print(f'WORKER registered {worker}', flush=True)
        active = None
        lost = asyncio.Event()

        async def heartbeat():
            while True:
                current = active
                payload = {**memory_metrics(), 'active_tasks': int(current is not None),
                           'gpu_model_memory_gb': await asyncio.to_thread(model.gpu_memory_gb)}
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
                        **memory_metrics(), 'active_tasks': 0})
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
                if task['model_id'] != model.model_id or task['model_revision'] != model.model_revision:
                    raise RuntimeError('Worker received an incompatible model')
                active = task
                lost.clear()
                print(f"WORKER claimed {task['task_id']}", flush=True)
                started = time.monotonic()
                failure = None
                try:
                    results = await asyncio.to_thread(model.predict, task)
                except Exception as exc:
                    failure = {'code': 'INFERENCE_FAILED', 'message': type(exc).__name__}
                if not lost.is_set():
                    endpoint = 'fail' if failure else 'complete'
                    body = {'worker_id': worker, 'assignment_id': task['assignment_id']}
                    if failure:
                        body['error'] = failure
                    else:
                        body.update(results=results, execution_time_ms=int((time.monotonic()-started)*1000))
                    # Retry ambiguous uploads with exactly the same assignment and result.
                    for attempt in range(3):
                        try:
                            r = await client.post(f"/api/tasks/{task['task_id']}/{endpoint}", json=body)
                            if r.status_code == 409:
                                print('Assignment superseded; discarding result.', flush=True)
                                break
                            r.raise_for_status()
                            print(f"WORKER {r.json()['status']}", flush=True)
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
    parser.add_argument('--name', default=socket.gethostname())
    parser.add_argument('--poll-seconds', type=float, default=1)
    parser.add_argument('--idle-timeout', type=float, default=86400)
    parser.add_argument('--max-tasks', type=int, default=10000)
    args = parser.parse_args()
    if min(args.poll_seconds,args.idle_timeout) <= 0 or args.max_tasks < 1:
        parser.error('Durations and max-tasks must be positive')
    try:
        raise SystemExit(asyncio.run(run(args)))
    except RuntimeError as exc:
        print(f'Worker stopped: {exc}')
        raise SystemExit(1)
    except httpx.HTTPError as exc:
        print(f'Worker stopped: {type(exc).__name__}. Check backend configuration and availability.')
        raise SystemExit(1)
    except KeyboardInterrupt:
        raise SystemExit(130)


if __name__ == '__main__':
    main()
