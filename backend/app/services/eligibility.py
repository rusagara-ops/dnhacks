"""Pure eligibility rules shared by task assignment and diagnostics."""
from datetime import timedelta
from app.core.model_registry import MODEL_REGISTRY


def eligibility_reasons(worker, model_id, model_revision, task_type, now, timeout, active_model_ids=None):
    reasons = []
    if now - worker.last_heartbeat > timedelta(seconds=timeout):
        reasons.append('OFFLINE')
    inventory = getattr(worker, 'models', None) or []
    selected = next((m for m in inventory if m['model_id'] == model_id), None)
    busy = worker.active_tasks >= len(inventory) if inventory else bool(worker.active_tasks)
    if inventory and active_model_ids is not None:
        busy = busy or model_id in active_model_ids
    if busy:
        reasons.append('BUSY')
    tasks = selected['supported_tasks'] if selected else worker.supported_tasks
    if task_type not in tasks:
        reasons.append('TASK_UNSUPPORTED')
    if not model_id or not model_revision:
        reasons.append('JOB_MODEL_UNCONFIGURED')
    elif ((selected['model_id'], selected['model_revision']) if selected else (worker.model_id, worker.model_revision)) != (model_id, model_revision):
        reasons.append('MODEL_MISMATCH')
    spec = MODEL_REGISTRY.get(model_id)
    # Preserve existing deployments of models that predate the registry.
    if spec is None:
        return reasons
    if task_type not in spec.task_types:
        reasons.append('MODEL_TASK_UNSUPPORTED')
    if worker.ram_gb < spec.min_total_ram_gb:
        reasons.append('TOTAL_RAM_INSUFFICIENT')
    if spec.min_free_ram_gb:
        if worker.ram_available_gb is None:
            reasons.append('FREE_RAM_UNKNOWN')
        elif worker.ram_available_gb < spec.min_free_ram_gb:
            reasons.append('FREE_RAM_INSUFFICIENT')
    if worker.cpu_utilization > spec.max_cpu_utilization:
        reasons.append('CPU_OVERLOADED')
    if spec.gpu_required:
        if not worker.gpu:
            reasons.append('GPU_REQUIRED')
        if worker.gpu_model_memory_gb is None or worker.gpu_model_memory_gb <= 0:
            reasons.append('GPU_MODEL_NOT_CONFIRMED')
        if worker.gpu_memory_kind != 'unified' and spec.min_free_vram_gb:
            if worker.gpu_available_gb is None:
                reasons.append('FREE_VRAM_UNKNOWN')
            elif worker.gpu_available_gb < spec.min_free_vram_gb:
                reasons.append('FREE_VRAM_INSUFFICIENT')
    return reasons
