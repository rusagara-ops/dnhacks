"""Best-effort host telemetry. Missing GPU counters remain unknown, never zero."""
import json
import platform
import subprocess
import psutil

GIB = 1024 ** 3


def hardware():
    gpu = None
    cores = None
    unified = platform.system() == 'Darwin' and platform.machine() == 'arm64'
    if platform.system() == 'Darwin':
        try:
            result = subprocess.run(['system_profiler', 'SPDisplaysDataType', '-json'],
                                    capture_output=True, text=True, check=True, timeout=15)
            displays = json.loads(result.stdout).get('SPDisplaysDataType', [])
            if displays:
                gpu = displays[0].get('sppci_model') or displays[0].get('_name')
                value = displays[0].get('sppci_cores')
                if value and str(value).isdigit():
                    cores = int(value)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    return {'ram_gb': psutil.virtual_memory().total / GIB, 'gpu': gpu,
            'gpu_core_count': cores, 'gpu_memory_kind': 'unified' if unified else 'unknown',
            'gpu_memory_gb': None}


def memory_metrics():
    memory = psutil.virtual_memory()
    return {'ram_available_gb': memory.available / GIB, 'memory_utilization': memory.percent,
            'cpu_utilization': psutil.cpu_percent(), 'gpu_available_gb': None}


def device_id():
    """Stable per-install identity; never copy the ignored cache to another Mac."""
    from pathlib import Path
    from uuid import UUID, uuid4
    import os
    path = Path(os.environ.get('WORKER_STATE_DIR', str(Path(__file__).resolve().parent / '.cache'))) / 'device-id'
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('x') as file:
            file.write(str(uuid4()))
    except FileExistsError:
        pass
    return str(UUID(path.read_text().strip()))


def lock_worker():
    import fcntl
    import os
    from pathlib import Path
    path = Path(os.environ.get('WORKER_STATE_DIR', str(Path(__file__).resolve().parent / '.cache')))
    path.mkdir(parents=True, exist_ok=True)
    handle = (path / 'worker.lock').open('a')
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise RuntimeError('A worker is already running from this installation.')
    return handle
