# M1-003 Storage Foundation Closeout Review

## Status

Completed

- Review date: 2026-07-13.
- Merged implementation PR title: `Implement Local Storage Adapter and Original Source Retention`.
- Merged implementation PR number: #52, visible in repository Git history.
- Required Backend CI result for merged M1-003D: remaining human merge-gate confirmation; detailed CI run URL is not present in repository context.
- This review is a milestone closeout for M1-003. It is not a software release.

## Objective

M1-003 established a provider-independent Storage boundary and retained original uploaded TXT/PDF sources without changing Reader behavior.

M1-003 was intentionally completed through separate review, policy, design, implementation, verification, and closeout steps so that architectural decisions, retention policy, implementation mechanics, and verification evidence remained reviewable independently.

## Completed task sequence

- **M1-003A — Review Current Storage Architecture and Define Atlas Digital Object Taxonomy**: reviewed existing storage locations, ownership gaps, and terminology. Result: completed current-state review and Digital Object Taxonomy.
- **M1-003B — Define Source Retention Strategy and Storage Ownership**: separated retained source policy from storage mechanics and clarified ownership. Result: completed Source Retention Strategy and Storage Ownership Model.
- **M1-003C — Design Storage Adapter Architecture**: defined the provider-independent Storage Adapter v1 boundary, operations, references, failure handling, and deferred scope. Result: completed accepted design for Local provider implementation.
- **M1-003D — Implement Local Storage Adapter and Original Source Retention**: implemented the Local provider, upload integration, retained source metadata, delete integration, compensation, and tests. Result: merged implementation PR #52.
- **M1-003E — Close Storage Foundation**: recorded completed work, accepted decisions, limitations, risks, technical debt, and readiness for the next approved M1 task. Result: this closeout review.

## Deliverables completed

### Architecture and policy

- Current Storage Review.
- Digital Object Taxonomy.
- Source Retention Strategy.
- Storage Ownership Model.
- Storage Adapter Design.

### Production implementation

- Provider-independent Storage interface.
- Local filesystem provider.
- Opaque logical references.
- `put`, `get`, `delete`, and `exists` operations.
- Size and SHA-256 integrity metadata.
- Create-only/checksum-idempotent writes.
- Source retention for original TXT/PDF uploads.
- `SourceFile.storage_reference` population.
- `SourceFile.retained` semantics for successful provider-backed retained storage.
- Settings-backed factory and FastAPI dependency integration.
- Explicit retained-source deletion through the book business path.
- Transaction compensation for upload and delete failure cases.

### Testing and CI

- Local provider contract tests.
- TXT/PDF source-retention integration tests.
- Failure-compensation tests.
- Multi-source delete compensation tests.
- API compatibility protection.
- Required Backend CI inclusion for storage contract and source-retention tests.

## Accepted architecture decisions

1. Storage stores objects and bytes; Business owns meaning and policy.
2. Document is a business aggregate, not a Digital Object.
3. SourceFile associates source evidence with Document.
4. Stable references are opaque provider-independent logical IDs.
5. Business/application callers must not parse provider details from references.
6. Local provider is the first implementation.
7. v1 operations are `put`, `get`, `delete`, and `exists`.
8. v1 is bytes-first and synchronous, with future additive stream/async design deferred.
9. Original retained Source writes are create-only.
10. Same-reference/same-checksum retry is idempotent.
11. Same-reference/different-checksum conflict fails.
12. Storage calculates actual byte size and SHA-256.
13. Original TXT/PDF source retention is the accepted M1 implementation scope.
14. Processed TXT, DB BLOBs, OCR JSON, and MinerU JSON remain transitional and deferred.
15. Upload transaction direction is: object write → integrity verification → metadata commit.
16. Failed metadata commit triggers best-effort object cleanup.
17. Book deletion currently uses compatibility-preserving Option A: delete the retained original Sources and book metadata through an explicit business-service path.
18. Multi-source partial deletion and DB-commit failure use best-effort restoration.
19. `retained=1` records successful storage through the configured provider and a stored reference; it does not continuously prove object existence or infrastructure durability.
20. Actual current existence must be checked through `Storage.exists()`/`get()`.
21. Durability depends on deployment/provider infrastructure.

## Information and ownership model

The accepted model keeps information, policy, responsibility, and implementation orthogonal.

Information Layer:

- Source.
- Artifact.
- Knowledge.
- Presentation.

Policy/responsibility dimensions:

- Retention Policy.
- Deletion Authority.
- Rebuildability.
- Business.
- Storage.
- Processing.
- Application.

Principle:

```text
Information answers what an object is.
Policy answers what should happen to it.
Responsibility answers who decides.
Implementation answers how it works.
```

This is architecture language, not a database enum system.

## Implemented module structure

The merged `app/storage/` structure is:

- `app/storage/__init__.py`: package marker for the Storage boundary.
- `app/storage/base.py`: provider-independent synchronous `StorageProvider` protocol.
- `app/storage/dependencies.py`: FastAPI dependency that constructs a configured provider.
- `app/storage/errors.py`: provider-independent error types for invalid references, integrity mismatches, not-found conditions, conflicts, provider unavailability, and read/write/delete failures.
- `app/storage/factory.py`: settings-backed provider factory.
- `app/storage/local.py`: root-confined Local filesystem provider.
- `app/storage/models.py`: provider-independent `StorageReference` and `PutResult` value objects.

The implemented logical reference format is:

```text
src_<32 lowercase hexadecimal characters>
```

The exact format is an implementation detail behind the opaque reference contract. Business/application code must not parse provider details from it.

## Local provider behavior

- Uses the configured `STORAGE_ROOT` through settings; the default is `storage/objects`.
- Resolves and creates a root directory, then rejects symlink roots.
- Stores generated object keys under sharded provider-internal paths.
- Does not include the original filename in the object path.
- Publishes writes with an atomic create-only hard link from a completed temporary file to the final object path.
- Treats same-reference/same-checksum writes as idempotent retries.
- Fails same-reference/different-checksum writes with an object conflict.
- Validates expected size and expected SHA-256 when supplied and returns actual byte size plus SHA-256.
- Treats missing `get`/`delete` targets as missing instead of silently succeeding.
- Fails closed for invalid references, traversal attempts, root escape, unsafe symlink root/destination/object cases, and path confinement failures.
- Does not expose absolute filesystem paths through the public Storage contract.

## Upload and processing behavior

TXT behavior:

- Source bytes are retained through Storage before final source metadata is committed.
- `SourceFile` metadata is committed with retained status, byte size, checksum, and storage reference.
- Temporary processing path remains separate from retained source storage.
- Processed TXT remains in `output/` for existing Reader behavior.
- Reader content remains unchanged.
- Processing failure leaves the retained Source available when metadata has committed.

PDF behavior:

- Source bytes are retained through Storage before final source metadata is committed.
- A temporary PDF remains available for rendering/processing needs.
- Rendered pages remain DB BLOBs.
- Page numbering remains 1-based.
- Background OCR behavior remains unchanged.
- Temporary PDF is cleaned.
- Processing failure leaves the retained Source available when metadata has committed.

## Delete behavior and compensation

- `DELETE /api/v1/books/{book_id}` remains compatible.
- The business/service layer authorizes and coordinates deletion.
- Storage performs object deletion mechanics.
- Retained source references are never treated as filesystem paths.
- Multiple retained Sources are supported.
- Partial multi-source delete failure triggers restoration of already-deleted Sources.
- DB delete commit failure triggers best-effort restoration.
- Restoration failure is logged.
- Behavior remains best-effort and is not a distributed transaction.

Current book delete permanently deletes retained original evidence.

Broader user/admin/compliance policy remains deferred.

No separate source-deletion API or UI was added.

## Deployment posture

The human-confirmed current Hugging Face posture is:

- test-only deployment;
- no production/user data;
- no Hugging Face Persistent Storage configured;
- local filesystem and SQLite data are ephemeral;
- data may be lost on container rebuild;
- this is accepted only for disposable testing.

M1-003 establishes Storage and retention semantics, not production durability.

Before real user/production data is accepted, deployment must use:

- persistent mounted filesystem storage; or
- a future durable object-storage provider.

The current Hugging Face storage must not be described as production durable.

## Verification evidence

The workflow used for M1-003D was evidence-driven:

- implementation Summary reviewed;
- independent verification performed;
- defects found and corrected;
- Required Backend CI included the merged storage tests; final run result remains a human merge-gate confirmation;
- human review.

Important defects discovered during verification:

- `os.replace` overwrite race;
- root symlink risk;
- delete commit evidence-loss risk;
- multi-source partial-delete compensation risk;
- Hugging Face durability wording/semantic ambiguity.

Final corrections:

- atomic create-only publication;
- root/symlink hardening;
- restore on DB delete failure;
- restore on partial multi-source delete failure;
- explicit ephemeral-deployment documentation;
- precise retained semantics.

Principle:

```text
Summary is a claim. Evidence earns approval.
```

## Test coverage

Storage contract tests cover:

- `put`, `get`, `delete`, and `exists`;
- invalid references;
- traversal;
- root isolation;
- symlink behavior;
- integrity mismatch;
- idempotent retry;
- different-checksum conflict;
- create-only publication race.

Source-retention integration tests cover:

- TXT retention;
- PDF retention;
- public API no-reference leakage;
- temporary-file cleanup;
- write failure;
- metadata commit failure;
- processing failure retention;
- book deletion;
- DB-delete commit restoration;
- multi-source partial-delete restoration.

Existing compatibility suites cover:

- API;
- Foundation architecture;
- Alembic migrations;
- Reader behavior.

## What went well

- Review happened before design.
- Policy was separated from mechanics.
- Implementation scope stayed small.
- Verification was evidence-driven instead of summary-driven.
- Architecture regression tests protected the boundary.
- Reader/API compatibility was preserved.
- Defects were caught before merge.

## Lessons learned

- Local storage does not imply persistent deployment storage.
- Retained state is not continuous existence proof.
- Filesystem atomicity must be checked under concurrent races.
- Deletion compensation is harder than upload compensation.
- One-to-many SourceFile architecture must be tested even when current uploads create one source.
- Business deletion policy and Storage delete mechanics must remain separate.
- Verification reports must distinguish static evidence, runtime evidence, and human deployment facts.

## Remaining technical debt

Deferred work remains intentional and should not be treated as M1-003 failure:

- production-persistent provider/mount;
- cloud provider support;
- streams/large-object handling;
- async provider design;
- stat/head metadata operation;
- processed TXT migration;
- `PdfPage`/`BookImage` BLOB migration;
- OCR/MinerU JSON migration;
- durable orphan reconciliation;
- staging/finalization transaction state;
- backup/restore;
- multi-instance/provider concurrency;
- formal user/admin/compliance deletion authority;
- archive/purge/soft-delete/legal-hold semantics;
- continuous retained-object consistency checking;
- provider migration tooling.

## Risks carried forward

- Current Hugging Face data loss on rebuild.
- Best-effort compensation can still fail.
- Direct infrastructure loss can create broken references.
- Current Local provider is single-node.
- No distributed transaction.
- No automatic orphan cleanup.
- Current Reader processed TXT still uses direct filesystem paths.

## Compatibility preserved

- Reader endpoint paths unchanged.
- Response schemas unchanged.
- `book_id`/`image_id` unchanged.
- Marker protocol unchanged.
- TXT completed behavior unchanged.
- PDF processing behavior unchanged.
- 1-based page numbering unchanged.
- DB BLOB/OCR/MinerU behavior unchanged.
- No public storage reference leakage.

## Non-goals confirmed

M1-003 did not add:

- cloud provider;
- Asset;
- ProcessingRun;
- public Document API;
- source-deletion API/UI;
- policy/permission model;
- lifecycle worker;
- orphan cleanup job;
- streaming/async provider;
- DB BLOB/JSON migration;
- processed TXT migration.

## Definition of done

M1-003 met these conditions:

- architecture reviewed;
- policies documented;
- design confirmed;
- Local provider implemented;
- original TXT/PDF retained through Storage;
- failure compensation tested;
- Reader compatibility preserved;
- Required Backend CI coverage included storage/source-retention tests; final merged-run result requires human confirmation;
- human verification completed;
- implementation merged.

## Closure statement

M1-003 Storage Foundation is formally complete.

Atlas now has a provider-independent Storage boundary, a tested Local provider, original TXT/PDF source-retention mechanics, and explicit separation between information meaning, retention policy, responsibility, and storage mechanics.

Current Hugging Face storage remains intentionally ephemeral for testing. Production durability remains a deployment/provider requirement before real user data is accepted.

## M1-004 scope resolution

Human roadmap decision: **M1-004 Original PDF Retention is completed because its original approved scope was absorbed by M1-003D**.

M1-003D already implemented original uploaded PDF retention through Storage, original uploaded TXT retention through Storage, `SourceFile.storage_reference` population, `SourceFile.retained` semantics, checksum and byte-size integrity, retention across processing failures, Reader compatibility, and retained-source deletion/compensation. Therefore M1-004 is not a separate implementation PR and must not remain marked as the next/current task.

This does not redefine M1-004 as production-durable Hugging Face storage, Persistent Storage configuration, S3/R2 support, backup/restore, legal retention, or cloud-provider implementation. Those remain separate deferred production-hardening concerns.

## M1 progress audit

Top-level M1 task status after this closeout:

- M1-000 Project Engineering Foundation — Completed.
- M1-001 Close Lightweight Required CI Baseline — Completed.
- M1-002 Introduce Alembic Migration Framework — Completed through Document/SourceFile foundation work, the Alembic baseline, migration-backed startup, migration documentation, and migration CI coverage.
- M1-003 Storage Adapter / Storage Foundation — Completed.
- M1-004 Original PDF Retention — Completed; original scope absorbed by M1-003D.
- M1-005 Document / SourceFile Compatibility Layer — Incomplete pending human roadmap clarification.

Progress: 5 / 6. M1 remains incomplete because M1-005 is not complete. The M1-003D Required Backend CI result remains a human merge-gate confirmation unless the human reviewer supplies the green run evidence.

## Next approved task

Exact M1-005 title: **M1-005 Document / SourceFile Compatibility Layer**.

Existing approved roadmap text provides the title but does not provide a detailed standalone scope beyond the M1-level Document/SourceFile compatibility objective. Prior M1-002 work already introduced the `Document` and `SourceFile` SQLAlchemy foundation, Reader-compatible serialization, and compatibility tests, so M1-005 may be overlapping or stale.

Next task pending human roadmap clarification. Do not redefine or start M1-005 in this PR.
