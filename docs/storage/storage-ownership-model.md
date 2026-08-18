# Storage Ownership Model

| Field | Value |
|---|---|
| Document Type | Ownership Model |
| Authority Domain | storage and persistence ownership distinctions |
| Applies To | Source, Artifact, Knowledge, Presentation, Business, Storage, Processing, Application, Document, SourceFile, storage paths, database blobs, processing outputs, application caches |

## Objective

Define who gives meaning to an object, who stores it, who produces it, and who consumes it. This model prevents storage paths, database blobs, processing outputs, and application caches from becoming accidental business owners of Atlas evidence. The follow-up [Storage Adapter Design](storage-adapter-design.md) proposes the smallest infrastructure boundary for object mechanics while preserving these ownership separations.

## Orthogonal dimensions

Atlas uses two top-level dimensions for object classification and responsibility, with retention policy, deletion authority, and rebuildability modeled separately when lifecycle decisions are made.

Dimension 1 — Information layer:

- Source
- Artifact
- Knowledge
- Presentation

Dimension 2 — Responsibility/ownership:

- Business
- Storage
- Processing
- Application

Information type does not determine ownership. Ownership does not determine retention by itself. Retention Policy, Deletion Authority, and Rebuildability are separate policy dimensions that must not be inferred only from information layer or owner.

For example, an original PDF can be classified as **Source**, governed by **Business** policy through `Document`/`SourceFile`, stored mechanically by **Storage**, produced by ingestion, and consumed by **Processing** for OCR. Those roles are related but not interchangeable.

## Business ownership

Business ownership means responsibility for meaning, identity, lifecycle, and policy.

Examples:

- `Document` owns business identity.
- `SourceFile` associates evidence with a `Document`.
- A future Fact belongs to a knowledge/business context.

Clarifications:

- `Document` is not a stored file object.
- `Document` should not know provider-specific paths.
- Business objects should refer to storage objects through stable references.
- Business policy decides whether evidence should be retained, deleted, archived, or placed under hold; Storage executes mechanics after policy approval.

## Storage ownership

Storage ownership means responsibility for:

- object bytes;
- retrieval;
- write/read/delete mechanics;
- object identity/key;
- provider interaction;
- integrity metadata where appropriate;
- durability mechanics.

Storage does not decide:

- whether an object is a book or contract;
- legal meaning;
- application semantics;
- knowledge truth;
- Reader behavior.

Storage stores and retrieves objects according to stable references and authorized commands. It should not embed Atlas business rules in local path names or provider-specific cleanup code.

## Processing ownership

Processing ownership means responsibility for:

- producing artifacts;
- consuming Source objects;
- recording provenance;
- declaring regeneration capability;
- cleanup recommendations;
- associating outputs with a future `ProcessingRun`.

`ProcessingRun` remains a future concept and is not implemented by this document. Processing can recommend that a page render, OCR JSON payload, layout result, or diagnostic file is temporary or regenerable, but Business policy decides retention authority and Storage performs byte-level actions.

## Application ownership

Application ownership means responsibility for:

- user experience;
- presentation;
- temporary views;
- application caches;
- learning objects where application-specific;
- user interaction state.

Application should not become the authoritative owner of original evidence. Reader, learning, archive, and future presentation features may consume retained sources, artifacts, or knowledge, but they should not directly delete business evidence or make provider-specific storage paths part of product semantics.

## Ownership matrix

| Object | Information layer | Business owner | Storage owner | Producer | Consumer | Retention authority | Current state | Future direction |
|---|---|---|---|---|---|---|---|---|
| Original PDF | Source | `SourceFile` associated with `Document` | Current local `uploads/` temporarily; future Storage | Upload ingestion | OCR/rendering, audit, reprocessing | Business policy, with user/admin choice as approved | Temporarily written then deleted; `SourceFile` metadata remains | Retain by default once policy and implementation are approved |
| SourceFile metadata | Business/provenance metadata, not bytes | `SourceFile` / `Document` | Database metadata | Upload ingestion | Business, processing, audit | Business policy | Stored in `source_files`; `retained=0` for current uploads | Continue as provenance record; reference retained source objects later |
| Rendered page PNG | Artifact / Presentation support | Current `PdfPage`; future processing/page artifact owner | Database blob today; future Storage if externalized | PDF rendering | OCR, cropping, Reader page endpoint | Business policy informed by Processing regeneration | Stored in `pdf_pages.page_image_data` while book remains | Treat as derived artifact; retain only when needed for compatibility, cost, or regeneration speed |
| OCR JSON | Artifact / Observation | Current `PdfPage`; future Processing provenance | Database text today | OCR processing | MinerU-Popo, debugging, future canonicalization | Business/Processing policy | Stored in `pdf_pages.ocr_raw_json` | Move conceptually toward processing observation when justified |
| Canonical content | Knowledge | Future Knowledge/Business context | Storage/database depending representation | Canonicalization process | Reader, archive, learning, search | Business/Knowledge policy | Not implemented as a separate canonical object | Define later through narrow canonicalization task |
| Fact/evidence link | Knowledge | Future Knowledge/Business context | Database/storage as needed | Extraction/validation | Archive, QA, analytics | Business/Knowledge policy | Future concept only | Must remain traceable to Source evidence |
| Flashcard | Knowledge / Presentation | Future Learning/Application, possibly Knowledge when accepted | Storage/database as needed | Learning generation or user authoring | Learning application | Application/Business policy depending user edits | Future concept only | Separate generated drafts from user-reviewed durable learning records |
| Mind map | Knowledge / Presentation | Future Learning/Application | Storage/database as needed | Learning generation or user authoring | Learning application | Application/Business policy | Future concept only | Treat generated cache differently from user-edited map |
| Reader page cache | Presentation | Application | Storage/cache layer | Reader/application rendering | Reader UI/API | Application policy constrained by Business evidence rules | Not named as a separate object; Reader uses processed TXT, MinerU JSON, images | Never authoritative; regenerate from knowledge/artifacts |
| Search index | Knowledge / Index Artifact | Future Retrieval/Application; Knowledge for semantics | Storage/index provider | Indexing process | Search/archive applications | Business/Knowledge policy for source data; retrieval policy for index | Future concept only | Rebuildable index derived from canonical/evidence-backed content |

## Source of truth

Source-of-truth principles:

- `Document` is authoritative for business identity.
- Source object is authoritative for original evidence.
- `SourceFile` is authoritative for source provenance and association with a `Document`, but it is not itself the bytes.
- Processing output is not automatically canonical truth.
- Canonical knowledge is authoritative only after accepted canonicalization.
- Presentation caches are never authoritative.
- Indexes and embeddings support retrieval; they are not evidence.

This section does not define canonicalization implementation.

## Provider independence

Business meaning must not depend on local, S3, R2, or other provider path format. Provider keys should not leak into public APIs. Storage references should remain replaceable so Atlas can migrate from local files to object storage without changing `Document` identity or Reader-facing contracts.

After adapter introduction, application code should not open provider paths directly. It should request objects through storage references and approved storage operations. This is design direction only and does not define an adapter interface.

## Failure and deletion ownership

Retention, deletion, purge, artifact cleanup, failed-upload cleanup, and orphan cleanup require both policy authority and execution responsibility.

| Action | Policy authority | Execution responsibility | Notes |
|---|---|---|---|
| Retention | Business policy, possibly user/admin/compliance | Storage persists objects; Processing declares regeneration needs | Retention policy, deletion authority, and rebuildability must be explicit. |
| Source deletion | Business policy with authorized user/admin action | Storage deletes bytes; database/business layer updates provenance state | Must define downstream effects first. |
| Purge | Business/compliance authority | Storage and database execution | Purge should be distinct from ordinary delete if approved later. |
| Artifact cleanup | Business/Application policy informed by Processing | Storage and owning service | Artifacts can be cleaned only if their rebuildability and regeneration prerequisites are confirmed. |
| Failed-upload cleanup | Ingestion/business workflow | Storage and database transaction/cleanup code | Must avoid orphan metadata and missing evidence surprises. |
| Orphan cleanup | Business/storage governance | Storage maintenance job or operator process | Requires reliable ownership and reference checks before deletion. |

The decision maker and executor should not be conflated. For example, Storage may execute a delete, but it should not decide that a legal record is safe to purge.

## Recommendations

### Codex recommendations — Human Confirmation Required

| Recommendation | Rationale | Status |
|---|---|---|
| Source-of-truth hierarchy: `Document` for identity, Source object for original evidence, accepted canonical knowledge for reusable understanding, presentation caches never authoritative. | Prevents derived artifacts and caches from becoming accidental truth. | Pending human confirmation |
| Retention authority belongs to Business policy, informed by Processing and Application needs. | Storage mechanics should not silently decide evidence lifecycle. | Pending human confirmation |
| Object deletion authority should require explicit Business approval for Sources and may be delegated for regenerable artifacts/caches. | Balances evidence integrity with cleanup practicality. | Pending human confirmation |
| Provider-reference boundaries should keep provider keys out of public APIs and out of business meaning. | Enables local-to-object-storage migration while preserving contracts. | Pending human confirmation |
| Existing DB blobs should be transitionally owned by current tables for compatibility, while future design classifies them as artifacts/presentation support before migration. | Avoids premature blob migration before ownership and retention decisions are accepted. | Pending human confirmation |

## Risks

- Two owners for the same object can create conflicting lifecycle decisions.
- No declared source of truth can make OCR output, caches, or indexes look authoritative.
- Storage provider leakage can turn local paths or object keys into public contracts.
- Business rules hidden in path cleanup can delete evidence without policy review.
- Derived artifact treated as evidence can mask the loss of originals.
- Application deleting business evidence can break auditability and trust.
- Orphaned objects can accumulate cost or expose stale data.
- Inaccessible evidence after provider change can break reprocessing, audit, and Reader compatibility.

## Open questions

1. What exact stable storage-reference concept should business records use after adapter design?
2. Which role approves deletion in personal, enterprise, and regulated deployments?
3. Should `SourceFile.retained=0` mean never retained, deleted by policy, failed retention, or external-reference-only in future state?
4. Who owns migration of existing `pdf_pages.page_image_data` and `book_images.image_data` blobs if object storage is introduced?
5. Should artifact cleanup be synchronous with document deletion or handled by later garbage collection?
6. What audit record is required when an application requests deletion of evidence?
7. When future learning objects are user-edited, do they become Business-owned knowledge or Application-owned records?

## Decision table

| Decision | Status | Notes |
|---|---|---|
| Information type does not determine ownership. | Accepted | Reuses accepted M1-003B principle. |
| Ownership does not determine retention by itself. | Accepted | Retention still requires policy. |
| Information layer remains Source / Artifact / Knowledge / Presentation. | Accepted | Existing Atlas Digital Object Taxonomy. |
| Retention policy is a separate dimension. | Accepted | Retention duration/lifecycle is not inferred only from information layer or owner. |
| Deletion authority is a separate dimension. | Accepted | Who may authorize deletion is distinct from who executes deletion. |
| Rebuildability is a separate dimension. | Accepted | Processing can inform rebuildability; rebuildability does not determine retention by itself. |
| Mixed three-class v1 vocabulary. | Rejected | Atlas will not collapse policy into labels such as User-managed Source, Regenerable Artifact, or Temporary Diagnostic. |
| `Document` is authoritative for business identity. | Accepted | Existing Atlas architecture principle. |
| Source object is authoritative for original evidence. | Accepted | Existing Atlas architecture principle. |
| Storage owns mechanics, not meaning. | Accepted | Storage stores objects; Business gives meaning. |
| Exact source retention policy. | Pending human confirmation | Option B remains a recommendation only in the source retention strategy. |
| Metadata-only `SourceFile` as a normal state. | Pending human confirmation | Current behavior is transitional; future allowed states require human decision. |
| Source-of-truth hierarchy recommendation. | Pending human confirmation | Codex recommendation only. |
| Business policy as retention authority. | Pending human confirmation | Codex recommendation only. |
| Provider-reference boundary details. | Pending human confirmation | Adapter design deferred. |
| Transitional ownership of current DB blobs. | Proposed | Intended as migration guidance, not implementation. |
| Exact database fields/enums. | Deferred | No schema representation is defined here. |
| Exact retention periods. | Deferred | Deployment and policy decisions remain future work. |
| Enterprise/compliance policy implementation. | Deferred | Legal hold, compliance schedules, and enterprise policy engines are not implemented here. |
| Provider interface, schema, migration, cleanup jobs. | Not in scope | This document is policy/design only. |

## M1-003D delete boundary

Storage owns object bytes and mechanics; book deletion is a business action. M1-003D uses the smallest compatibility-preserving delete behavior: `DELETE /api/v1/books/{book_id}` explicitly deletes retained source bytes through the injected Storage provider as part of deleting book metadata, because the current public API semantically deletes the whole book. Before each retained-source delete, the service reads bytes for best-effort restoration and tracks each source deleted during the attempt. If a later retained-source delete fails before metadata deletion, the service restores already-deleted sources, rolls back, and returns the existing failure behavior. If the metadata delete commit fails after source deletion, the service also attempts to restore just-deleted retained sources and logs restoration failures. Generic filesystem cleanup still only handles compatibility paths such as processed TXT and never parses `SourceFile.storage_reference` as a local path.

No source-deletion API, user/admin/compliance policy model, lifecycle worker, or orphan cleanup job is introduced.

### M1-003D retained-state and deployment caveat

`retained = 1` records that Atlas successfully stored original source bytes through the configured Storage provider and saved a storage reference; it does not continuously prove the referenced object still exists. If infrastructure loss, manual deletion, or provider failure removes bytes, `retained = 1` plus a non-null `storage_reference` becomes a broken-reference / infrastructure-consistency condition. Runtime existence must be verified through Storage. The current Hugging Face Space has no Persistent Storage configured and is intentionally disposable; production must use persistent mounted storage or a durable provider before accepting real user data.
