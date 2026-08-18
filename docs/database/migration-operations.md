# Migration Operations

| Field | Value |
|---|---|
| Document Type | Migration Operations |
| Authority Domain | Alembic-based schema migration operations and revision application |
| Applies To | Migration inspection, upgrade, downgrade, startup boundaries, tests, and operational warnings. |

M1-002C introduces Alembic as the authoritative schema evolution mechanism for `pdf-ocr-service`.

## Installed structure

- `alembic.ini` contains project-level Alembic configuration.
- `alembic/env.py` imports `app.models.Base.metadata` for autogenerate and reads the database URL from the same application configuration source (`app.database.DATABASE_URL`) unless a test/CLI config explicitly overrides it.
- `alembic/versions/0001_foundation_schema.py` is the first reviewed foundation baseline.

## Baseline revision

Revision: `0001_foundation_schema` — foundation schema.

The baseline creates:

1. `documents`
2. `ocr_tasks`
3. `book_images`
4. `content_blocks`
5. `mineru_results`
6. `pdf_pages`
7. `source_files`

`book_images`, `content_blocks`, `mineru_results`, `pdf_pages`, and `source_files` reference `documents` with `ON DELETE CASCADE` to match current ORM metadata. `book_images.image_id` and `mineru_results.book_id` retain their current unique constraints. No explicit indexes beyond primary keys and unique constraints are defined by the current ORM metadata.

The baseline intentionally excludes `bookshelf` and `bookshelves`. It also does not add future platform tables such as `assets`, `processing_runs`, `observations`, `canonical_nodes`, `facts`, `learning_objects`, `categories`, `collections`, `domains`, or archive-intelligence tables.

## Schema authority and startup behavior

Alembic is now the production schema authority. `app.database.init_db()` runs `alembic upgrade head` during FastAPI startup. If migration fails, startup fails closed instead of silently falling back to `Base.metadata.create_all()`.

For the current Hugging Face Spaces entrypoint, `app.py` runs `uvicorn` against `app.main:app`; FastAPI startup then applies migrations before serving requests. `render.yaml` is a separate Render-oriented configuration that still declares `gunicorn app:app` and should be reviewed before any Render deployment is treated as authoritative. A later production-hardening task should consider moving migrations to an explicit release/start command before multiple replicas or real production data exist.

`Base.metadata.create_all()` is retained only in isolated test helpers and the standalone in-memory `DatabaseService("sqlite:///:memory:")` path. These uses are temporary speed optimizations for lightweight tests and are not production schema authority.

## Common commands

Use these commands from the repository root:

```bash
alembic upgrade head
alembic current
alembic history
alembic downgrade base
```

To point Alembic at a disposable local SQLite database:

```bash
DATABASE_URL=sqlite:///./ocr_tasks.db alembic upgrade head
```

To recreate the current disposable local database during M1 only:

```bash
rm -f ocr_tasks.db
DATABASE_URL=sqlite:///./ocr_tasks.db alembic upgrade head
```

Warning: do not use destructive deletion or `alembic downgrade base` against future production data. The baseline downgrade drops all baseline tables and is acceptable only because current databases are disposable.

## Test strategy

Migration tests create temporary SQLite databases and run Alembic upgrade/downgrade directly. Existing Reader/API contract tests keep their fast metadata-created fixtures for now so Required Backend CI remains lightweight and does not import OCR/model dependencies.

Required Backend CI runs:

```bash
alembic heads
alembic history
python -m pytest -q tests/test_migrations.py
```

## SQLite foreign keys

Current engine configuration does not enable `PRAGMA foreign_keys=ON`. The schema declares `ON DELETE CASCADE`, and ORM relationships use delete-orphan cascades, but SQLite database-level cascade enforcement is not guaranteed unless foreign keys are enabled per connection. Follow-up recommendation: enable and test SQLite foreign-key enforcement in a dedicated PR before relying on database-level cascades.

## Future production-data warning

Before real production/user data exists, disposable database recreation and destructive baseline downgrade are acceptable. Once real data exists, future migrations must include explicit backup, restore, data migration, and rollback policy instead of table-dropping assumptions.
