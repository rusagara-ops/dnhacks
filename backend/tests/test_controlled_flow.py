"""HTTP rehearsal: enroll, enable, reserve, execute, refund, and revoke."""
from uuid import uuid4
from app.schemas.provider import ALL_TASKS
from test_scheduler_postgres import factory
from test_controlled_auth import controlled, account, worker_key, register, headers, registration


def test_provider_credit_partial_failure_and_revocation_end_to_end(controlled):
    client = controlled
    buyer = account(client, 'Buyer')
    provider = account(client, 'Provider')
    key, device = worker_key(client, provider['token'])
    worker_id = register(client, key['token'], device)
    h_provider, h_buyer, h_worker = headers(provider['token']), headers(buyer['token']), headers(key['token'])
    endpoint = f'/api/provider/workers/{worker_id}/policy'
    initial = client.get('/api/provider/workers', headers=h_provider).json()['items'][0]
    assert initial['policy']['sharing_enabled'] is False
    assert client.get('/api/provider/workers', headers=h_buyer).json()['items'] == []
    enabled = dict(sharing_enabled=True, allowed_task_types=ALL_TASKS,
                   max_concurrent_tasks=1, min_ram_available_gb=0, availability=[])
    assert client.post(endpoint, json=enabled, headers=h_buyer).status_code == 403
    assert client.post(endpoint, json=enabled, headers=h_worker).status_code == 403
    assert client.post(endpoint, json=enabled, headers=h_provider).status_code == 200
    # Re-registering cannot overwrite provider controls or ownership.
    assert client.post('/api/workers/register', json=registration(device), headers=h_worker).status_code == 201
    assert client.get('/api/provider/workers', headers=h_provider).json()['items'][0]['policy']['max_concurrent_tasks'] == 1
    grant = dict(account_id=buyer['account']['id'], amount=30, request_id=str(uuid4()))
    assert client.post('/api/credits/grants', json=grant, headers=headers('test-setup-only')).status_code == 200
    payload = dict(task_type='sentiment-classification', inputs=['demo input']*26)
    quote = client.post('/api/credits/quote', json=payload, headers=h_buyer).json()
    assert quote['credits'] == 26
    created = client.post('/api/jobs', json=payload, headers=h_buyer)
    assert created.status_code == 201
    jid = created.json()['job_id']
    wallet = client.get('/api/credits', headers=h_buyer).json()
    assert (wallet['available'], wallet['reserved']) == (4, 26)
    pull = f'/api/workers/{worker_id}/next-task'
    task = client.post(pull, headers=h_worker).json()['task']
    assert client.post(endpoint, json=enabled | {'sharing_enabled':False}, headers=h_provider).status_code == 200
    diagnostics = client.get(f'/api/jobs/{jid}/eligibility', headers=h_buyer).json()['workers']
    assert 'SHARING_PAUSED' in next(w['reasons'] for w in diagnostics if w['worker_id'] == worker_id)
    completion = dict(worker_id=worker_id, assignment_id=task['assignment_id'], execution_time_ms=12,
                      results=[dict(index=i['index'], label='POSITIVE', score=.9) for i in task['inputs']])
    complete = f"/api/tasks/{task['task_id']}/complete"
    assert client.post(complete, json=completion, headers=h_worker).json()['status'] == 'completed'
    assert client.post(complete, json=completion, headers=h_worker).json()['status'] == 'already_completed'
    assert client.post(pull, headers=h_worker).json()['task'] is None
    assert client.post(endpoint, json=enabled, headers=h_provider).status_code == 200
    for _ in range(3):
        task = client.post(pull, headers=h_worker).json()['task']
        failed = client.post(f"/api/tasks/{task['task_id']}/fail", headers=h_worker,
            json=dict(worker_id=worker_id, assignment_id=task['assignment_id'],
                      error=dict(code='INFERENCE_FAILED', message='synthetic rehearsal')))
        assert failed.status_code == 200
    result = client.get(f'/api/jobs/{jid}/results', headers=h_buyer).json()
    assert result['status'] == 'FAILED' and result['completed_inputs'] == 25 and result['failed_inputs'] == 1
    assert len(result['results']) == 25
    assert client.get(f'/api/jobs/{jid}/results', headers=h_provider).status_code == 404
    assert client.get(f'/api/jobs/{jid}/results', headers=h_worker).status_code == 403
    buyer_wallet = client.get('/api/credits', headers=h_buyer).json()
    seller_wallet = client.get('/api/credits', headers=h_provider).json()
    assert (buyer_wallet['available'], buyer_wallet['reserved']) == (5, 0)
    assert (seller_wallet['available'], seller_wallet['lifetime_earned']) == (25, 25)
    history = client.get('/api/provider/workers', headers=h_provider).json()['items'][0]['reliability']
    assert history['completed_tasks'] == 1 and history['failed_attempts'] == 3 and history['observed_attempts'] == 4
    assert client.post('/api/credentials/'+key['credential']['id']+'/revoke', headers=h_provider).status_code == 200
    assert client.post(pull, headers=h_worker).status_code == 401
