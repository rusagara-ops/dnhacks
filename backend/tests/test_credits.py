"""Demo accounting tests use unique schemas on an explicitly supplied test DB."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select

from app.core.security import new_token
from app.db.database import get_db
from app.main import create_app
from app.models import Job, Task, TaskResult, Worker
from app.models.account import Account, Credential
from app.models.credit import CreditEntry, Wallet
from app.models.provider import ProviderPolicy
from app.schemas.credit import CreditGrantRequest
from app.schemas.job import JobCreateRequest
from app.schemas.task import TaskCompleteRequest, TaskFailRequest
from app.services import credits
from app.services.job_service import create_job
from app.services.recovery import recover_expired
from app.services.task_service import complete_task, fail_task, job_results
from test_scheduler_postgres import SETTINGS, claim, factory, seed


def accounts(factory, count=2, initial=100):
    with factory.begin() as db:
        rows = [Account(name=f'Member {i}') for i in range(count)]
        db.add_all(rows)
        db.flush()
        for row in rows:
            if initial:
                credits.grant_credits(db, row.id, initial, uuid4())
        return [row.id for row in rows]


def owned_worker(factory, owner_id):
    worker_id = seed(factory)[0]
    with factory.begin() as db:
        db.get(Worker, worker_id).owner_account_id = owner_id
        db.add(ProviderPolicy(worker_id=worker_id, sharing_enabled=True,
                              allowed_task_types=['sentiment-classification']))
    return worker_id


def metered_job(factory, owner_id, inputs=1, target=None):
    with factory() as db:
        return create_job(db, JobCreateRequest(task_type='sentiment-classification', inputs=['test'] * inputs,
                          target_worker_id=target), SETTINGS.inference_model_id,
                          SETTINGS.inference_model_revision, owner_account_id=owner_id)


def snapshot(factory, account_id):
    with factory.begin() as db:
        return credits.balance(db, account_id)


def completion(worker_id, assignment, execution_time_ms=1):
    return TaskCompleteRequest(worker_id=worker_id, assignment_id=assignment.assignment_id,
                              execution_time_ms=execution_time_ms,
                              results=[{'index': item.index, 'label': 'POSITIVE', 'score': .9} for item in assignment.inputs])


@pytest.mark.parametrize('task_type', ['sentiment-classification', 'summarization', 'document-qa',
                                      'information-extraction', 'coding-assistance'])
def test_quote_prices_inputs_and_not_text_length_or_task_category(task_type):
    payload = JobCreateRequest(task_type=task_type, inputs=['x', 'longer text'],
                               instruction='question?' if task_type == 'document-qa' else None)
    assert credits.quote(payload).model_dump() == {
        'total_inputs': 2, 'credits': 2, 'unit': 'demo credits', 'pricing_version': 'demo-v1'}


@pytest.mark.parametrize('amount', [0, -1, True, 1.5, '1', 1_000_001])
def test_grants_require_bounded_integer_amounts(amount):
    with pytest.raises(ValidationError):
        CreditGrantRequest(account_id=uuid4(), amount=amount, request_id=uuid4())


def test_empty_account_balance_and_immutable_grant_retry(factory):
    account_id = accounts(factory, count=1, initial=0)[0]
    assert snapshot(factory, account_id).available == 0
    request_id = uuid4()
    for _ in range(2):
        with factory.begin() as db:
            credits.grant_credits(db, account_id, 15, request_id)
    wallet = snapshot(factory, account_id)
    assert (wallet.available, wallet.reserved, wallet.lifetime_earned, wallet.total_entries) == (15, 0, 0, 1)
    with factory.begin() as db, pytest.raises(HTTPException) as error:
        credits.grant_credits(db, account_id, 16, request_id)
    assert error.value.status_code == 409
    with pytest.raises(ValueError, match='immutable'), factory.begin() as db:
        db.scalar(select(CreditEntry)).available_delta = 99
    assert snapshot(factory, account_id).available == 15


def test_insufficient_credit_creation_rolls_back_job_and_tasks(factory):
    buyer = accounts(factory, count=1, initial=1)[0]
    with pytest.raises(HTTPException) as error:
        metered_job(factory, buyer, inputs=2)
    assert error.value.status_code == 402
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Job)) == 0
        assert db.scalar(select(func.count()).select_from(Task)) == 0
    wallet = snapshot(factory, buyer)
    assert wallet.available == 1 and wallet.reserved == 0 and wallet.total_entries == 1


def test_reservation_and_completion_are_atomic_and_paid_once(factory):
    buyer, provider = accounts(factory)
    worker_id = owned_worker(factory, provider)
    job = metered_job(factory, buyer, inputs=3)
    assert (snapshot(factory, buyer).available, snapshot(factory, buyer).reserved) == (97, 3)
    with factory.begin() as db:
        credits.reserve_job(db, db.get(Job, job.id), buyer)
    assignment = claim(factory, worker_id)
    for elapsed in (999_999_999, 1):
        with factory() as db:
            result = complete_task(db, assignment.task_id, completion(worker_id, assignment, elapsed))
    assert result.status == 'already_completed'
    assert (snapshot(factory, buyer).available, snapshot(factory, buyer).reserved) == (97, 0)
    recipient = snapshot(factory, provider)
    assert recipient.available == 103 and recipient.lifetime_earned == 3
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(CreditEntry).where(CreditEntry.kind == 'earn')) == 1
        assert db.scalar(select(func.count()).select_from(TaskResult)) == 1


def test_partial_results_survive_final_failure_and_only_failed_inputs_refund(factory):
    buyer, provider = accounts(factory)
    worker_id = owned_worker(factory, provider)
    job = metered_job(factory, buyer, inputs=26)
    first = claim(factory, worker_id)
    with factory() as db:
        complete_task(db, first.task_id, completion(worker_id, first))
    assert snapshot(factory, provider).lifetime_earned == 25
    for attempt in range(3):
        task = claim(factory, worker_id)
        failure = TaskFailRequest(worker_id=worker_id, assignment_id=task.assignment_id,
                                  error={'code': 'TEST_FAILURE', 'message': 'Intentional test failure'})
        with factory() as db:
            result = fail_task(db, task.task_id, failure)
        assert result.status == ('failed' if attempt == 2 else 'requeued')
        assert snapshot(factory, buyer).reserved == (0 if attempt == 2 else 1)
    with factory() as db:
        assert fail_task(db, task.task_id, failure).status == 'already_failed'
    wallet = snapshot(factory, buyer)
    assert wallet.available == 75 and wallet.reserved == 0
    assert sum(row.kind == 'refund' for row in wallet.entries) == 1
    with factory() as db:
        results = job_results(db, job.id)
        assert results.status == 'FAILED' and results.completed_inputs == 25 and results.failed_inputs == 1
        assert len(results.results) == 25


def test_expired_final_assignment_refunds_once(factory):
    buyer, provider = accounts(factory)
    worker_id = owned_worker(factory, provider)
    metered_job(factory, buyer)
    assignment = claim(factory, worker_id)
    with factory.begin() as db:
        task = db.get(Task, assignment.task_id)
        task.attempt_count = 3
        task.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    for _ in range(2):
        with factory() as db:
            recover_expired(db, SETTINGS)
    wallet = snapshot(factory, buyer)
    assert wallet.available == 100 and wallet.reserved == 0
    assert sum(row.kind == 'refund' for row in wallet.entries) == 1
    assert snapshot(factory, provider).lifetime_earned == 0


def test_own_machine_settlement_conserves_balance(factory):
    owner = accounts(factory, count=1)[0]
    worker_id = owned_worker(factory, owner)
    metered_job(factory, owner, inputs=5)
    assignment = claim(factory, worker_id)
    with factory() as db:
        complete_task(db, assignment.task_id, completion(worker_id, assignment))
    wallet = snapshot(factory, owner)
    assert (wallet.available, wallet.reserved, wallet.lifetime_earned) == (100, 0, 5)
    assert sum(row.available_delta for row in wallet.entries) == wallet.available
    assert sum(row.reserved_delta for row in wallet.entries) == wallet.reserved
    assert sum(row.earned_delta for row in wallet.entries) == wallet.lifetime_earned


def test_legacy_jobs_do_not_create_credits_and_unowned_workers_cannot_claim_metered_jobs(factory):
    buyer, provider = accounts(factory)
    unowned = seed(factory)[0]
    owned = owned_worker(factory, provider)
    paid = metered_job(factory, buyer)
    assert claim(factory, unowned) is None
    with factory() as db:
        legacy = create_job(db, JobCreateRequest(task_type='sentiment-classification', inputs=['legacy']),
                            SETTINGS.inference_model_id, SETTINGS.inference_model_revision)
    task = claim(factory, unowned)
    assert task.job_id == legacy.id
    with factory() as db:
        complete_task(db, task.task_id, completion(unowned, task))
    assert snapshot(factory, provider).lifetime_earned == 0
    assert claim(factory, owned).job_id == paid.id


def test_concurrent_reservations_cannot_overdraw(factory):
    owner = accounts(factory, count=1, initial=1)[0]
    gate = Barrier(2)

    def reserve(_):
        gate.wait(timeout=10)
        try:
            return metered_job(factory, owner).id
        except HTTPException as error:
            return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(reserve, range(2)))
    assert outcomes.count(402) == 1
    assert snapshot(factory, owner).reserved == 1
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Job)) == 1


def test_concurrent_duplicate_completion_pays_once(factory):
    buyer, provider = accounts(factory)
    worker_id = owned_worker(factory, provider)
    metered_job(factory, buyer)
    task = claim(factory, worker_id)
    gate = Barrier(2)

    def finish(_):
        gate.wait(timeout=10)
        with factory() as db:
            return complete_task(db, task.task_id, completion(worker_id, task)).status

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(finish, range(2)))
    assert sorted(outcomes) == ['already_completed', 'completed']
    assert snapshot(factory, provider).lifetime_earned == 1


def test_failed_settlement_rolls_back_result_status_and_payer_debit(factory, monkeypatch):
    buyer, provider = accounts(factory)
    worker_id = owned_worker(factory, provider)
    metered_job(factory, buyer)
    task = claim(factory, worker_id)
    original = credits._apply

    def fail_provider_payment(db, wallet, **kwargs):
        if kwargs['kind'] == 'earn':
            raise RuntimeError('Simulated accounting storage failure')
        return original(db, wallet, **kwargs)

    monkeypatch.setattr(credits, '_apply', fail_provider_payment)
    with factory() as db, pytest.raises(RuntimeError, match='accounting storage failure'):
        complete_task(db, task.task_id, completion(worker_id, task))
    wallet = snapshot(factory, buyer)
    assert (wallet.available, wallet.reserved) == (99, 1)
    assert snapshot(factory, provider).lifetime_earned == 0
    with factory() as db:
        assert db.get(Task, task.task_id).status == 'ASSIGNED'
        assert db.get(TaskResult, task.task_id) is None
    monkeypatch.setattr(credits, '_apply', original)
    with factory() as db:
        assert complete_task(db, task.task_id, completion(worker_id, task)).status == 'completed'
    assert snapshot(factory, provider).lifetime_earned == 1


def test_settlement_cannot_be_refunded_and_refund_cannot_be_settled(factory):
    buyer, provider = accounts(factory)
    worker_id = owned_worker(factory, provider)
    first_job = metered_job(factory, buyer)
    first = claim(factory, worker_id)
    with factory() as db:
        complete_task(db, first.task_id, completion(worker_id, first))
    with pytest.raises(HTTPException) as error, factory.begin() as db:
        task = db.get(Task, first.task_id)
        task.status = 'FAILED'
        credits.refund_task(db, task, db.get(Job, first_job.id))
    assert error.value.status_code == 409
    second_job = metered_job(factory, buyer)
    second = claim(factory, worker_id)
    with factory.begin() as db:
        db.get(Task, second.task_id).attempt_count = 3
    with factory() as db:
        fail_task(db, second.task_id, TaskFailRequest(worker_id=worker_id, assignment_id=second.assignment_id,
                  error={'code': 'TEST_FAILURE', 'message': 'Intentional test failure'}))
    with pytest.raises(HTTPException) as error, factory.begin() as db:
        task = db.get(Task, second.task_id)
        task.status = 'COMPLETED'
        credits.settle_task(db, task, db.get(Job, second_job.id), db.get(Worker, worker_id))
    assert error.value.status_code == 409
    assert (snapshot(factory, buyer).available, snapshot(factory, buyer).reserved) == (99, 0)
    assert snapshot(factory, provider).lifetime_earned == 1


def test_opposite_account_transfers_lock_wallets_in_same_order(factory):
    first, second = accounts(factory)
    first_worker = owned_worker(factory, first)
    second_worker = owned_worker(factory, second)
    metered_job(factory, first, target=second_worker)
    metered_job(factory, second, target=first_worker)
    assignments = [(first_worker, claim(factory, first_worker)), (second_worker, claim(factory, second_worker))]
    gate = Barrier(2)

    def finish(item):
        worker_id, task = item
        gate.wait(timeout=10)
        with factory() as db:
            return complete_task(db, task.task_id, completion(worker_id, task)).status

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(finish, assignments)) == ['completed', 'completed']
    for account_id in (first, second):
        wallet = snapshot(factory, account_id)
        assert (wallet.available, wallet.reserved, wallet.lifetime_earned) == (100, 0, 1)


def test_concurrent_grant_retry_cannot_mint_twice_or_change_recipient(factory):
    first, second = accounts(factory, initial=0)
    request_id = uuid4()
    gate = Barrier(2)

    def grant(account_id):
        gate.wait(timeout=10)
        try:
            with factory.begin() as db:
                credits.grant_credits(db, account_id, 10, request_id)
            return 'granted'
        except HTTPException as error:
            return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(grant, [first, second]))
    assert outcomes.count('granted') == 1 and outcomes.count(409) == 1
    assert snapshot(factory, first).available + snapshot(factory, second).available == 10


def test_credit_api_scopes_own_history_and_admin_grants(factory):
    first, second = accounts(factory, initial=0)
    member_token, token_hash = new_token()
    worker_token, worker_hash = new_token()
    with factory.begin() as db:
        db.add(Credential(account_id=first, token_hash=token_hash, kind='account', label='Test member'))
        db.add(Credential(account_id=first, token_hash=worker_hash, kind='worker', device_id=uuid4(), label='Test worker'))
    from app.core.config import Settings
    app = create_app(Settings(_env_file=None, auth_mode='controlled', api_token='setup-test-token'))

    def sessions():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = sessions
    with TestClient(app) as client:
        app.state.sessions = factory
        assert client.get('/api/credits').status_code == 401
        grant = {'account_id': str(second), 'amount': 9, 'request_id': str(uuid4())}
        client.headers['Authorization'] = f'Bearer {member_token}'
        assert client.post('/api/credits/grants', json=grant).status_code == 403
        assert client.get('/api/credits').json()['account_id'] == str(first)
        assert client.get('/api/credits?account_id=' + str(second)).json()['account_id'] == str(first)
        assert client.post('/api/credits/quote', json={'task_type': 'summarization', 'inputs': ['a', 'b']}).json()['credits'] == 2
        client.headers['Authorization'] = f'Bearer {worker_token}'
        assert client.get('/api/credits').status_code == 403
        assert client.post('/api/credits/quote', json={'task_type': 'summarization', 'inputs': ['a']}).status_code == 403
        assert client.post('/api/credits/grants', json=grant).status_code == 403
        client.headers['Authorization'] = 'Bearer setup-test-token'
        assert client.get('/api/credits').status_code == 403
        for _ in range(2):
            response = client.post('/api/credits/grants', json=grant)
            assert response.status_code == 200, response.text
            assert response.json()['available'] == 9 and response.json()['total_entries'] == 1
