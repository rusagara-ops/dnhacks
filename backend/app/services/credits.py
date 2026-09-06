"""Fixed-price demo accounting; all writes participate in the caller's transaction.

Lifecycle callers lock worker -> task -> job first. This service then locks all
affected wallets by sorted account ID. No network calls or commits belong here.
Worker-reported timing, hardware and token counts never determine credit amounts.
"""
import hashlib
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.models.account import Account
from app.models.credit import CreditEntry, Wallet
from app.schemas.credit import CreditBalanceResponse, CreditEntryResponse, CreditQuote
from app.schemas.job import JobCreateRequest

PRICING_VERSION = 'demo-v1'
UNIT_COST = 1
MAX_BALANCE = 2**63 - 1


def quote(payload: JobCreateRequest) -> CreditQuote:
    return CreditQuote(total_inputs=len(payload.inputs), credits=len(payload.inputs) * UNIT_COST)


def _transaction_required(db):
    if not db.in_transaction():
        raise RuntimeError('Credit mutations require a caller-owned transaction')


def _lock_wallets(db, account_ids):
    """Create zero balances lazily; deterministic insert/lock order avoids deadlocks."""
    wallets = {}
    for account_id in sorted(set(account_ids), key=str):
        if db.get(Account, account_id) is None:
            raise HTTPException(404, 'Account not found')
        db.execute(insert(Wallet).values(account_id=account_id).on_conflict_do_nothing(index_elements=['account_id']))
        wallets[account_id] = db.scalar(select(Wallet).where(Wallet.account_id == account_id)
                                        .with_for_update().execution_options(populate_existing=True))
    return wallets


def _entry(db, key):
    return db.scalar(select(CreditEntry).where(CreditEntry.idempotency_key == key))


def _apply(db, wallet, *, key, kind, available, reserved=0, earned=0, job_id=None, task_id=None):
    balances = (wallet.available + available, wallet.reserved + reserved, wallet.lifetime_earned + earned)
    if any(value < 0 or value > MAX_BALANCE for value in balances):
        raise HTTPException(409, 'Credit balance cannot cover this operation')
    wallet.available, wallet.reserved, wallet.lifetime_earned = balances
    db.add(CreditEntry(account_id=wallet.account_id, job_id=job_id, task_id=task_id,
                       kind=kind, available_delta=available, reserved_delta=reserved,
                       earned_delta=earned, idempotency_key=key, pricing_version=PRICING_VERSION))


def grant_credits(db, account_id: UUID, amount: int, request_id: UUID):
    """Administrator-issued demo units; retries must reuse the same request ID."""
    _transaction_required(db)
    if isinstance(amount, bool) or not isinstance(amount, int) or not 1 <= amount <= 1_000_000:
        raise HTTPException(422, 'Grant amount must be an integer from 1 to 1000000')
    key = f'grant:{request_id}'
    # The request ID is globally unique, even if concurrently reused for a
    # different account. Acquire this before a wallet lock on all grant paths.
    advisory_key = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], 'big', signed=True)
    db.execute(select(func.pg_advisory_xact_lock(advisory_key)))
    previous = _entry(db, key)
    if previous:
        if previous.account_id != account_id or previous.available_delta != amount:
            raise HTTPException(409, 'Grant request ID was already used with different details')
        return
    wallet = _lock_wallets(db, [account_id])[account_id]
    _apply(db, wallet, key=key, kind='grant', available=amount)
    db.flush()


def reserve_job(db, job, account_id: UUID | None):
    """Reserve all bounded inputs atomically with job creation; legacy jobs are free."""
    if account_id is None:
        return
    _transaction_required(db)
    if job.owner_account_id != account_id:
        raise HTTPException(409, 'Job owner does not match its credit reservation')
    wallet = _lock_wallets(db, [account_id])[account_id]
    amount = job.total_inputs * UNIT_COST
    if not 1 <= job.total_inputs <= 1000:
        raise HTTPException(422, 'Job input count is outside demo pricing limits')
    key = f'reserve:{job.id}'
    previous = _entry(db, key)
    if previous:
        if previous.account_id != account_id or previous.reserved_delta != amount:
            raise HTTPException(409, 'Job already has a different credit reservation')
        return
    if wallet.available < amount:
        raise HTTPException(402, f'Insufficient demo credits: {amount} required, {wallet.available} available')
    _apply(db, wallet, key=key, kind='reserve', available=-amount, reserved=amount, job_id=job.id)
    db.flush()


def _reserved_task_amount(db, task, job):
    if task.job_id != job.id or not 1 <= task.input_count <= 25:
        raise HTTPException(409, 'Task does not match its credit reservation')
    reservation = _entry(db, f'reserve:{job.id}')
    if reservation is None or reservation.account_id != job.owner_account_id:
        raise HTTPException(409, 'Job credit reservation is missing')
    if reservation.pricing_version != PRICING_VERSION:
        raise HTTPException(409, 'Job credit pricing version is unsupported')
    amount = task.input_count * UNIT_COST
    # The payer wallet lock serializes checks and mutations for this job. Guard
    # the job reservation, not merely the wallet's aggregate reserved balance.
    used = db.scalar(select(func.coalesce(func.sum(-CreditEntry.reserved_delta), 0)).where(
        CreditEntry.job_id == job.id, CreditEntry.kind.in_(['spend', 'refund'])))
    if used + amount > reservation.reserved_delta:
        raise HTTPException(409, 'Job credit reservation is already exhausted')
    return amount


def settle_task(db, task, job, worker):
    """Move accepted task credits to its enrolled provider exactly once."""
    owner_id = getattr(job, 'owner_account_id', None)
    if owner_id is None:
        return
    _transaction_required(db)
    provider_id = getattr(worker, 'owner_account_id', None)
    if provider_id is None:
        raise HTTPException(409, 'Metered tasks require an enrolled provider')
    if task.status != 'COMPLETED':
        raise HTTPException(409, 'Only accepted completed tasks can earn demo credits')
    wallets = _lock_wallets(db, [owner_id, provider_id])
    key = f'task:{task.id}:debit'
    previous = _entry(db, key)
    if previous:
        if previous.kind != 'spend' or previous.account_id != owner_id:
            raise HTTPException(409, 'Task credits were already refunded')
        return
    amount = _reserved_task_amount(db, task, job)
    _apply(db, wallets[owner_id], key=key, kind='spend', available=0, reserved=-amount, job_id=job.id, task_id=task.id)
    _apply(db, wallets[provider_id], key=f'task:{task.id}:earn', kind='earn', available=amount,
           earned=amount, job_id=job.id, task_id=task.id)
    db.flush()


def refund_task(db, task, job):
    """Only terminal failure returns unspent reservations; retries keep them held."""
    owner_id = getattr(job, 'owner_account_id', None)
    if owner_id is None:
        return
    _transaction_required(db)
    if task.status != 'FAILED':
        raise HTTPException(409, 'Only permanently failed tasks can be refunded')
    wallet = _lock_wallets(db, [owner_id])[owner_id]
    key = f'task:{task.id}:debit'
    previous = _entry(db, key)
    if previous:
        if previous.kind != 'refund' or previous.account_id != owner_id:
            raise HTTPException(409, 'Task credits were already settled')
        return
    amount = _reserved_task_amount(db, task, job)
    _apply(db, wallet, key=key, kind='refund', available=amount, reserved=-amount, job_id=job.id, task_id=task.id)
    db.flush()


def balance(db, account_id: UUID, limit=50, offset=0) -> CreditBalanceResponse:
    """Return one internally consistent snapshot while holding a shared wallet lock."""
    wallet = db.scalar(select(Wallet).where(Wallet.account_id == account_id)
                       .with_for_update(read=True).execution_options(populate_existing=True))
    if wallet is None:
        if db.get(Account, account_id) is None:
            raise HTTPException(404, 'Account not found')
        return CreditBalanceResponse(account_id=account_id, available=0, reserved=0, lifetime_earned=0,
                                     entries=[], total_entries=0)
    entries = db.scalars(select(CreditEntry).where(CreditEntry.account_id == account_id)
                         .order_by(CreditEntry.created_at.desc(), CreditEntry.id.desc()).limit(limit).offset(offset))
    count = db.scalar(select(func.count()).select_from(CreditEntry).where(CreditEntry.account_id == account_id))
    return CreditBalanceResponse(account_id=account_id, available=wallet.available, reserved=wallet.reserved,
                                 lifetime_earned=wallet.lifetime_earned,
                                 entries=[CreditEntryResponse.model_validate(entry) for entry in entries], total_entries=count)
