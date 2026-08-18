# Repository Conventions

## Naming Examples

For task `M1-003`:

| Item | Example |
| --- | --- |
| Task | `M1-003` |
| Issue | `M1-003 Introduce Storage Adapter` |
| PR | `M1-003 Introduce Storage Adapter` |
| Branch | `codex/m1-003-storage-adapter` |
| Squash Commit | `M1-003 Introduce Storage Adapter` |

## Branch Naming

Use short, descriptive branch names that identify the task or change type.
Recommended examples include:

- `codex/m1-002-alembic`
- `codex/m1-003-storage-adapter`
- `codex/m2-001-heading-markers`
- `bugfix/...`
- `docs/<area>/<document>.md`

Prefer one feature branch per production change. Documentation-only work should
normally also use a branch and Pull Request.

## Recommended PR Template

```markdown
## Milestone

## Problem

## Background

## Scope

## Non-goals

## Acceptance Criteria

## Validation

## Compatibility

## Rollback
```

## Documentation Conventions

- Markdown files inside repositories are the source of truth.
- Do not delete obsolete ADRs.
- ADR statuses are: Proposed, Accepted, Superseded, Deprecated, Rejected.
- Pending decisions should be labeled **TODO — Pending Decision**.
- Codex recommendations should be labeled **Codex Recommendation** and kept separate from accepted decisions.

## Repository Responsibilities

Follow ADR-001.

### `paddle-vl-api`

- OCR Compute Service
- durable-business-stateless
- asynchronous OCR execution
- temporary job state
- temporary artifacts
- no durable business ownership

### `pdf-ocr-service`

- durable business system of record
- Document Core
- Source Files
- Page Records
- Observations
- Canonical Content
- Archive Facts
- Learning Objects

### `speed-reading-trainer`

- presentation layer
- reading experience
- focus mode
- browser interaction
- learning interface
