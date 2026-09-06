"""Provider admission controls, independent of task leases and model execution."""
from datetime import timezone, timedelta
from fastapi import HTTPException
from sqlalchemy import select, func
from app.models import Worker, Task
from app.models.provider import ProviderPolicy, ExecutionAttempt
from app.schemas.provider import ALL_TASKS


def describe_policy(policy, worker):
    if policy is None:
        return dict(sharing_enabled=worker.owner_account_id is None, allowed_task_types=list(ALL_TASKS),
                    max_concurrent_tasks=2, min_ram_available_gb=0, availability=[])
    return {key: getattr(policy, key) for key in ('sharing_enabled', 'allowed_task_types',
            'max_concurrent_tasks', 'min_ram_available_gb', 'availability')}


def admission_reasons(worker, policy, now, active_count=0, task_type=None):
    p = describe_policy(policy, worker)
    reasons = []
    if not p['sharing_enabled']:
        reasons.append('SHARING_PAUSED')
    if not p['allowed_task_types'] or (task_type is not None and task_type not in p['allowed_task_types']):
        reasons.append('WORKLOAD_NOT_ALLOWED')
    if active_count >= p['max_concurrent_tasks']:
        reasons.append('PROVIDER_CONCURRENCY_LIMIT')
    if p['min_ram_available_gb'] > 0:
        if worker.ram_available_gb is None:
            reasons.append('PROVIDER_FREE_RAM_UNKNOWN')
        elif worker.ram_available_gb < p['min_ram_available_gb']:
            reasons.append('PROVIDER_FREE_RAM_LIMIT')
    utc = now.astimezone(timezone.utc)
    minute = utc.hour * 60 + utc.minute
    if p['availability'] and not any(utc.weekday() in window['days'] and
            window['start_minute'] <= minute < window['end_minute'] for window in p['availability']):
        reasons.append('OUTSIDE_PROVIDER_SCHEDULE')
    return reasons


def set_policy(db, worker_id, payload):
    with db.begin():
        # The same lock as scheduler claims makes pause vs. claim ordering explicit.
        worker = db.scalar(select(Worker).where(Worker.id == worker_id).with_for_update())
        if worker is None:
            raise HTTPException(404, 'Worker not found')
        if payload.min_ram_available_gb > worker.ram_gb:
            raise HTTPException(422, 'Minimum free RAM exceeds this worker’s total RAM')
        policy = db.get(ProviderPolicy, worker_id)
        if policy is None:
            policy = ProviderPolicy(worker_id=worker_id)
            db.add(policy)
        for key, value in payload.model_dump().items():
            setattr(policy, key, value)
        db.flush()
        return describe_policy(policy, worker)


def finish_attempt(db, task, worker, now, status, execution_ms=None):
    attempt = db.get(ExecutionAttempt, task.assignment_id)
    # An assignment already in flight at migration has no durable new-history row.
    if attempt is None:
        return
    attempt.status = status
    attempt.ended_at = now
    attempt.reported_execution_ms = execution_ms


def provider_workers(db, principal, settings):
    now = db.scalar(select(func.clock_timestamp()))
    query = select(Worker).order_by(Worker.created_at.desc(), Worker.id).limit(500)
    if principal.auth_mode == 'controlled' and principal.role != 'admin':
        query = query.where(Worker.owner_account_id == principal.account_id)
    workers = db.scalars(query).all()
    ids = [worker.id for worker in workers]
    policies = {p.worker_id: p for p in db.scalars(select(ProviderPolicy).where(ProviderPolicy.worker_id.in_(ids)))}
    counts = dict(db.execute(select(Task.assigned_worker_id, func.count()).where(
        Task.assigned_worker_id.in_(ids), Task.status.in_(['ASSIGNED', 'RUNNING'])).group_by(Task.assigned_worker_id)).all())
    attempts = db.execute(select(ExecutionAttempt.worker_id, ExecutionAttempt.status, func.count(),
        func.avg(ExecutionAttempt.reported_execution_ms)).where(ExecutionAttempt.worker_id.in_(ids))
        .group_by(ExecutionAttempt.worker_id, ExecutionAttempt.status)).all()
    metrics = {wid: dict(completed_tasks=0, failed_attempts=0, expired_attempts=0,
        observed_attempts=0, average_reported_execution_ms=None,
        scope='Assignments recorded since this feature was deployed; execution time is worker-reported. Not a security rating or network latency measurement.') for wid in ids}
    for wid, status, count, average in attempts:
        m = metrics[wid]
        m['observed_attempts'] += count
        key = {'COMPLETED': 'completed_tasks', 'FAILED': 'failed_attempts', 'EXPIRED': 'expired_attempts'}.get(status)
        if key:
            m[key] = count
        if status == 'COMPLETED' and average is not None:
            m['average_reported_execution_ms'] = round(float(average), 1)
    items = []
    for w in workers:
        policy = policies.get(w.id)
        reasons = admission_reasons(w, policy, now, counts.get(w.id, 0))
        if now - w.last_heartbeat > timedelta(seconds=settings.worker_timeout_seconds):
            reasons.append('OFFLINE')
        if counts.get(w.id, 0) >= max(1, len(w.models or [])):
            reasons.append('WORKER_BUSY')
        items.append(dict(worker_id=w.id, name=w.name, device_id=w.device_id, ram_gb=w.ram_gb,
            policy=describe_policy(policy, w), accepting_new_tasks=not reasons,
            admission_reasons=reasons, reliability=metrics[w.id]))
    return dict(items=items, auth_mode=principal.auth_mode)
