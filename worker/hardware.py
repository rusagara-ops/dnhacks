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
