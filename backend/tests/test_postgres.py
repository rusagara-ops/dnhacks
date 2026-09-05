"""Run only against a disposable migrated PostgreSQL database, never shared Supabase."""
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import Settings
from app.db.database import make_engine
from app.main import create_app


def test_registry_postgres_lifecycle():
    url = os.environ.get('TEST_DATABASE_URL')
    if not url:
        pytest.skip('TEST_DATABASE_URL must point to a disposable migrated PostgreSQL database')
    engine = make_engine(url)
    worker_id = None
    try:
        with TestClient(create_app(Settings(_env_file=None, database_url=url, api_token='test-token'))) as client:
            client.headers['Authorization'] = 'Bearer test-token'
            assert client.get('/ready').status_code == 200
            response = client.post('/api/workers/register', json={
                'name': 'integration-test-' + str(uuid4()), 'hostname': 'test', 'cpu': 'test',
                'cpu_cores': 2, 'ram_gb': 4, 'supported_tasks': ['sentiment-classification']})
            assert response.status_code == 201, response.text
            worker_id = response.json()['worker_id']
            assert response.json()['heartbeat_interval_seconds'] == 5
            heartbeat = {'cpu_utilization': 50, 'memory_utilization': 25, 'active_tasks': 1}
            assert client.post(f'/api/workers/{worker_id}/heartbeat', json=heartbeat).status_code == 200
            def status():
                return next(w['status'] for w in client.get('/api/workers?limit=500').json() if w['id'] == worker_id)
            assert status() == 'BUSY'
            with engine.begin() as db:
                db.execute(text("UPDATE coordinator.workers SET last_heartbeat = now() - interval '30 seconds' WHERE id = :id"), {'id': worker_id})
            assert status() == 'OFFLINE'
            heartbeat['active_tasks'] = 0
            assert client.post(f'/api/workers/{worker_id}/heartbeat', json=heartbeat).status_code == 200
            assert status() == 'AVAILABLE'
            assert client.post(f'/api/workers/{uuid4()}/heartbeat', json=heartbeat).status_code == 404
            assert client.post(f'/api/workers/{worker_id}/heartbeat', json=heartbeat | {'cpu_utilization': 101}).status_code == 422
    finally:
        if worker_id:
            with engine.begin() as db:
                db.execute(text('DELETE FROM coordinator.workers WHERE id = :id'), {'id': worker_id})
        engine.dispose()
