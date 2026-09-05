from alembic import context
from sqlalchemy import text
from app.core.config import Settings
from app.db.database import Base, make_engine
from app.models import Worker  # noqa: F401

settings = Settings()
if not settings.database_url:
    raise RuntimeError('Set DATABASE_URL before running migrations')

if context.is_offline_mode():
    context.configure(url=settings.database_url.get_secret_value(), target_metadata=Base.metadata, literal_binds=True, include_schemas=True, version_table_schema='coordinator')
    with context.begin_transaction():
        context.execute('CREATE SCHEMA IF NOT EXISTS coordinator')
        context.run_migrations()
else:
    engine = make_engine(settings.database_url.get_secret_value())
    with engine.connect() as connection:
        connection.execute(text('CREATE SCHEMA IF NOT EXISTS coordinator'))
        connection.commit()
        context.configure(connection=connection, target_metadata=Base.metadata, include_schemas=True, version_table_schema='coordinator')
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
