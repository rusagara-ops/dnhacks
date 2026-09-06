from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from app.core.config import Settings
from app.db.database import get_db, make_engine
from app.main import create_app
from app.models import Worker
from app.schemas.worker import WorkerRegisterRequest
from app.services.worker_service import describe_worker

PAYLOAD = {'name': 'Abel-Test-Worker', 'hostname': 'abel-laptop', 'cpu': 'Apple Silicon',
           'cpu_cores': 8, 'ram_gb': 16, 'supported_tasks': ['sentiment-classification']}


@pytest.fixture
def client():
    with TestClient(create_app(Settings(_env_file=None, database_url=None, api_token='test-token'))) as client:
        yield client


def test_health_without_database(client):
    assert client.get('/health').json() == {'status': 'ok'}
    assert client.get('/ready').status_code == 503
    assert client.get('/api/workers', headers={'Authorization': 'Bearer test-token'}).status_code == 503


def test_api_requires_configured_token(client):
    assert client.get('/api/workers').status_code == 401
    assert client.get('/api/activity').status_code == 401
    assert client.post('/api/workers/register', json=PAYLOAD).status_code == 401


@pytest.mark.parametrize('changes', [{'cpu_cores': 0}, {'ram_gb': -1}, {'supported_tasks': ['unknown']}, {'name': '   '}, {'unexpected': True}])
def test_registration_validation(changes):
    with pytest.raises(ValidationError):
        WorkerRegisterRequest(**(PAYLOAD | changes))


def test_presence_and_recovery():
    now = datetime.now(timezone.utc)
    worker = Worker(**WorkerRegisterRequest(**PAYLOAD).model_dump(), id=uuid4(),
                    cpu_utilization=0, memory_utilization=0, active_tasks=0,
                    last_heartbeat=now, created_at=now, updated_at=now)
    assert describe_worker(worker, now, 15).status == 'AVAILABLE'
    worker.active_tasks = 1
    assert describe_worker(worker, now, 15).status == 'BUSY'
    assert describe_worker(worker, now + timedelta(seconds=16), 15).status == 'OFFLINE'
    worker.last_heartbeat = now + timedelta(seconds=17)
    worker.active_tasks = 0
    assert describe_worker(worker, worker.last_heartbeat, 15).status == 'AVAILABLE'


def test_database_failure_does_not_leak_details(client):
    def broken_db():
        raise OperationalError('private statement', {'password': 'secret-value'}, Exception('private-host'))
        yield
    client.app.dependency_overrides[get_db] = broken_db
    result = client.get('/api/workers', headers={'Authorization': 'Bearer test-token'})
    assert result.status_code == 503
    assert 'secret-value' not in result.text and 'private-host' not in result.text


def test_postgres_url_normalization():
    engine = make_engine('postgresql://example:example@localhost/example')
    assert engine.dialect.driver == 'psycopg'
    engine.dispose()
    with pytest.raises(ValueError):
        make_engine('sqlite://')


def test_cors(client):
    result = client.options('/api/workers', headers={
        'Origin': 'http://localhost:5173', 'Access-Control-Request-Method': 'GET',
        'Access-Control-Request-Headers': 'authorization'})
    assert result.status_code == 200
    assert result.headers['access-control-allow-origin'] == 'http://localhost:5173'
