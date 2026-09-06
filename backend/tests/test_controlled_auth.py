"""Cross-account and installation boundaries exercised through real HTTP routes."""
from datetime import datetime, timezone
import hashlib
import importlib
import os
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select, text

from app.core.config import Settings
from app.db.database import get_db
from app.main import create_app
from app.models import Job, Task, TaskResult, Worker
from app.models.account import Account, Credential
from app.schemas.job import JobCreateRequest
from app.schemas.worker import WorkerRegisterRequest
from app.services.job_service import create_job
from app.services.worker_service import register_worker
from test_scheduler_postgres import factory, seed


def headers(token):
    return {'Authorization': f'Bearer {token}'}


@pytest.fixture
def controlled(factory):
    settings = Settings(_env_file=None, auth_mode='controlled', api_token='test-setup-only',
                        database_url=None, inference_model_id='test/model', inference_model_revision='test-revision')
    app = create_app(settings)
    def session():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = session
    with TestClient(app) as client:
        app.state.sessions = factory
        yield client


def account(client, name, role='member'):
    response = client.post('/api/accounts', headers=headers('test-setup-only'), json={'name': name, 'role': role})
    assert response.status_code == 201
    assert response.headers['Cache-Control'] == 'no-store'
    return response.json()


def worker_key(client, token, device_id=None):
    device_id = device_id or uuid4()
    response = client.post('/api/credentials', headers=headers(token), json={'device_id': str(device_id), 'label': 'Test installation'})
    assert response.status_code == 201
    return response.json(), device_id


def registration(device_id):
    return {'device_id': str(device_id), 'name': 'Test GPU', 'hostname': 'test-host', 'cpu': 'test',
            'cpu_cores': 1, 'ram_gb': 8, 'supported_tasks': ['sentiment-classification'],
            'model_id': 'test/model', 'model_revision': 'test-revision'}


def register(client, token, device_id):
    response = client.post('/api/workers/register', headers=headers(token), json=registration(device_id))
    assert response.status_code == 201
    return response.json()['worker_id']


def test_controlled_mode_never_silently_opens_and_bootstrap_cannot_run_jobs():
    for setup in (None, 'setup'):
        app = create_app(Settings(_env_file=None, auth_mode='controlled', api_token=setup, database_url=None))
        with TestClient(app) as client:
            assert client.get('/health').status_code == 200
            for path in ('/api/me', '/api/models', '/api/jobs', '/api/stats', '/api/workers'):
                assert client.get(path).status_code == 401
            if setup:
                client.headers.update(headers(setup))
                assert client.get('/api/me').json()['credential_kind'] == 'bootstrap'
                assert client.get('/api/models').status_code == 403


@pytest.mark.parametrize('shared_token', [None, 'shared-demo-key'])
def test_startup_refuses_demo_mode_on_database_with_accounts(factory, monkeypatch, shared_token):
    main = importlib.import_module('app.main')
    # The startup path receives a real PostgreSQL engine, scoped to this test's
    # generated schema; no production or shared coordinator rows are touched.
    monkeypatch.setattr(main, 'make_engine', lambda _: factory.kw['bind'])
    settings = Settings(_env_file=None, database_url=os.environ['TEST_DATABASE_URL'],
                        auth_mode='demo', api_token=shared_token)
    with TestClient(create_app(settings)) as client:
        assert client.get('/health').status_code == 200
    with factory.begin() as db:
        db.add(Account(name='Private account'))
    with pytest.raises(RuntimeError, match='AUTH_MODE=controlled'):
        with TestClient(create_app(settings)):
            pytest.fail('A shared demo must not open an account-owned database')
    with TestClient(create_app(settings.model_copy(update={'auth_mode': 'controlled'}))) as client:
        assert client.get('/health').status_code == 200
        assert client.get('/api/jobs').status_code == 401


def test_startup_guard_preserves_pre_migration_database_behavior(factory, monkeypatch):
    main = importlib.import_module('app.main')
    engine = factory.kw['bind']
    schema = engine.get_execution_options()['schema_translate_map']['coordinator']
    # This is exclusively the disposable schema created by the factory fixture.
    with engine.begin() as connection:
        connection.execute(text(f'DROP TABLE "{schema}".accounts CASCADE'))
    monkeypatch.setattr(main, 'make_engine', lambda _: engine)
    with TestClient(create_app(Settings(_env_file=None, auth_mode='demo',
                                       database_url=os.environ['TEST_DATABASE_URL']))) as client:
        assert client.get('/health').status_code == 200


def test_demo_identity_cannot_grant_credits_even_with_injected_database(factory):
    from app.models.credit import Wallet
    with factory.begin() as db:
        owner = Account(name='Private account')
        db.add(owner)
        db.flush()
        account_id = owner.id
    app = create_app(Settings(_env_file=None, auth_mode='demo', database_url=None, api_token=None))
    def session():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = session
    with TestClient(app) as client:
        response = client.post('/api/credits/grants', json={'account_id': str(account_id),
                               'amount': 100, 'request_id': str(uuid4())})
        assert response.status_code == 409
    with factory() as db:
        assert db.get(Wallet, account_id) is None


def test_credentials_are_hashed_scoped_and_revocable(controlled, factory):
    client = controlled
    a, b = account(client, 'A'), account(client, 'B')
    key, device = worker_key(client, a['token'])
    assert client.get('/api/me', headers=headers(a['token'])).json()['account_id'] == a['account']['id']
    metadata = client.get('/api/credentials', headers=headers(a['token'])).json()
    assert len(metadata) == 2
    assert all('token' not in row and 'token_hash' not in row for row in metadata)
    with factory() as db:
        stored = db.get(Credential, UUID(key['credential']['id']))
        assert stored.token_hash == hashlib.sha256(key['token'].encode()).hexdigest()
        assert stored.token_hash != key['token']
    assert client.get('/api/accounts', headers=headers(a['token'])).status_code == 403
    for path in ('/api/credentials', '/api/accounts', '/api/jobs', '/api/activity', '/api/stats', '/api/models', '/api/workers'):
        assert client.get(path, headers=headers(key['token'])).status_code == 403
    endpoint = '/api/credentials/' + key['credential']['id'] + '/revoke'
    assert client.post(endpoint, headers=headers(b['token'])).status_code == 404
    assert client.post(endpoint, headers=headers(a['token'])).status_code == 200
    assert client.get('/api/me', headers=headers(key['token'])).status_code == 401
    with factory.begin() as db:
        db.get(Account, UUID(a['account']['id'])).enabled = False
    assert client.get('/api/me', headers=headers(a['token'])).status_code == 401


def test_admin_recovery_preserves_account_and_balance_until_explicit_revocation(controlled, factory):
    client = controlled
    owner, admin = account(client, 'Owner'), account(client, 'Administrator', 'admin')
    account_id = owner['account']['id']
    endpoint = f'/api/accounts/{account_id}/credentials'
    admin_auth, owner_auth = headers(admin['token']), headers(owner['token'])
    grant = client.post('/api/credits/grants', headers=admin_auth,
                        json={'account_id': account_id, 'amount': 17, 'request_id': str(uuid4())})
    assert grant.status_code == 200
    initial = client.get(endpoint, headers=admin_auth).json()
    assert len(initial) == 1
    assert client.get(endpoint, headers=owner_auth).status_code == 403
    assert client.post(endpoint, headers=owner_auth, json={'label': 'Unauthorized recovery'}).status_code == 403
    replacement = client.post(endpoint, headers=admin_auth, json={'label': 'Replacement account key'})
    assert replacement.status_code == 201
    assert replacement.headers['Cache-Control'] == 'no-store'
    token = replacement.json()['token']
    assert replacement.json()['credential']['kind'] == 'account'
    assert replacement.json()['credential']['device_id'] is None
    for auth in (owner_auth, headers(token)):
        assert client.get('/api/me', headers=auth).json()['account_id'] == account_id
        assert client.get('/api/credits', headers=auth).json()['available'] == 17
    assert client.post('/api/credentials/' + initial[0]['id'] + '/revoke', headers=admin_auth).status_code == 200
    assert client.get('/api/me', headers=owner_auth).status_code == 401
    assert client.get('/api/credits', headers=headers(token)).json()['available'] == 17
    # Recovery also works after the last existing key has already been revoked.
    replacement_id = replacement.json()['credential']['id']
    assert client.post('/api/credentials/' + replacement_id + '/revoke', headers=admin_auth).status_code == 200
    recovered = client.post(endpoint, headers=headers('test-setup-only'), json={'label': 'Lost credential recovery'})
    assert recovered.status_code == 201
    assert client.get('/api/me', headers=headers(recovered.json()['token'])).json()['account_id'] == account_id
    assert client.get('/api/credits', headers=headers(recovered.json()['token'])).json()['available'] == 17
    metadata = client.get(endpoint, headers=admin_auth).json()
    assert len(metadata) == 3
    assert all('token' not in row and 'token_hash' not in row for row in metadata)
    with factory.begin() as db:
        db.get(Account, UUID(account_id)).enabled = False
    assert client.post(endpoint, headers=admin_auth, json={'label': 'Do not reactivate disabled account'}).status_code == 409
    assert client.post(f'/api/accounts/{uuid4()}/credentials', headers=admin_auth,
                       json={'label': 'Missing account'}).status_code == 404


def test_controlled_api_responses_are_never_cacheable(controlled):
    client = controlled
    owner = account(client, 'Owner')
    auth = headers(owner['token'])
    for path in ('/api/me', '/api/jobs', '/api/credits', '/api/credentials', '/api/activity', '/api/stats'):
        response = client.get(path, headers=auth)
        assert response.status_code == 200
        assert response.headers['Cache-Control'] == 'no-store'
    for response in (client.get('/api/jobs'), client.get('/api/accounts', headers=auth),
                     client.get(f'/api/jobs/{uuid4()}/results', headers=auth)):
        assert response.status_code in (401, 403, 404)
        assert response.headers['Cache-Control'] == 'no-store'


def test_worker_keys_cannot_impersonate_another_installation_or_owner(controlled, factory):
    client = controlled
    a, b = account(client, 'A'), account(client, 'B')
    ka, da = worker_key(client, a['token'])
    kb, db_id = worker_key(client, b['token'])
    wa, wb = register(client, ka['token'], da), register(client, kb['token'], db_id)
    assert register(client, ka['token'], da) == wa
    with factory() as db:
        assert db.get(Worker, UUID(wa)).owner_account_id == UUID(a['account']['id'])
    assert client.post('/api/workers/register', headers=headers(a['token']), json=registration(da)).status_code == 403
    assert client.post('/api/workers/register', headers=headers(ka['token']), json=registration(db_id)).status_code == 403
    changed = registration(da) | {'previous_device_id': str(db_id)}
    assert client.post('/api/workers/register', headers=headers(ka['token']), json=changed).status_code == 403
    other_key, other_device = worker_key(client, a['token'])
    heartbeat = {'cpu_utilization': 0, 'memory_utilization': 0, 'active_tasks': 0}
    assert client.post(f'/api/workers/{wa}/heartbeat', headers=headers(ka['token']), json=heartbeat).status_code == 200
    for token in (kb['token'], other_key['token'], b['token']):
        assert client.post(f'/api/workers/{wa}/heartbeat', headers=headers(token), json=heartbeat).status_code == 403
        assert client.post(f'/api/workers/{wa}/next-task', headers=headers(token)).status_code == 403
    fake_assignment = {'worker_id': wa, 'assignment_id': str(uuid4())}
    assert client.post(f'/api/tasks/{uuid4()}/complete', headers=headers(kb['token']), json=fake_assignment |
                       {'results': [{'index': 0, 'label': 'POSITIVE', 'score': .9}], 'execution_time_ms': 1}).status_code == 403
    assert client.post(f'/api/tasks/{uuid4()}/fail', headers=headers(kb['token']), json=fake_assignment |
                       {'error': {'code': 'TEST', 'message': 'test'}}).status_code == 403
    assert client.post(f'/api/workers/{wa}/location', headers=headers(kb['token']), json={'location': None}).status_code == 403
    assert client.post('/api/credentials', headers=headers(b['token']), json={'device_id': str(da), 'label': 'Steal'}).status_code == 403


def test_existing_installation_needs_explicit_admin_enrollment(controlled, factory):
    client = controlled
    a, b = account(client, 'A'), account(client, 'B')
    device = uuid4()
    with factory() as db:
        worker_id = register_worker(db, WorkerRegisterRequest(**registration(device))).id
    endpoint = f"/api/accounts/{a['account']['id']}/workers/{worker_id}/enroll"
    assert client.post(endpoint, headers=headers(a['token'])).status_code == 403
    assert client.post(endpoint, headers=headers('test-setup-only')).status_code == 200
    key, _ = worker_key(client, a['token'], device)
    assert register(client, key['token'], device) == str(worker_id)
    assert client.post(f"/api/accounts/{b['account']['id']}/workers/{worker_id}/enroll",
                       headers=headers('test-setup-only')).status_code == 409


def test_registration_cannot_claim_existing_row_with_preminted_foreign_key(controlled, factory):
    client = controlled
    a, b = account(client, 'A'), account(client, 'B')
    # Both credentials were issued before this random installation registered.
    ka, device = worker_key(client, a['token'])
    kb, _ = worker_key(client, b['token'], device)
    original = register(client, ka['token'], device)
    assert client.post('/api/workers/register', headers=headers(kb['token']), json=registration(device)).status_code == 403
    with factory() as db:
        assert db.get(Worker, UUID(original)).owner_account_id == UUID(a['account']['id'])


@pytest.mark.parametrize('role', ['member', 'admin'])
def test_worker_credential_never_inherits_account_or_admin_endpoints(controlled, role):
    client = controlled
    owner = account(client, 'Owner', role)
    key, device = worker_key(client, owner['token'])
    worker_id = register(client, key['token'], device)
    account_id, job_id = owner['account']['id'], uuid4()
    job = {'task_type': 'sentiment-classification', 'inputs': ['test']}
    calls = [
        ('GET', '/api/connection', None),
        ('GET', '/api/workers/locations?latitude=0&longitude=0', None),
        ('POST', '/api/workers/locations/search', {'latitude': 0, 'longitude': 0}),
        ('POST', '/api/jobs', job),
        ('GET', f'/api/jobs/{job_id}', None),
        ('GET', f'/api/jobs/{job_id}/results', None),
        ('GET', f'/api/jobs/{job_id}/eligibility', None),
        ('GET', '/api/provider/workers', None),
        ('POST', f'/api/provider/workers/{worker_id}/policy', {'sharing_enabled': True,
            'allowed_task_types': ['sentiment-classification'], 'max_concurrent_tasks': 1,
            'min_ram_available_gb': 0, 'availability': []}),
        ('GET', '/api/credits', None),
        ('POST', '/api/credits/quote', job),
        ('POST', '/api/credits/grants', {'account_id': account_id, 'amount': 1, 'request_id': str(uuid4())}),
        ('POST', '/api/accounts', {'name': 'Unauthorized administrator', 'role': 'admin'}),
        ('GET', f'/api/accounts/{account_id}/credentials', None),
        ('POST', f'/api/accounts/{account_id}/credentials', {'label': 'Escalated account credential'}),
        ('POST', '/api/credentials', {'device_id': str(uuid4()), 'label': 'Escalated credential'}),
        ('POST', f"/api/credentials/{key['credential']['id']}/revoke", None),
        ('POST', f'/api/accounts/{account_id}/workers/{worker_id}/enroll', None),
    ]
    for method, path, body in calls:
        response = client.request(method, path, headers=headers(key['token']), json=body)
        assert response.status_code == 403, (method, path, response.status_code)


def test_job_results_activity_and_counters_do_not_cross_accounts(controlled, factory):
    client = controlled
    a, b = account(client, 'A'), account(client, 'B')
    admin = account(client, 'Admin', 'admin')
    worker = seed(factory)[0]
    jobs = []
    for owner in (a, b):
        with factory() as db:
            job = create_job(db, JobCreateRequest(task_type='sentiment-classification', inputs=['Private input']),
                             'test/model', 'test-revision')
            jobs.append(job.id)
        with factory.begin() as db:
            job = db.get(Job, jobs[-1])
            job.owner_account_id = UUID(owner['account']['id'])
            job.status, job.completed_tasks = 'COMPLETED', 1
            task = db.scalar(select(Task).where(Task.job_id == job.id))
            task.status, task.assigned_worker_id, task.attempt_count = 'COMPLETED', worker, 1
            task.started_at = task.completed_at = datetime.now(timezone.utc)
            db.add(TaskResult(task_id=task.id, worker_id=worker, result=[{'index': 0, 'label': 'POSITIVE', 'score': .9}], execution_time_ms=12))
    for owner, own, other in ((a, jobs[0], jobs[1]), (b, jobs[1], jobs[0])):
        auth = headers(owner['token'])
        assert [row['id'] for row in client.get('/api/jobs', headers=auth).json()] == [str(own)]
        for suffix in ('', '/results', '/eligibility'):
            assert client.get(f'/api/jobs/{own}{suffix}', headers=auth).status_code == 200
            assert client.get(f'/api/jobs/{other}{suffix}', headers=auth).status_code == 404
        activity = client.get('/api/activity', headers=auth).json()
        assert {row['job_id'] for row in activity['recent_tasks']} == {str(own)}
        assert activity['task_counts'] == {'COMPLETED': 1}
        assert activity['worker_metrics'][0]['completed_inputs'] == 1
        stats = client.get('/api/stats', headers=auth).json()
        assert stats['jobs_completed'] == stats['tasks_completed'] == stats['total_inferences'] == 1
    assert len(client.get('/api/jobs', headers=headers(admin['token'])).json()) == 2
