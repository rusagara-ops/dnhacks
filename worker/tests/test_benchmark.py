import json
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import benchmark


def test_benchmark_records_four_modes_without_saving_inputs_or_outputs(monkeypatch, tmp_path):
    calls = []
    model = SimpleNamespace(model_id='test-model', model_revision='test-digest', gpu_memory_gb=lambda: None,
                            last_metrics={'prompt_tokens': None, 'output_tokens': 10, 'generation_duration_ms': 1000})
    model.predict = lambda task: calls.append(task) or [{'index': 0, 'text': 'Output must not be stored'}]
    monkeypatch.setattr(benchmark, 'Summarizer', lambda: model)
    monkeypatch.setattr(benchmark, 'hardware', lambda: {'ram_gb': 24})
    monkeypatch.setattr(benchmark, 'memory_metrics', lambda: {'ram_available_gb': 10})
    output = tmp_path / 'benchmark.json'
    benchmark.benchmark(SimpleNamespace(expected_digest='test-digest', repeats=1, output=output))
    report = json.loads(output.read_text())
    assert len(calls) == len(report['measurements']) == 4
    assert set(report['median_execution_ms']) == set(benchmark.SUPPORTED_TASKS)
    for row in report['measurements']:
        assert row['inference_metrics']['tokens_per_second'] == 10
        assert row['inference_metrics']['prompt_tokens'] is None
        assert row['gpu_model_memory_gb'] is None
    assert 'Output must not be stored' not in output.read_text()
    assert 'The library approved' not in output.read_text()
    assert 'SOURCE' not in output.read_text()
    assert 'instruction' not in output.read_text()


def test_benchmark_rejects_wrong_digest(monkeypatch, tmp_path):
    monkeypatch.setattr(benchmark, 'Summarizer', lambda: SimpleNamespace(model_revision='wrong'))
    with pytest.raises(RuntimeError, match='digest'):
        benchmark.benchmark(SimpleNamespace(expected_digest='expected', repeats=1, output=tmp_path / 'out.json'))
    assert not (tmp_path / 'out.json').exists()
