"""Database configuration and Alembic-backed schema initialization."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)


def normalize_database_url(value: str) -> str:
    """Normalize provider PostgreSQL URLs onto the explicit Psycopg 3 dialect.

    SQLAlchemy 2.x still maps a bare ``postgresql://`` URL to psycopg2. Atlas
    installs Psycopg 3, so provider-style PostgreSQL URLs are normalized before
    either the runtime engine or Alembic consumes them. Explicit driver URLs are
    preserved unchanged.
    """
    normalized = str(value).strip()
    if normalized.startswith("postgres://"):
        return "postgresql+psycopg://" + normalized[len("postgres://") :]
    if normalized.startswith("postgresql://"):
        return "postgresql+psycopg://" + normalized[len("postgresql://") :]
    return normalized


# Default remains SQLite for local development/tests. Production may supply a
# PostgreSQL URL; provider-style URLs are normalized to the installed Psycopg 3
# SQLAlchemy dialect before engine/Alembic configuration.
DATABASE_URL = normalize_database_url(
    os.getenv("DATABASE_URL", "sqlite:///./ocr_tasks.db")
)

# SQLite needs check_same_thread disabled for FastAPI request/background usage.
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
    )
else:
    # PoolPrePing prevents a stale pooled connection from surviving a database
    # restart/network idle timeout. Pool sizing intentionally remains SQLAlchemy's
    # bounded default until the Production PostgreSQL provider is selected.
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """Yield a request-scoped database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def alembic_config() -> Config:
    """Build an Alembic Config that uses the same DATABASE_URL as the app."""
    project_root = Path(__file__).resolve().parents[1]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    # Alembic Config uses ConfigParser interpolation. Escape literal percent
    # characters from URL-encoded credentials while preserving the effective URL.
    config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))
    return config


def init_db() -> None:
    """Apply reviewed Alembic migrations during application startup.

    Alembic is the production schema authority. Startup fails closed if the
    database cannot be upgraded to the repository head revision.
    """
    try:
        command.upgrade(alembic_config(), "head")
    except Exception:
        logger.exception("Database schema migration to Alembic head failed")
        raise
    logger.info("Database schema upgraded to Alembic head")


__all__ = [
    "DATABASE_URL",
    "SessionLocal",
    "alembic_config",
    "engine",
    "get_db",
    "init_db",
    "normalize_database_url",
]
