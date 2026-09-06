"""Geographic discovery; distances are not network routes or latency estimates."""
from datetime import timedelta
from sqlalchemy import case, func, literal, select
from app.models import Worker
from app.schemas.worker import LocatedWorker, WorkerLocationsResponse
from app.services.worker_service import visible_workers, describe_worker

EARTH_RADIUS_KM = 6371.0088


def list_locations(db, settings, latitude=None, longitude=None, task_type=None,
                   gpu_only=False, online_only=False, limit=100, offset=0):
    reference = 'request' if latitude is not None else 'unavailable'
    if latitude is None and settings.compute_origin_latitude is not None:
        latitude, longitude = settings.compute_origin_latitude, settings.compute_origin_longitude
        reference = 'coordinator'
    now = db.scalar(select(func.clock_timestamp()))
    query = visible_workers(now, settings.worker_timeout_seconds)
    if gpu_only:
        query = query.where(Worker.gpu.is_not(None))
    if online_only:
        query = query.where(Worker.last_heartbeat >= now - timedelta(seconds=settings.worker_timeout_seconds))
    if task_type:
        query = query.where(Worker.supported_tasks.contains([task_type]))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    distance = literal(None)
    if latitude is not None:
        lat = Worker.location['latitude'].as_float()
        lon = Worker.location['longitude'].as_float()
        a = (func.power(func.sin(func.radians(lat - latitude) / 2), 2)
             + func.cos(func.radians(latitude)) * func.cos(func.radians(lat))
             * func.power(func.sin(func.radians(lon - longitude) / 2), 2))
        # Preserve NULL locations; clamp rounding at antipodes to avoid asin errors.
        distance = case((lat.is_not(None), 2 * EARTH_RADIUS_KM * func.asin(
            func.sqrt(func.least(1.0, func.greatest(0.0, a))))))
    rows = db.execute(query.add_columns(distance.label('distance_km')).order_by(
        distance.asc().nulls_last(), Worker.name, Worker.id).limit(limit).offset(offset)).all()
    return WorkerLocationsResponse(items=[LocatedWorker(
        worker=describe_worker(worker, now, settings.worker_timeout_seconds),
        distance_km=round(km, 1) if km is not None else None,
        compatible=bool(settings.inference_model_id and settings.inference_model_revision
                        and any((m['model_id'], m['model_revision']) == (
                            settings.inference_model_id, settings.inference_model_revision) for m in (worker.models or [{'model_id': worker.model_id, 'model_revision': worker.model_revision}]))),
    ) for worker, km in rows], total=total, limit=limit, offset=offset, distance_reference=reference)
