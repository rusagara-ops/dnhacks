import math
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inference import generation_metrics
from location import location_from_args


def test_generation_metrics_use_actual_token_generation_time():
    assert generation_metrics([{'prompt_eval_count': 30, 'eval_count': 10, 'eval_duration': 2_000_000_000,
                                'total_duration': 9_000_000_000},
                               {'prompt_eval_count': 40, 'eval_count': 20, 'eval_duration': 1_000_000_000}]) == {
        'prompt_tokens': 70, 'output_tokens': 30, 'generation_duration_ms': 3000}


@pytest.mark.parametrize('unknown', [None, -1, '20', True, float('inf'), float('nan')])
def test_missing_or_invalid_measurements_are_null(unknown):
    result = generation_metrics([{'prompt_eval_count': 20, 'eval_count': unknown, 'eval_duration': unknown}])
    assert result == {'prompt_tokens': 20, 'output_tokens': None, 'generation_duration_ms': None}
    assert all(value is None for value in generation_metrics([]).values())


def test_worker_location_is_optional_and_zero_is_valid():
    assert location_from_args(SimpleNamespace()) is None
    assert location_from_args(SimpleNamespace(site=' Campus ', latitude=0, longitude=0)) == {
        'site': 'Campus', 'region': None, 'latitude': 0, 'longitude': 0}


@pytest.mark.parametrize('changes', [{'latitude': None}, {'longitude': math.nan}, {'longitude': 181}, {'site': ' '}])
def test_invalid_worker_location_fails_before_model_loading(changes):
    with pytest.raises(ValueError):
        location_from_args(SimpleNamespace(**({'site': 'Campus', 'latitude': 0, 'longitude': 0} | changes)))
