"""Alembic environment for the Atlas PDF OCR service."""
from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import (
    Column,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    engine_from_config,
    inspect,
    pool,
)

from alembic import context
from app.database import DATABASE_URL, normalize_database_url
from app.models import Base
import app.models_v2  # noqa: F401 - register structured-content v2 tables
import app.models_v2_selection  # noqa: F401 - register v2 selection table
import app.processing.ingestion_dispatch_model  # noqa: F401 - register dispatch table

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Alembic autogenerate must use the production SQLAlchemy model metadata.
target_metadata = Base.metadata

# Alembic 1.13.x creates its version_num column as VARCHAR(32). Atlas already
# has reviewed revision identifiers longer than 32 characters. SQLite does not
# enforce VARCHAR length, but PostgreSQL does, so the fresh PostgreSQL online
# migration path needs a wider physical version column before Alembic writes the
# first long revision identifier. Existing SQLite databases are never touched by
# this compatibility bridge.
_ALEMBIC_VERSION_TABLE = "alembic_version"
_ALEMBIC_VERSION_LENGTH = 255


def _database_url() -> str:
    """Return the normalized migration database URL.

    Alembic CLI and tests may override sqlalchemy.url on the Config object.
    Otherwise, the environment uses app.database.DATABASE_URL so deployment and
    migrations share one source of database configuration and PostgreSQL driver
    selection.
    """
    configured_url = config.get_main_option("sqlalchemy.url")
    x_args = context.get_x_argument(as_dictionary=True)
    if x_args.get("database_url"):
        return normalize_database_url(x_args["database_url"])
    if configured_url and configured_url != "sqlite:///./ocr_tasks.db":
        return normalize_database_url(configured_url)
    return DATABASE_URL


def _ensure_postgresql_alembic_version_capacity(connection) -> None:
    """Create or fail-closed validate the PostgreSQL Alembic version table.

    This only prepares Alembic's own bookkeeping table. It does not create or
    mutate application tables and is intentionally a no-op for SQLite.
    """
    if connection.dialect.name != "postgresql":
        return

    inspector = inspect(connection)
    if inspector.has_table(_ALEMBIC_VERSION_TABLE):
        version_column = next(
            (
                column
                for column in inspector.get_columns(_ALEMBIC_VERSION_TABLE)
                if column["name"] == "version_num"
            ),
            None,
        )
        if version_column is None:
            raise RuntimeError("PostgreSQL Alembic version table has no version_num column")
        length = getattr(version_column["type"], "length", None)
        if length is not None and length < _ALEMBIC_VERSION_LENGTH:
            raise RuntimeError(
                "PostgreSQL Alembic version_num column is too narrow for Atlas revision identifiers"
            )
        return

    metadata = MetaData()
    version_table = Table(
        _ALEMBIC_VERSION_TABLE,
        metadata,
        Column("version_num", String(_ALEMBIC_VERSION_LENGTH), nullable=False),
        PrimaryKeyConstraint("version_num", name="alembic_version_pkc"),
    )
    version_table.create(connection)


def run_migrations_offline() -> None:
    """Run migrations in offline mode."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in online mode."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # Commit only the PostgreSQL bookkeeping-table compatibility bridge
        # before Alembic opens its own transactional-DDL migration boundary.
        with connection.begin():
            _ensure_postgresql_alembic_version_capacity(connection)

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
