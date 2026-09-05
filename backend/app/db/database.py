from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from fastapi import HTTPException, Request


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str):
    url = make_url(database_url)
    if url.drivername in ('postgres', 'postgresql'):
        url = url.set(drivername='postgresql+psycopg')
    if url.drivername != 'postgresql+psycopg':
        raise ValueError('DATABASE_URL must use PostgreSQL with psycopg')
    return create_engine(
        url, pool_pre_ping=True, pool_size=5, max_overflow=0,
        pool_timeout=5, connect_args={'connect_timeout': 5},
        hide_parameters=True,
    )


def make_sessions(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_db(request: Request):
    factory = request.app.state.sessions
    if factory is None:
        raise HTTPException(503, 'Database is not configured')
    with factory() as db:
        yield db
