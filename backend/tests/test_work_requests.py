"""Focused rehearsal for provider-mediated work requests."""

from uuid import uuid4

from test_controlled_auth import account, controlled, headers, register, worker_key
from test_scheduler_postgres import factory


def enabled_policy():
    return dict(sharing_enabled=True, allowed_task_types=['sentiment-classification'],
                max_concurrent_tasks=1, min_ram_available_gb=0, availability=[])


def setup_accounts(client):
    buyer = account(client, 'Ronald')
    provider = account(client, 'Abel')
    credential, device = worker_key(client, provider['token'])
    worker_id = register(client, credential['token'], device)
    provider_headers = headers(provider['token'])
    assert client.post(f'/api/provider/workers/{worker_id}/policy', json=enabled_policy(),
                       headers=provider_headers).status_code == 200
    return buyer, provider, worker_id, provider_headers


def test_provider_directory_request_and_decision(controlled):
    client = controlled
    buyer, provider, worker_id, provider_headers = setup_accounts(client)
    buyer_headers = headers(buyer['token'])

    directory = client.get('/api/work-requests/providers', headers=buyer_headers)
    assert directory.status_code == 200
    item = next(value for value in directory.json() if value['worker_id'] == worker_id)
    assert item['provider_name'] == 'Abel'
    assert 'sentiment-classification' in item['task_types']

    created = client.post('/api/work-requests', headers=buyer_headers, json={
        'provider_account_id': provider['account']['id'], 'worker_id': str(worker_id),
        'task_type': 'sentiment-classification', 'model_id': 'test/model'})
    assert created.status_code == 201
    request_id = created.json()['id']
    assert created.json()['status'] == 'PENDING'
    assert client.get('/api/work-requests', headers=provider_headers).json()[0]['id'] == request_id

    assert client.post(f'/api/work-requests/{request_id}/approve', headers=buyer_headers).status_code == 404
    approved = client.post(f'/api/work-requests/{request_id}/approve', headers=provider_headers)
    assert approved.status_code == 200 and approved.json()['status'] == 'APPROVED'

    grant = client.post('/api/credits/grants', headers=headers('test-setup-only'), json={
        'account_id': buyer['account']['id'], 'amount': 2, 'request_id': str(uuid4())})
    assert grant.status_code == 200
    job = client.post('/api/jobs', headers=buyer_headers, json={
        'task_type': 'sentiment-classification', 'model_id': 'test/model', 'inputs': ['hello'],
        'work_request_id': request_id})
    assert job.status_code == 201
    assert client.get('/api/work-requests', headers=buyer_headers).json()[0]['status'] == 'USED'


def test_direct_job_submission_does_not_require_request(controlled):
    client = controlled
    buyer, provider, worker_id, _ = setup_accounts(client)
    buyer_headers = headers(buyer['token'])
    assert client.post('/api/credits/grants', headers=headers('test-setup-only'), json={
        'account_id': buyer['account']['id'], 'amount': 2, 'request_id': str(uuid4())}).status_code == 200
    direct = client.post('/api/jobs', headers=buyer_headers, json={
        'task_type': 'sentiment-classification', 'model_id': 'test/model',
        'target_worker_id': str(worker_id), 'inputs': ['hello']})
    assert direct.status_code == 201
