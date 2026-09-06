from contextlib import asynccontextmanager
import asyncio
import logging
from pathlib import Path
from fastapi.staticfiles import StaticFiles

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.workers import router
from app.api.jobs import router as jobs_router
from app.api.models import router as models_router
from app.api.tasks import router as tasks_router
from app.api.stats import router as stats_router
from app.api.activity import router as activity_router
from app.api.connection import router as connection_router
from app.api.accounts import router as accounts_router
from app.core.security import authenticate, validate_database_auth_mode
from app.services.recovery import recover_expired
from app.core.config import Settings
from app.api.provider import router as provider_router
from app.api.credits import router as credits_router
from app.db.database import make_engine, make_sessions

logger = logging.getLogger(__name__)


# Kept as an import-compatible alias for existing integrations.
require_token = authenticate


def create_app(settings: Settings | None = None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        engine = make_engine(settings.database_url.get_secret_value()) if settings.database_url else None
        if engine:
            try:
                validate_database_auth_mode(engine, settings)
            except Exception:
                engine.dispose()
                raise
        app.state.sessions = make_sessions(engine) if engine else None
        stop = asyncio.Event()
        def sweep():
            with app.state.sessions() as db:
                recover_expired(db, settings)
        async def recovery_loop():
            while not stop.is_set():
                try:
                    await asyncio.wait_for(stop.wait(), timeout=settings.recovery_interval_seconds)
                except TimeoutError:
                    try:
                        await asyncio.to_thread(sweep)
                    except Exception as exc:
                        logger.error('Recovery failed: %s', type(exc).__name__)
        recovery_task = asyncio.create_task(recovery_loop()) if engine else None
        try:
            yield
        finally:
            stop.set()
            if recovery_task:
                await recovery_task
            if engine:
                engine.dispose()

    app = FastAPI(title='DNhacks Coordinator', version='0.5.0', lifespan=lifespan)
    app.state.settings = settings
    app.state.sessions = None
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                       allow_methods=['GET', 'POST'], allow_headers=['Content-Type', 'Authorization'])

    @app.middleware('http')
    async def private_api_responses(request: Request, call_next):
        response = await call_next(request)
        if settings.auth_mode == 'controlled' and request.url.path.startswith('/api/'):
            # Includes authorization errors and one-time credentials. Do not let
            # browser/proxy caches retain private jobs, results, or account data.
            response.headers['Cache-Control'] = 'no-store'
        return response

    app.include_router(accounts_router, prefix='/api', dependencies=[Depends(require_token)])
    app.include_router(router, prefix='/api', dependencies=[Depends(require_token)])
    app.include_router(connection_router, prefix='/api', dependencies=[Depends(require_token)])
    app.include_router(activity_router, prefix='/api', dependencies=[Depends(require_token)])
    app.include_router(stats_router, prefix='/api', dependencies=[Depends(require_token)])
    app.include_router(tasks_router, prefix='/api', dependencies=[Depends(require_token)])
    app.include_router(models_router, prefix='/api', dependencies=[Depends(require_token)])
    app.include_router(jobs_router, prefix='/api', dependencies=[Depends(require_token)])
    app.include_router(provider_router, prefix='/api', dependencies=[Depends(require_token)])
    app.include_router(credits_router, prefix='/api', dependencies=[Depends(require_token)])

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        # Do not return or log connection strings, query parameters, or database details.
        logger.error('Database request failed: %s', type(exc).__name__)
        return JSONResponse(status_code=503, content={'detail': 'Database unavailable or migrations missing'})

    @app.get('/health', tags=['health'])
    def health():
        return {'status': 'ok'}

    @app.get('/ready', tags=['health'])
    def ready():
        if app.state.sessions is None:
            raise HTTPException(503, 'Database is not configured')
        with app.state.sessions() as db:
            db.execute(text('SELECT 1'))
            db.execute(text('SELECT id, device_id, ram_available_gb, gpu_core_count, gpu_memory_kind, gpu_available_gb, gpu_model_memory_gb FROM coordinator.workers LIMIT 0'))
            db.execute(text('SELECT id, model_id, model_revision, target_worker_id FROM coordinator.jobs LIMIT 0'))
            db.execute(text('SELECT location, models FROM coordinator.workers LIMIT 0'))
            db.execute(text('SELECT id, last_error, model_slot FROM coordinator.tasks LIMIT 0'))
            db.execute(text('SELECT task_id, inference_metrics FROM coordinator.task_results LIMIT 0'))
            db.execute(text('SELECT owner_account_id FROM coordinator.jobs LIMIT 0'))
            db.execute(text('SELECT account_id FROM coordinator.wallets LIMIT 0'))
            db.execute(text('SELECT worker_id FROM coordinator.provider_policies LIMIT 0'))
        return {'status': 'ok', 'database': 'ok'}

    demo_directory = Path(__file__).resolve().parents[2] / 'frontend' / 'demo'
    if demo_directory.is_dir():
        app.mount('/demo', StaticFiles(directory=demo_directory, html=True), name='demo')
    return app


app = create_app()
