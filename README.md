---
title: PDF OCR Service
emoji: 📄
colorFrom: blue
colorTo: purple
sdk: docker
app_file: app.py
pinned: false
---

# Atlas — Document Intelligence Platform

Atlas is a Document Intelligence Platform that transforms real-world
information into structured, verifiable, reusable knowledge. It helps you read
faster, learn deeper, remember more effectively, and build an intelligent
personal knowledge base that understands your documents, reasons across them,
and traces every answer back to the original evidence.

This repository contains the FastAPI backend for PDF ingestion, transitional
Reader compatibility output generation, and bookshelf management. Current PDF
processing still uses the local implementation path; `paddle-vl-api` integration
is the target M2 architecture, not the active production pipeline.

## Mission

Transform real-world information into structured, verifiable, reusable
knowledge.

## Engineering Motto

Think long-term.
Build incrementally.
Verify continuously.

## Atlas Way

Atlas is developed through small, verifiable iterations. Long-term architecture
guides implementation, while current requirements determine scope. Stable public
contracts are preserved while the internal implementation evolves. Architecture
guides the schema. Current requirements justify the schema. Compatibility governs
schema evolution.

For detailed engineering workflow, architecture decisions, roadmap, and
development practices, see the Engineering Documentation section below. Atlas
does not duplicate documentation already maintained elsewhere.

## Project identity

This repository is part of **Atlas**, one **Document Intelligence Platform**.
Atlas contains peer applications, **Smart Reading OS** and **Smart Archive**,
which share one Document Intelligence Core. Within Atlas, this service owns the
backend document-processing and bookshelf APIs described by
[ADR-001 Service Boundaries](docs/architecture/adr/ADR-001-service-boundaries.md).

## Engineering foundation status

The M1 foundation milestone is in progress under the canonical
[Atlas Roadmap v2](docs/roadmap/roadmap.md). Completed foundation work includes
project governance, repository documentation, Required Backend CI, Alembic,
`Document`/`SourceFile` foundation, Storage Adapter, Local provider, and original
Source retention mechanics.

M1 remains incomplete until the documentation/design closeout task **Storage
Persistence Architecture and M1-to-M2 Processing Handoff** is completed and
verified. M2 must not be treated as current until M1 closes.

Original M1-004 PDF retention scope was absorbed by completed M1 Storage work.
The old M1-005 label is realigned because prior M1 work already introduced the
compatible `Document` and `SourceFile` foundation.

## Features

- Upload PDF or TXT files → processed compatibility output persisted to bookshelf
- Current transitional PDF path uses local PyMuPDF rendering, `PdfPage` image
  BLOBs, local PaddleOCR-VL, MinerU-Popo, and `MinerUResult` Reader dependency
- Target M2 PDF path retrieves retained Sources with `Storage.get()`, calls
  `paddle-vl-api`, normalizes with MinerU-Popo, and emits structured processing
  output
- Generated book content is serialized as Reader Content Stream Protocol v2, defined in [`docs/contracts/reader-content-stream-v2.md`](docs/contracts/reader-content-stream-v2.md)
- Reader streams support paragraph lines, heading markers (`$#$#1` through `$#$#6`), and unchanged image marker lines (`$%$%$%{image_id}$%$%$%`)
- Bookshelf CRUD: list, detail, content, delete
- Image serving: `GET /api/v1/images/{image_id}` returns stored image assets referenced by Reader stream markers
- Health check: `GET /api/v1/health`
- Auto-generated API docs at `/docs`
- Chinese + English mixed document content support through the current local OCR path

## PDF Processing Pipeline

When a PDF is uploaded via `POST /api/v1/upload`, `pdf-ocr-service` currently
uses a transitional local processing path. Do not read this README as claiming
that the target M2 `paddle-vl-api` pipeline is already implemented.

Current transitional implementation:

```text
uploaded PDF
    ↓
local PyMuPDF page rendering
    ↓
PdfPage image BLOBs
    ↓
local PaddleOCR-VL
    ↓
OCR JSON
    ↓
MinerU-Popo
    ↓
MinerUResult
    ↓
Reader compatibility output
```

Target M2 architecture:

```text
retained SourceFile
    ↓
Storage.get()
    ↓
paddle-vl-api
    ↓
processing result / document tree
    ↓
MinerU-Popo
    ↓
normalized structured processing output
```

Stream Text / Reader Content Stream is a generated presentation and
compatibility format for Speed Reading. It is not canonical data and must not
become the sole persistent content representation.

### Reader Content Stream Protocol v2

The Reader stream is plain text. Logical lines are delimited by `\n`, and the
protocol supports three content forms:

| Form | Serialization | Notes |
|------|---------------|-------|
| Paragraph | `Paragraph text\n` | Internal OCR/provider line wraps are removed before serialization. |
| Heading | `$#$#<level>Heading text\n` | Levels `1` through `6` are valid heading levels. |
| Image | `$%$%$%{image_id}$%$%$%\n` | The existing image marker format is unchanged and occupies an entire logical line. |

Example stream:

```text
$#$#1Chapter One
$#$#2Introduction
This is a normalized paragraph with internal line wraps removed.
$%$%$%image_123$%$%$%
This paragraph follows the image.
```

Version 1 paragraph/image-only streams remain valid v2 streams. Readers that do
not understand heading markers may display them literally, so Reader support for
heading markers should be deployed before backend heading generation.

### Provider boundary

`paddle-vl-api` is the target M2 OCR/layout compute boundary. The current code
still uses the transitional local path. After M2 ingestion, `pdf-ocr-service`
should not depend on temporary provider artifacts; durable references must point
to `pdf-ocr-service` owned records, files, or storage objects.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/upload` | Upload PDF or TXT; returns book metadata |
| `GET`  | `/api/v1/books` | List all books |
| `GET`  | `/api/v1/books/{book_id}` | Book detail |
| `GET`  | `/api/v1/books/{book_id}/content` | Book TXT content |
| `DELETE` | `/api/v1/books/{book_id}` | Delete book and files |
| `GET`  | `/api/v1/images/{image_id}` | Retrieve stored PNG image |
| `GET`  | `/api/v1/health` | Health check |
| `POST` | `/api/pdf/upload-and-process` | Background PDF processing (also writes TXT) |

### Reader stream format

Book content returned by `GET /api/v1/books/{book_id}/content` is serialized
according to [Reader Content Stream Protocol v2](docs/contracts/reader-content-stream-v2.md).

#### Image marker format

Image references in a book's Reader stream are represented as complete logical
lines:

```text
$%$%$%{image_id}$%$%$%
```

where `{image_id}` is the value used by `GET /api/v1/images/{image_id}`.
Example: `$%$%$%image_123$%$%$%`.

#### Heading marker format

Headings are represented with explicit v2 heading markers at the beginning of a
logical line:

```text
$#$#1Chapter title
$#$#2Section title
```

Heading levels `1` through `6` are reserved. Unknown levels are rendered as
normal text by v2 Readers.

#### Paragraph newline policy

Paragraphs are serialized as plain text lines terminated by `\n`:

- internal OCR/provider line wraps inside one paragraph are removed before serialization
- each paragraph ends with `\n`
- paragraph content has no required marker prefix
- old paragraph-only streams remain valid v2 streams

## Architecture

- [Document Intelligence Platform Architecture Proposal](docs/architecture/document-intelligence-platform.md)

## Engineering Documentation

- [Product Strategy](docs/product/product-strategy.md)
- [Architecture](docs/architecture/document-intelligence-platform.md)
- [Current State Review](docs/architecture/current-state-review.md)
- [Initial Modification Plan](docs/planning/initial-modification-plan.md)
- [ADR](docs/architecture/adr/README.md)
- [Roadmap](docs/roadmap/roadmap.md)
- [M1 Foundation Dashboard](docs/milestones/M1.md)
- [M1-000 Review](docs/reviews/M1-000-review.md)
- [Engineering Foundation Release Note](docs/releases/2026-07-11-engineering-foundation.md)
- [Engineering Principles](docs/engineering/engineering-principles.md)
- [Development Workflow](docs/engineering/development-workflow.md)
- [Repository Conventions](docs/engineering/repository-conventions.md)
- [Project Governance](docs/project/project-governance.md)
- [Glossary](docs/project/project-glossary.md)

## Project structure

```text
pdf-ocr-service/
├── app/
│   ├── main.py                        # FastAPI app, router registration
│   ├── config.py                      # Settings (upload_dir, output_dir, …)
│   ├── database.py                    # SQLAlchemy engine + session factory
│   ├── models.py                      # Bookshelf, ContentBlock, BookImage ORM models
│   ├── schemas.py                     # Pydantic request/response schemas
│   ├── ocr_service.py                 # PaddleOCR wrapper (file path + numpy array)
│   ├── pdf_service.py                 # PDF ingestion → Reader stream orchestration
│   ├── enhanced_pdf_service.py        # Legacy local layout service (not current upload path)
│   ├── image_preprocessing.py         # Legacy image preprocessing helpers
│   ├── image_service.py               # DB-backed image persistence
│   ├── book_service.py                # Bookshelf CRUD helper
│   ├── routers/
│   │   ├── ocr.py                     # POST /api/v1/upload (PDF + TXT)
│   │   ├── books.py                   # /api/v1/books/* endpoints
│   │   ├── images.py                  # /api/v1/images/* endpoints
│   │   ├── health.py                  # /api/v1/health
│   ├── api/
│   │   └── pdf_endpoints.py           # /api/pdf/upload-and-process (background)
│   └── services/
│       ├── pdf_processing_service.py  # Block-level processing helper
│       └── database_service.py        # Standalone DB service (background tasks)
├── tests/
│   ├── test_api.py                    # API light tests (no GPU)
│   ├── test_phase2_light.py           # DB service unit tests
│   ├── test_pdf_pipeline.py           # Legacy/local pipeline and stream-format tests
│   └── test_heavy.py                  # Real OCR tests (marked slow)
├── requirements.txt
├── Dockerfile
└── README.md
```

## Run locally

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 7860 --reload
```

Service runs on `http://localhost:7860`.  API docs at `http://localhost:7860/docs`.

## Run tests

```bash
# Fast tests only (no GPU required)
python -m pytest tests/test_api.py tests/test_phase2_light.py tests/test_pdf_pipeline.py -q

# All tests including heavy OCR (requires PaddleOCR + GPU/CPU models)
python -m pytest tests/ -q
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./ocr_tasks.db` | SQLAlchemy database URL |
| `UPLOAD_DIR` | `uploads` | Directory for temporary uploaded files |
| `OUTPUT_DIR` | `output` | Directory for generated TXT files |
| `LAYOUT_ENGINE` | `auto` | Legacy local layout setting retained only for legacy/manual local pipeline paths |
| `LAYOUT_DEBUG_ENABLED` | `false` | Legacy local layout diagnostic artifact toggle |
| `LAYOUT_DEBUG_DIR` | `output/layout_debug` | Legacy local layout debug artifact directory |
| `LAYOUT_MIN_TEXT_BLOCK_SIZE` | `8` | Legacy local layout text-block size threshold |
| `LAYOUT_MIN_VISUAL_BLOCK_SIZE` | `12` | Legacy local layout image/table size threshold |
| `LAYOUT_MIN_CONFIDENCE` | `0.0` | Legacy local layout confidence threshold |

### Database migrations

Alembic is the schema authority. On application startup the service runs `alembic upgrade head` against `DATABASE_URL` and fails closed if migration fails. Developer commands and disposable SQLite recreation steps are documented in [Migration Operations](docs/database/migration-operations.md).

### Local source retention storage

Original uploaded TXT/PDF source bytes are retained through the Storage Adapter v1 Local provider. Configure the root with `STORAGE_ROOT` (default: `storage/objects`). The stored `SourceFile.storage_reference` is an opaque `src_<uuidhex>` logical reference, not a filesystem path and not part of public Reader API responses. The current Hugging Face Space is a disposable test deployment with no Persistent Storage configured, so the default Local provider stores objects on ephemeral container storage and may lose them along with SQLite data during rebuilds. This is acceptable only for the current test stage; production deployment must use persistent mounted storage or a durable provider before accepting real user data.
