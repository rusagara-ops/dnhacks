"""Explicit local GPU benchmark. Never connects to the coordinator or saves source/output text."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import statistics
import time

from hardware import hardware, memory_metrics, lock_worker
from inference import Summarizer, SUPPORTED_TASKS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-digest', required=True, help='Digest agreed with Abel')
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 100:
        parser.error('repeats must be between 1 and 100')
    with lock_worker():
        benchmark(args)


def benchmark(args):
    model = Summarizer()
    if model.model_revision != args.expected_digest:
        raise RuntimeError('Installed model digest does not match the agreed benchmark digest')
    measurements = []
    for mode in SUPPORTED_TASKS:
        task = {'model_id': model.model_id, 'model_revision': model.model_revision, 'task_type': mode,
                'inputs': [{'index': 0, 'text': 'The library approved $18,000 for evening staffing. Ada will present the pilot results on October 30.'}]}
        if mode == 'document-qa': task['instruction'] = 'What budget was approved?'
        if mode == 'coding-assistance':
            task['inputs'][0]['text'] = 'def average(values):\n    return sum(values) / len(values)'
            task['instruction'] = 'Explain the empty-list failure and suggest a guard. Do not execute code.'
        for index in range(args.repeats):
            before = memory_metrics()
            start = time.perf_counter()
            model.predict(task)
            elapsed = (time.perf_counter() - start) * 1000
            metrics = dict(model.last_metrics)
            duration = metrics['generation_duration_ms']
            metrics['tokens_per_second'] = (metrics['output_tokens'] * 1000 / duration
                                           if metrics['output_tokens'] is not None and duration else None)
            measurements.append({'task_type': mode, 'iteration': index + 1, 'execution_time_ms': elapsed,
                                 'inference_metrics': metrics, 'memory_before': before,
                                 'memory_after': memory_metrics(), 'gpu_model_memory_gb': model.gpu_memory_gb()})
            print(f'{mode}: completed iteration {index + 1}', flush=True)
    report = {'recorded_at': datetime.now(timezone.utc).isoformat(), 'hardware': hardware(),
              'platform': platform.platform(), 'python': platform.python_version(),
              'model_id': model.model_id, 'model_revision': model.model_revision,
              'scope': 'One physical host, warm model, short synthetic examples; memory snapshots are not peaks.',
              'measurements': measurements,
              'median_execution_ms': {mode: statistics.median(row['execution_time_ms'] for row in measurements if row['task_type'] == mode)
                                      for mode in SUPPORTED_TASKS}}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print('Benchmark report saved. Review only as evidence for this tested host.')


if __name__ == '__main__':
    main()
