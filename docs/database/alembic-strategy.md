# Alembic Strategy

| Field | Value |
|---|---|
| Document Type | Alembic Strategy |
| Authority Domain | Atlas database migration strategy and Alembic adoption direction |
| Implementation Status | Documentation and strategy only; implementation requires separate authorization. |

Task M1-002A does not introduce Alembic. This document defines a revised strategy baseline for a future implementation and separates Codex recommendations from accepted project decisions.

## Confirmed project decision

The project is still at an early stage. The existing database contains test data only, and there is no production database or user data that must be migrated in place. The current Reader and persistence model are also early implementations.

Therefore, future database work may discard existing SQLite test databases and recreate them from the approved schema. Old databases created by `Base.metadata.create_all()` are disposable. The first formal Alembic migration does not need to preserve the current physical schema and should not blindly mirror temporary SQLAlchemy tables as the target schema.

This does **not** remove Reader/API compatibility requirements. Current Reader-facing behavior remains a compatibility constraint until deliberately versioned. Option B is now accepted as the strategic direction: the first formal Atlas database baseline should introduce a minimal `Document` + `SourceFile` foundation while preserving the existing Reader API through an application compatibility layer. This acceptance does not authorize implementation in this documentation-only task.


## Foundation schema design dependency

The implementation-ready design for the first foundation baseline is now documented in `docs/database/foundation-schema-design.md`. Future Alembic work should treat that document as the schema-responsibility source for `Document`, `SourceFile`, and their relationship.

The first formal Alembic baseline should therefore be generated only after the open implementation questions in the foundation design are resolved, especially identifier strategy, `Document` to `SourceFile` cardinality enforcement, source retention behavior, and the initial `Document.status` vocabulary.

This strategy continues to prohibit adding Alembic in documentation-only design tasks. The next implementation task should add migrations only when it is also ready to baseline the approved foundation schema rather than mirror the temporary `Bookshelf` tables.

## Goals

- Establish Alembic as the versioned, reviewable, repeatable database migration mechanism.
- Establish the approved minimal Atlas foundation schema as the first formal baseline.
- Stop treating the temporary schema as the design authority.
- Enable reproducible database creation for development, tests, and future deployments.
- Move schema evolution out of startup `create_all()` and into reviewed migration files.
- Protect current Reader behavior through application compatibility adapters and contract tests rather than by preserving obsolete physical tables.

## Non-goals

Alembic will not, by itself:

- design the complete Document Intelligence Platform schema;
- introduce Canonical Nodes, Facts, Learning, Archive, or future Processing models unless required by the minimal foundation;
- preserve obsolete tables solely for historical compatibility;
- migrate disposable SQLite test data;
- change Reader API behavior;
- change existing `/api/v1` endpoint paths used by `speed-reading-trainer`;
- replace SQLite with another database;
- move blobs to S3/R2;
- normalize all OCR JSON;
- create migrations in this M1-002A documentation-only task.

## Guiding principle: Design → Baseline → Evolve

The earlier migration principle was:

```text
Mirror
  ↓
Migrate
  ↓
Extend
```

That principle assumed the existing database was a production schema that had to be preserved in place. The confirmed project decision makes that assumption obsolete.

The revised principle is:

```text
Design
  ↓
Baseline
  ↓
Evolve
```

| Phase | Meaning | Boundary |
|---|---|---|
| Design | Define the smallest durable Atlas foundation schema needed now. | This does not mean designing the complete future platform in one migration. |
| Baseline | Create the first formal Alembic migration from the approved foundation schema. | The baseline should be intentionally small and human-approved. |
| Evolve | Apply future changes through incremental migrations. | Larger concepts should arrive only when their requirements and compatibility behavior are understood. |

The foundation baseline should remain small enough to review as a durable starting point, not broad enough to pre-commit the entire Document Intelligence Platform.

Database design must follow the approved overall Atlas architecture, implement only concepts required by current product needs, avoid prematurely creating the complete future schema, evolve incrementally through compatibility-safe migrations, and preserve stable external API/protocol contracts rather than temporary internal table layouts.

Use this distinction when reviewing schema scope:

```text
Architecture guides the schema.
Current requirements justify the schema.
Compatibility governs schema evolution.
```

## What must remain compatible

Even though the physical schema may be replaced, the application must preserve the following until a deliberate versioning decision changes them:

| Compatibility surface | Requirement |
|---|---|
| Reader API paths | Keep existing `/api/v1` paths consumed by `speed-reading-trainer`, including upload, list, detail, content, delete, and image retrieval paths. |
| Request/response fields | Preserve Bookshelf-shaped response compatibility where currently required, including fields consumed by the Reader such as `book_id`, title/name fields, file type, status, page count, timestamps, and error fields. |
| Identifiers | Preserve `book_id` behavior for Reader flows and `image_id` behavior for embedded image retrieval. |
| Image marker protocol | Preserve the current `$%$%$%{image_id}$%$%$%` content marker protocol until replaced by an explicitly versioned protocol. |
| Basic reading flows | Preserve current upload, list, detail, content loading, image loading, and deletion flows. |
| TXT/PDF content behavior | Maintain current user-visible behavior for completed TXT and PDF reading, even if the internal persistence representation changes. |

Compatibility should be enforced by application-level adapters and contract tests. It does not require keeping current table names, column names, blob placement, or create-all initialization.

## What may be replaced

The following are implementation details that may be replaced by the foundation design, subject to normal review:

- current table layout;
- `Bookshelf` as an internal persistence root;
- DB blob storage for rendered pages and extracted images;
- `Base.metadata.create_all()` initialization;
- original-file deletion behavior after upload/rendering;
- local OCR coupling and process-local task assumptions;
- disposable SQLite test databases;
- current `OCRTask`, `ContentBlock`, `PdfPage`, `BookImage`, and `MineruResult` physical representations if compatibility behavior is preserved elsewhere.

## Proposed Minimal Foundation Schema

Option B is accepted as the strategic direction, so the proposed first formal foundation should include `Document` and `SourceFile` at minimum. This section is implementation-oriented but still logical: it does not define every future column, constraint, index, or relationship detail.

### Document

| Topic | Proposal | Rationale |
|---|---|---|
| Purpose | Represent the durable readable/work item that current Reader flows call a book. | Atlas needs a stable aggregate that is not tied to the temporary `Bookshelf` table. |
| Aggregate responsibility | Own document-level identity, user-visible reading lifecycle, current title/metadata needed by Reader responses, and the relationship to source files. | This keeps the first baseline focused on current product needs rather than future intelligence objects. |
| Minimum lifecycle needs | Track enough lifecycle/status state to support upload, processing visibility, content availability, failure reporting, and deletion semantics. | Reader flows require status and errors, but a full processing provenance model is not required in the first baseline. |
| External compatibility role | Prefer mapping current `book_id` behavior to `Document` identity or a stable public identifier on `Document`. | This lets the compatibility layer serialize Bookshelf-shaped responses from a durable root. |
| Identifier strategy | Prefer one stable public document identifier that can serve current `book_id`; add a separate compatibility mapping only if implementation proves `Document.id` cannot safely be exposed. | Avoids unnecessary mapping tables while preserving the option for explicit compatibility linkage. |

`Document` should not become a home for Canonical Nodes, Facts, Learning objects, Archive intelligence, or complete processing history in the first baseline. Those concepts require concrete future tasks.

### SourceFile

| Topic | Proposal | Rationale |
|---|---|---|
| Purpose | Represent an immutable uploaded source or source reference associated with a `Document`. | Current upload behavior needs source provenance even if old original files were deleted. |
| Immutable source responsibility | Treat each source record as a historical input reference rather than mutable document state. | This supports future reprocessing and avoids silently changing provenance. |
| Relationship to Document | Start with one `Document` having one primary `SourceFile` for current TXT/PDF uploads, while allowing the model to evolve to multiple source files later if justified. | Current product needs are single-upload flows; multi-source documents should not be designed prematurely. |
| File metadata responsibility | Store only metadata needed now: original filename/title inputs, file type/MIME category, size/checksum if selected during implementation, and enough status to know whether the source is retained or metadata-only. | The first baseline should support reproducibility and auditability without defining every future storage field. |
| Storage-reference responsibility | Record a storage reference when an original is retained; explicitly allow metadata-only records when current behavior deletes originals. | This reconciles durable source provenance with current original-file deletion behavior. |
| Versioning requirement | Do not implement full source-file versioning in the first baseline unless the upload flow creates multiple durable revisions. If a file is replaced later, model it as a new `SourceFile` in a future migration. | Current requirements justify single-source provenance, not a complete versioning system. |

### Relationship and compatibility notes

- The first baseline should model `Document` as the authoritative internal aggregate and `SourceFile` as the immutable source input for that aggregate.
- Current `book_id` should map to a stable `Document` identifier when practical. A compatibility foreign key or mapping field is preferable to an independent mapping table unless multiple external identifier namespaces are immediately required.
- Current Reader responses should remain Bookshelf-shaped through a serializer/adapter that reads from the authoritative model and emits existing response fields.
- Current `Bookshelf`/`PdfPage` data may coexist temporarily during transition, but should not remain an independent permanent source of truth.
- A compatibility foreign key from legacy `Bookshelf` rows to `Document` is likely preferable during transition because it is explicit, testable, and avoids adapter-only hidden mapping. Adapter-only mapping is acceptable only if `Document.id` is exactly the existing `book_id` and no legacy row linkage is needed.

## Deferred Schema Concepts

The following concepts should be added only when justified by a concrete task and compatibility plan:

| Concept | Baseline status | Deferral reason |
|---|---|---|
| Page / `DocumentPage` | Deferred unless technically required for the first baseline. | Current page records are processing details; redesign page identity when page-level product requirements are explicit. |
| Asset | Deferred unless technically required for `image_id` compatibility or storage-reference work in the first baseline. | DB blob replacement and object storage need their own design. |
| ProcessingRun | Deferred; do not introduce a full processing-run design in the baseline. | Current status needs can be represented minimally without full provenance. |
| CanonicalNode | Deferred. | Normalized semantic content requires a concrete document-intelligence task. |
| Fact | Deferred. | Fact extraction is outside current Reader/product needs. |
| Learning objects | Deferred. | Learning features should not shape the first database baseline. |
| Archive intelligence | Deferred. | Archive concepts are future platform scope, not current baseline scope. |

## Candidate approaches

| Option | Description | Benefits | Costs / risks |
|---|---|---|---|
| Option A | Alembic baseline mirrors current schema. | Fastest mechanical migration; lowest immediate code-adapter work; matches current models. | Preserves temporary design as if it were durable; carries obsolete tables/blobs forward; conflicts with the confirmed decision that test DBs are disposable. |
| Option B | Alembic baseline introduces minimal `Document` + `SourceFile` schema while an application adapter preserves current Reader API behavior. | Aligns with Design → Baseline → Evolve; establishes durable core without overdesigning; avoids locking in `Bookshelf` as the persistence root. | Requires explicit design decisions and adapter work; may defer page/image storage cleanup; needs contract tests to prove Reader compatibility. |
| Option C | Alembic baseline includes `Document` + `SourceFile` + `DocumentPage`/`Asset` foundation. | Creates a stronger base for PDF page processing, image markers, and future object storage. | Larger first migration; more decisions up front; higher risk of prematurely encoding processing/storage details. |

## Codex Recommendation — Transition Approach Requires Human Confirmation

Codex recommends the accepted Option B direction with **Approach 1** for transition: add `Document` and `SourceFile` while retaining `Bookshelf`/`PdfPage` as the active legacy persistence path for the shortest practical transition, explicitly linked to `Document`. This recommendation is not accepted until human confirmation.

Open human confirmations required before implementation:

1. Should the transition use Approach 1, with legacy rows linked to `Document`, as the implementation path?
2. Is `Document.id` allowed to be the Reader-facing `book_id`, or should `Document` have a separate stable public identifier?
3. Is a compatibility foreign key on legacy `Bookshelf` sufficient, or is a separate mapping table required?
4. Must `Page` or `Asset` be included because of a technical blocker, or can both remain deferred?
5. Should source records in the first baseline be metadata-only when originals are deleted, or must original-file retention change in the same implementation?


## Compatibility-layer transition approaches

| Approach | Description | Implementation complexity | Data consistency | Rollback | Testability | Transitional duration | Drift risk |
|---|---|---|---|---|---|---|---|
| Approach 1 | Add `Document` and `SourceFile` while retaining `Bookshelf`/`PdfPage` as the active legacy persistence path, linked to `Document`. | Moderate: adds foundation models plus explicit linkage while minimizing immediate router/service rewrites. | Good if `Document` is created once per legacy book and linkage is required; legacy remains operational during transition. | Strong: the app can continue using legacy paths while new foundation rows are validated. | Strong: contract tests can compare legacy Reader behavior while asserting foundation linkage exists. | Short-to-medium; should end when upload ownership moves to `Document`/`SourceFile`. | Manageable if linkage is explicit and there is one declared source of truth at each step. |
| Approach 2 | Make `Document` the active persistence root immediately and serialize old Bookshelf-shaped API responses from it. | Higher: requires moving upload/list/detail/content ownership immediately. | Strong after cutover because there is one authoritative root. | Weaker for the first PR because rollback touches active flows. | Strong if contract tests are already comprehensive; risky if not. | Short if successful. | Low after cutover, but initial migration risk is higher. |
| Approach 3 | Temporarily dual-write independent legacy and new models. | High: every write path must maintain two independent models. | Weak unless strict consistency checks are built immediately. | Mixed: either model may be incomplete or divergent. | Harder: tests must validate two stores and reconciliation behavior. | Should be extremely short if used at all. | High risk of permanent dual-model drift. |

Codex recommends Approach 1 because it avoids independent permanent dual-write, keeps the current Reader contract stable, provides explicit compatibility linkage, and allows `Document`/`SourceFile` to become authoritative incrementally. Approach 3 should be avoided unless a temporary implementation spike proves it is unavoidable. If temporary dual-write is ever used, it must have an exact duration of one migration/cutover PR, `Document` as the declared target source of truth, automated consistency checks between legacy and foundation rows, and removal criteria requiring all Reader contract tests to pass from the authoritative model.

## Testing implications

Future implementation may:

- recreate test databases from Alembic migrations;
- delete old SQLite test databases instead of upgrading them in place;
- replace `Base.metadata.create_all()` in integration tests gradually;
- retain `create_all()` temporarily for isolated unit tests only if explicitly justified;
- validate the Reader API through contract tests rather than legacy schema assertions;
- assert compatibility for endpoint paths, response shapes, `book_id`, `image_id`, marker protocol, and upload/list/detail/content/image flows.

Tests should avoid asserting that legacy tables exist unless a compatibility adapter intentionally keeps them.

## Rollback philosophy

Rollback should be conservative. Because current databases are disposable test data, early rollback can prefer database recreation from a known migration revision rather than in-place downgrade of historical schemas.

- The first baseline should be clear enough to recreate from scratch.
- Additive migrations may support downgrades that drop newly added empty tables, but data-loss implications must be explicit.
- Destructive downgrades should not be treated as safe production rollback without an accepted backup/restore procedure.
- Once real production/user data exists, this strategy must be revisited before destructive changes are allowed.

## Risks

| Risk area | Evaluation |
|---|---|
| Over-baselining | Including pages, assets, processing runs, nodes, or learning concepts too early could freeze immature design. |
| Under-baselining | A baseline with only `Document` and `SourceFile` may require adapter shims or quick follow-up migrations for page/image workflows. |
| Reader compatibility | Physical schema replacement could break Reader behavior unless contract tests cover current flows. |
| Startup `create_all()` | Keeping it after Alembic may hide migration failures; removing or gating it is a future production-code decision. |
| Blob storage | Deferring `Asset` may leave DB blob behavior temporarily unresolved. |
| Source retention | Current original-file deletion behavior conflicts with durable source-file semantics and needs a decision. |
| Future PostgreSQL | The foundation schema should avoid SQLite-only assumptions even if SQLite remains the current development database. |


## Implementation sequencing recommendation

A small-PR sequence should keep design, migration mechanics, compatibility, and ownership changes reviewable:

1. Approve the foundation schema design in `docs/database/foundation-schema-design.md` and resolve its open implementation questions.
2. Define SQLAlchemy `Document` and `SourceFile` models according to the approved design.
3. Introduce Alembic after model responsibilities are accepted.
4. Generate the first Alembic baseline migration for the approved `Document` + `SourceFile` schema.
5. Switch durable database initialization away from long-term reliance on startup `Base.metadata.create_all()`.
6. Add a Reader compatibility adapter/serializer that emits current Bookshelf-shaped responses from the foundation model.
7. Move upload/list/detail/content ownership to `Document`/`SourceFile` behind Reader contract tests.
8. Retire legacy persistence incrementally after replacements for content, page/image behavior, and deletion semantics are verified.

The foundation design recommends a one `Document` to many `SourceFile` relationship with one initial primary source for current Reader uploads, but this requires human confirmation before implementation. Do not introduce Page/Asset redesign, full `ProcessingRun`, Canonical Nodes, Facts, Learning objects, or Archive intelligence in the foundation PR unless a concrete technical blocker requires it.

## Roadmap impact recommendation

M1 should likely be adjusted so foundation data-model design precedes Alembic implementation. Possible task split:

| Potential task | Purpose |
|---|---|
| M1-002B Define Foundation Data Model | Human-review and approve the minimal `Document`/`SourceFile` foundation and decide whether `DocumentPage`, `Asset`, compatibility mappings, or `ProcessingRun` belong in the first baseline. |
| M1-002C Introduce Alembic Foundation Baseline | Add Alembic and create the first formal migration from the approved foundation schema. |

If the foundation design is confirmed to be very small, these could be combined into one implementation task. This document does not update task numbering or mark that roadmap change accepted.

## Open questions

- What exact columns belong in the minimal `Document` foundation?
- What exact columns belong in `SourceFile`, especially for checksum, size, original filename, MIME type, storage URI, and deletion/retention state?
- Should `book_id` be the document primary key, a public identifier column, or a row in a compatibility mapping table?
- Should `image_id` be backed by an `Asset` table in the first baseline or by a later adapter?
- How long may `Base.metadata.create_all()` remain in isolated unit tests?
- Which Reader contract tests are required before switching from legacy persistence to the foundation schema?
- What is the accepted policy for deleting or recreating existing local/Hugging Face SQLite test databases?

## Final decision summary

| Decision | Status | Notes |
|---|---|---|
| Option B direction | Accepted | First formal Atlas baseline should introduce minimal `Document` + `SourceFile` foundation while preserving Reader API behavior through a compatibility layer. |
| Existing test DB recreation | Accepted | Existing SQLite test data and old `create_all()` databases may be deleted and recreated. |
| Physical legacy schema compatibility | Not required | Current table layouts are implementation evidence, not long-term contracts. |
| Reader API compatibility | Required | Existing `/api/v1` paths, Bookshelf-shaped responses where consumed, `book_id`, `image_id`, marker protocol, and current reading flows remain compatibility constraints. |
| Minimal baseline scope | Document + SourceFile | Do not define every future column or platform concept in the first baseline. |
| Transitional coexistence approach | Pending human confirmation | Codex recommends Approach 1: linked legacy path during transition, not independent permanent dual-write. |
| Exact columns and constraints | Pending implementation design | This document remains logical and implementation-ready, not a final DDL specification. |
| Page/Asset inclusion in baseline | Deferred unless required | Add only if a concrete technical blocker proves they are required for the first baseline. |

## Accepted architecture philosophy for future database work

Atlas is a Document Intelligence Platform whose mission is to transform real-world information into structured, verifiable, reusable knowledge. The long-term aggregate root is `Document`, not `Bookshelf`, and `Document` represents a durable real-world information object rather than a PDF or OCR result container.

`SourceFile` represents immutable source evidence. A `Document` may eventually have one or many source files, but the first formal baseline should still implement only the minimum needed for current validated requirements.

The conceptual future pipeline is:

```text
Document
  ↓
SourceFile
  ↓
ProcessingRun
  ↓
Observation
  ↓
Canonical Knowledge
  ↓
Applications
```

This pipeline is architecture direction only. It does not authorize adding `ProcessingRun`, `Observation`, Canonical Knowledge, Facts, Learning objects, or Archive intelligence tables to the first Alembic baseline.

Future database work must continue to apply the accepted principle:

```text
Architecture guides the schema.
Current requirements justify the schema.
Compatibility governs schema evolution.
```

The temporary physical schema is not a long-term contract. Reader API compatibility is a long-term contract until deliberately versioned. Compatibility should be protected through application behavior and contract tests, not by treating temporary internal table names as permanent architecture.

## M1-002B status before Alembic baseline

M1-002B intentionally implements the `Document` and `SourceFile` SQLAlchemy
models before introducing Alembic. This keeps the first formal migration in
M1-002C aligned to the accepted foundation schema instead of preserving the old
Bookshelf-centered test schema.

The current disposable create_all-managed schema now contains `documents` and
`source_files`; there is no separately mapped `bookshelf` table. Reader-facing
book responses are compatibility serialization over `Document`. Existing
page/image/content/MinerU tables keep `book_id` column names temporarily but
reference `documents.id`.

M1-002C remains required and should create the version-controlled Alembic
baseline for the implemented foundation, then replace or gate startup/test
`Base.metadata.create_all()` behavior. No migration files are introduced in
M1-002B.

## M1-002C implementation update

Alembic is now installed in the runtime/lightweight dependency set because the deployed application applies migrations at startup and Required Backend CI validates migration behavior. The baseline revision is `0001_foundation_schema`.

Production schema management now runs `alembic upgrade head` through `app.database.init_db()`. `Base.metadata.create_all()` is no longer used by normal application startup; any remaining uses are isolated test-only shortcuts documented in `docs/database/migration-operations.md`.

See `docs/database/migration-operations.md` for commands, startup behavior, rollback assumptions, and SQLite foreign-key notes.
