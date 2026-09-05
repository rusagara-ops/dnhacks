from contextlib import asynccontextmanager
import asyncio
import logging
import secrets
from pathlib import Path
from fastapi.staticfiles import StaticFiles

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.workers import router
from app.api.jobs import router as jobs_router
from app.api.tasks import router as tasks_router
from app.api.stats import router as stats_router
from app.services.recovery import recover_expired
from app.core.config import Settings
from app.db.database import make_engine, make_sessions

logger = logging.getLogger(__name__)


bearer = HTTPBearer(auto_error=False)


def require_token(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    expected = request.app.state.settings.api_token
    if expected and not secrets.compare_digest(
        credentials.credentials if credentials else '', expected.get_secret_value()
    ):
        raise HTTPException(401, 'Invalid API token', headers={'WWW-Authenticate': 'Bearer'})


def create_app(settings: Settings | None = None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        engine = make_engine(settings.database_url.get_secret_value()) if settings.database_url else None
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
    app.include_router(router, prefix='/api', dependencies=[Depends(require_token)])
    app.include_router(stats_router, prefix='/api', dependencies=[Depends(require_token)])
    app.include_router(tasks_router, prefix='/api', dependencies=[Depends(require_token)])
    app.include_router(jobs_router, prefix='/api', dependencies=[Depends(require_token)])

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
            db.execute(text('SELECT id, ram_available_gb, gpu_core_count, gpu_memory_kind, gpu_available_gb, gpu_model_memory_gb FROM coordinator.workers LIMIT 0'))
            db.execute(text('SELECT id, model_id, model_revision FROM coordinator.jobs LIMIT 0'))
            db.execute(text('SELECT id, last_error FROM coordinator.tasks LIMIT 0'))
            db.execute(text('SELECT task_id FROM coordinator.task_results LIMIT 0'))
        return {'status': 'ok', 'database': 'ok'}

    app.mount('/demo', StaticFiles(directory=Path(__file__).resolve().parents[1] / 'demo', html=True), name='demo')
    return app


app = create_app()
