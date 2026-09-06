from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from app.core.config import Settings
from app.db.database import get_db
from app.main import create_app
from app.models import Worker, Task
from app.schemas.worker import WorkerLocation, WorkerRegisterRequest
from app.schemas.job import JobCreateRequest
from app.schemas.task import TaskCompleteRequest, ReportedInferenceMetrics
from app.services.worker_service import register_worker
from app.services.locations import list_locations
from app.services.job_service import create_job
from app.services.task_service import complete_task, job_results
from test_scheduler_postgres import factory, seed, claim, SETTINGS


@pytest.mark.parametrize('changes', [
    {'latitude': 91}, {'longitude': -181}, {'latitude': float('nan')},
    {'longitude': float('inf')}, {'site': ' '}, {'extra': 'no'}, {'latitude': None},
])
def test_location_validation(changes):
    with pytest.raises(ValidationError):
        WorkerLocation(**({'site': 'Campus', 'latitude': 0, 'longitude': 0} | changes))


def test_location_auth_and_query_validation():
    app = create_app(Settings(_env_file=None, database_url=None, api_token='test'))
    app.dependency_overrides[get_db] = lambda: MagicMock()
    with TestClient(app) as client:
        assert client.get('/api/workers/locations').status_code == 401
        client.headers['Authorization'] = 'Bearer test'
        for query in ['latitude=0', 'longitude=0', 'latitude=91&longitude=0',
                      'latitude=nan&longitude=0', 'latitude=0&longitude=inf', 'limit=501', 'offset=-1']:
            assert client.get('/api/workers/locations?' + query).status_code == 422


def test_discovery_distance_sorting_pagination_and_filters(factory):
    ids = seed(factory, 4)
    with factory.begin() as db:
        for i, worker_id in enumerate(ids):
            worker = db.get(Worker, worker_id)
            worker.device_id = uuid4()
            worker.name = f'Worker {i}'
            worker.gpu = 'Test GPU' if i != 2 else None
            if i != 3:
                worker.location = {'site': 'Campus', 'latitude': 0, 'longitude': [0, 90, 180][i]}
        db.get(Worker, ids[1]).last_heartbeat = datetime.now(timezone.utc) - timedelta(seconds=600)
        db.get(Worker, ids[2]).model_revision = 'incompatible'
    with factory() as db:
        result = list_locations(db, SETTINGS, 0, 0, limit=2)
        assert result.total == 4
        assert [item.worker.id for item in result.items] == ids[:2]
        assert result.items[0].distance_km == 0
        assert result.items[1].distance_km == pytest.approx(10007.6, abs=.1)
        assert result.items[1].worker.status == 'OFFLINE'
        page = list_locations(db, SETTINGS, 0, 0, limit=2, offset=2)
        assert page.items[0].distance_km == pytest.approx(20015.1, abs=.1)
        assert not page.items[0].compatible
        assert page.items[1].distance_km is None and page.items[1].worker.location is None
        filtered = list_locations(db, SETTINGS, gpu_only=True, online_only=True)
        assert {item.worker.id for item in filtered.items} == {ids[0], ids[3]}
        assert all(item.distance_km is None for item in filtered.items)
        assert list_locations(db, SETTINGS, task_type='coding-assistance').total == 0


def test_distance_across_dateline(factory):
    worker_id = seed(factory)[0]
    with factory.begin() as db:
        db.get(Worker, worker_id).location = {'site': 'Dateline', 'latitude': 0, 'longitude': -179}
    with factory() as db:
        assert list_locations(db, SETTINGS, 0, 179).items[0].distance_km == pytest.approx(222.4, abs=.1)


@pytest.mark.parametrize('changes', [
    {'compute_origin_latitude': 0}, {'compute_origin_longitude': 0},
    {'compute_origin_latitude': 91, 'compute_origin_longitude': 0},
    {'compute_origin_latitude': 0, 'compute_origin_longitude': float('nan')},
])
def test_invalid_coordinator_origin(changes):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **changes)


def test_backend_origin_sorts_before_pagination_without_browser_coordinates(factory):
    far, unknown, near = seed(factory, 3)
    with factory.begin() as db:
        db.get(Worker, far).location = {'site': 'Far', 'latitude': 0, 'longitude': 90}
        db.get(Worker, far).name = 'A far worker'
        db.get(Worker, near).location = {'site': 'Near', 'latitude': 0, 'longitude': 0}
        db.get(Worker, near).name = 'Z near worker'
    settings = SETTINGS.model_copy(update={'compute_origin_latitude': 0, 'compute_origin_longitude': 0})
    with factory() as db:
        first = list_locations(db, settings, limit=1)
        assert first.distance_reference == 'coordinator'
        assert first.items[0].worker.id == near and first.items[0].distance_km == 0
        assert list_locations(db, settings, limit=1, offset=1).items[0].worker.id == far
        assert list_locations(db, settings, limit=1, offset=2).items[0].worker.id == unknown
        override = list_locations(db, settings, latitude=0, longitude=90, limit=1)
        assert override.distance_reference == 'request' and override.items[0].worker.id == far
        unset = list_locations(db, SETTINGS)
        assert unset.distance_reference == 'unavailable'
        assert all(item.distance_km is None for item in unset.items)


def test_location_registration_roundtrip_and_legacy(factory):
    payload = WorkerRegisterRequest(device_id=uuid4(), name='Campus GPU', hostname='host', cpu='test',
                                   cpu_cores=1, ram_gb=8, supported_tasks=['summarization'],
                                   location=WorkerLocation(site=' Campus ', latitude=40, longitude=-74))
    with factory() as db:
        worker = register_worker(db, payload)
        worker_id = worker.id
        assert worker.location['site'] == 'Campus'
    with factory() as db:
        updated = register_worker(db, payload.model_copy(update={'location': WorkerLocation(site='New campus', latitude=41, longitude=-73)}))
        assert updated.id == worker_id and updated.location['latitude'] == 41
    with factory() as db:
        legacy = register_worker(db, payload.model_copy(update={'location': None}))
        assert legacy.id == worker_id and legacy.location is None


def targeted(factory, worker_id):
    with factory() as db:
        return create_job(db, JobCreateRequest(task_type='sentiment-classification', inputs=['test'], target_worker_id=worker_id),
                          SETTINGS.inference_model_id, SETTINGS.inference_model_revision, SETTINGS.worker_timeout_seconds)


def test_selected_worker_is_enforced_even_after_lease_recovery(factory):
    a, b = seed(factory, 2)
    job = targeted(factory, a)
    assert claim(factory, b) is None
    task = claim(factory, a)
    assert task.job_id == job.id
    with factory.begin() as db:
        db.get(Task, task.task_id).lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert claim(factory, b) is None
    replacement = claim(factory, a)
    assert replacement.task_id == task.task_id and replacement.assignment_id != task.assignment_id


def test_selection_rejects_offline_missing_and_incompatible_workers(factory):
    stale = seed(factory, stale=True)[0]
    incompatible = seed(factory, model='other')[0]
    for worker_id, status in [(stale, 409), (incompatible, 422), (uuid4(), 422)]:
        with pytest.raises(HTTPException) as error:
            targeted(factory, worker_id)
        assert error.value.status_code == status


def test_metrics_are_saved_once_and_returned_with_attribution(factory):
    worker_id = seed(factory)[0]
    job = targeted(factory, worker_id)
    task = claim(factory, worker_id)
    payload = TaskCompleteRequest(worker_id=worker_id, assignment_id=task.assignment_id,
                                 results=[{'index': 0, 'label': 'POSITIVE', 'score': .9}], execution_time_ms=1500,
                                 inference_metrics={'prompt_tokens': 100, 'output_tokens': 20, 'generation_duration_ms': 1000})
    with factory() as db: assert complete_task(db, task.task_id, payload).status == 'completed'
    with factory() as db:
        duplicate = payload.model_copy(update={'inference_metrics': None})
        assert complete_task(db, task.task_id, duplicate).status == 'already_completed'
    with factory() as db:
        result = job_results(db, job.id)
        assert result.status == 'COMPLETED' and result.tasks[0].worker_id == worker_id
        assert result.tasks[0].inference_metrics.tokens_per_second == 20
        assert result.tasks[0].inference_metrics.prompt_tokens == 100


def test_unknown_and_zero_duration_metrics():
    assert ReportedInferenceMetrics().model_dump()['tokens_per_second'] is None
    assert ReportedInferenceMetrics(output_tokens=10, generation_duration_ms=0).tokens_per_second is None
    assert ReportedInferenceMetrics(output_tokens=0, generation_duration_ms=100).tokens_per_second == 0


def test_http_discovery_selection_and_persisted_results(factory):
    a, b = seed(factory, 2)
    with factory.begin() as db:
        db.get(Worker, a).location = {'site': 'Campus', 'latitude': 0, 'longitude': 0}
    app = create_app(SETTINGS.model_copy(update={'api_token': None}))
    def session():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = session
    with TestClient(app) as client:
        locations = client.get('/api/workers/locations?latitude=0&longitude=0')
        assert locations.status_code == 200, locations.text
        assert locations.json()['items'][0]['worker']['id'] == str(a)
        response = client.post('/api/jobs', json={'task_type': 'sentiment-classification', 'inputs': ['x'], 'target_worker_id': str(a)})
        assert response.status_code == 201, response.text
        job_id = response.json()['job_id']
        assert client.get('/api/jobs/' + job_id).json()['target_worker_id'] == str(a)
        assert client.post(f'/api/workers/{b}/next-task').json()['task'] is None
        task = client.post(f'/api/workers/{a}/next-task').json()['task']
        response = client.post(f"/api/tasks/{task['task_id']}/complete", json={
            'worker_id': str(a), 'assignment_id': task['assignment_id'], 'execution_time_ms': 1300,
            'results': [{'index': 0, 'label': 'POSITIVE', 'score': .9}],
            'inference_metrics': {'prompt_tokens': None, 'output_tokens': 10, 'generation_duration_ms': 1000}})
        assert response.status_code == 200, response.text
        result = client.get('/api/jobs/' + job_id + '/results').json()
        assert result['status'] == 'COMPLETED'
        assert result['tasks'][0]['inference_metrics'] == {
            'prompt_tokens': None, 'output_tokens': 10, 'generation_duration_ms': 1000, 'tokens_per_second': 10}


def test_worker_map_edit_auth_validation_and_registration_preservation(factory):
    app = create_app(Settings(_env_file=None, database_url=None, api_token='test'))
    def session():
        with factory() as db: yield db
    app.dependency_overrides[get_db] = session
    payload = dict(device_id=str(uuid4()), name='Owner GPU', hostname='owner', cpu='test', cpu_cores=1,
                   ram_gb=8, supported_tasks=['summarization'])
    with TestClient(app) as client:
        assert client.post(f'/api/workers/{uuid4()}/location', json={'location': None}).status_code == 401
        assert client.post('/api/workers/locations/search', json={'latitude': 0, 'longitude': 0}).status_code == 401
        client.headers['Authorization'] = 'Bearer test'
        worker_id = client.post('/api/workers/register', json=payload).json()['worker_id']
        original = client.get('/api/workers').json()[0]
        site = {'site': 'Campus', 'latitude': 0, 'longitude': 0}
        assert client.post(f'/api/workers/{worker_id}/location', json={'location': site | {'latitude': 91}}).status_code == 422
        assert client.post(f'/api/workers/{uuid4()}/location', json={'location': site}).status_code == 404
        updated = client.post(f'/api/workers/{worker_id}/location', json={'location': site})
        assert updated.status_code == 200, updated.text
        assert updated.json()['location']['site'] == 'Campus'
        assert updated.json()['last_heartbeat'] == original['last_heartbeat']
        assert updated.json()['active_tasks'] == original['active_tasks']
        # The ordinary startup omits location and must not erase the map edit.
        assert client.post('/api/workers/register', json=payload).json()['worker_id'] == worker_id
        assert client.get('/api/workers').json()[0]['location']['site'] == 'Campus'
        response = client.post('/api/workers/locations/search', json={'latitude': 0, 'longitude': 0})
        assert response.status_code == 200
        assert response.json()['distance_reference'] == 'request'
        assert response.json()['items'][0]['distance_km'] == 0
        assert client.post('/api/workers/locations/search', json={'latitude': 0}).status_code == 422
        assert client.post('/api/workers/locations/search', json={'latitude': 0, 'longitude': 'NaN'}).status_code == 422
        client.post(f'/api/workers/{worker_id}/location', json={'location': None})
        assert client.get('/api/workers').json()[0]['location'] is None


def test_gpu_allocation_is_discoverable_when_gpu_name_is_unknown(factory):
    worker_id = seed(factory)[0]
    with factory.begin() as db:
        db.get(Worker, worker_id).gpu_model_memory_gb = 4
    with factory() as db:
        result = list_locations(db, SETTINGS, gpu_only=True)
        assert result.items[0].worker.id == worker_id
