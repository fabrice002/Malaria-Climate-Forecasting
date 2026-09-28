"""
Database engine, session factory, and declarative base.

Uses the URL from settings. For PostgreSQL/PostGIS in production, set
MEWS_DATABASE_URL=postgresql+psycopg://user:pass@host:5432/malaria
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

# SQLite needs a special flag for multithreaded FastAPI access.
connect_args = (
    {"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {}
)

engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a database session and closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables. Called on application startup for the skeleton.

    In production this is replaced by Alembic migrations.
    """
    import app.models.orm  # noqa: F401  (register models on the metadata)
    Base.metadata.create_all(bind=engine)
