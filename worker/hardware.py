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


def previous_device_id():
    """Read the installation ID for one-time migration of an existing DB row."""
    from pathlib import Path
    from uuid import UUID
    import os
    path = Path(os.environ.get('WORKER_STATE_DIR', str(Path(__file__).resolve().parent / '.cache'))) / 'device-id'
    try:
        return str(UUID(path.read_text().strip()))
    except FileNotFoundError:
        return None


def device_id():
    """Mac identity survives repository copies. Never send the raw hardware UUID."""
    from pathlib import Path
    from uuid import UUID, uuid4, uuid5, NAMESPACE_URL
    import os
    import re
    path = Path(os.environ.get('WORKER_STATE_DIR', str(Path(__file__).resolve().parent / '.cache'))) / 'device-id'
    path.parent.mkdir(parents=True, exist_ok=True)
    # An explicit state directory preserves isolated test/simulator identities.
    if platform.system() == 'Darwin' and 'WORKER_STATE_DIR' not in os.environ:
        try:
            result = subprocess.run(['ioreg', '-rd1', '-c', 'IOPlatformExpertDevice'],
                                    capture_output=True, text=True, check=True, timeout=5)
            match = re.search(r'"IOPlatformUUID"\s*=\s*"([0-9A-Fa-f-]+)"', result.stdout)
            if match:
                hardware_id = str(UUID(match.group(1)))
                identity = str(uuid5(NAMESPACE_URL, 'dnhacks:mac:' + hardware_id))
                try:
                    with path.open('x') as file:
                        file.write(identity)
                except FileExistsError:
                    pass  # Retain the old alias until registration can migrate it.
                return identity
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
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
    lock_path = path / 'worker.lock'
    if platform.system() == 'Darwin' and 'WORKER_STATE_DIR' not in os.environ:
        import tempfile
        lock_path = Path(tempfile.gettempdir()) / f'dnhacks-worker-{device_id()}.lock'
    handle = lock_path.open('a')
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise RuntimeError('A worker is already running for this machine identity.')
    return handle
