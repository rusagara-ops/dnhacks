"""Read-only connection check: python -m app.db.check."""
from sqlalchemy import text
from app.core.config import Settings
from app.db.database import make_engine


def main():
    settings = Settings()
    if not settings.database_url:
        raise SystemExit('Set DATABASE_URL in backend/.env first.')
    engine = make_engine(settings.database_url.get_secret_value())
    try:
        with engine.connect() as connection:
            assert connection.scalar(text('SELECT 1')) == 1
        print('Database connection OK (SELECT 1).')
    except Exception:
        raise SystemExit('Database connection failed. Check DATABASE_URL, SSL and network access.') from None
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
