"""Small explicit registry; thresholds are demo policies, not measured model costs.

Free-memory thresholds describe additional headroom after a worker loads its model.
Do not count the loaded model's allocation again as free-memory demand.
"""
from dataclasses import asdict, dataclass
from fastapi import HTTPException


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    task_types: tuple[str, ...]
    min_total_ram_gb: float
    min_free_ram_gb: float
    gpu_required: bool
    min_free_vram_gb: float
    workload_metric: str
    performance_metric: str
    max_cpu_utilization: float = 85

    def describe(self):
        return asdict(self)


TEXT_TASKS = ('summarization', 'document-qa', 'information-extraction', 'coding-assistance')
MODEL_REGISTRY = {
    'gemma3:12b': ModelSpec('gemma3:12b', TEXT_TASKS, 16, 2, True, 1,
                          'input_tokens_and_output_budget', 'output_tokens_per_second'),
    'qwen2.5-coder:3b': ModelSpec('qwen2.5-coder:3b', ('coding-assistance',), 8, 1, True, 1,
                                'input_tokens_and_output_budget', 'output_tokens_per_second'),
    'simulation/ui': ModelSpec('simulation/ui', ('sentiment-classification',) + TEXT_TASKS,
                               0, 0, False, 0, 'inputs', 'inputs_per_second'),
    'simulation/sentiment': ModelSpec('simulation/sentiment', ('sentiment-classification',),
                                      0, 0, False, 0, 'inputs', 'inputs_per_second'),
}


def select_model(payload, settings):
    """Explicit selection must be registered and configured; omission is legacy-compatible."""
    requested = payload.model_id
    model_id = requested or settings.inference_model_id
    revision = settings.inference_model_revision
    spec = MODEL_REGISTRY.get(model_id)
    if requested and spec is None:
        raise HTTPException(422, 'Unknown model_id; see /api/models')
    if requested and requested not in ('gemma3:12b', 'qwen2.5-coder:3b') and (requested != settings.inference_model_id or not revision):
        raise HTTPException(503, 'Requested model is not configured on this coordinator')
    if spec and payload.task_type not in spec.task_types:
        raise HTTPException(422, 'The selected model does not support this task type')
    # Explicit real-model requests resolve their digest from online worker inventory
    # inside job_service's transaction; never borrow the default model's revision.
    return model_id, revision if model_id == settings.inference_model_id else None
