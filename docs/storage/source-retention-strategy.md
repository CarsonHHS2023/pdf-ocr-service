# Source Retention Strategy

| Field | Value |
|---|---|
| Document Type | Storage Strategy |
| Approval Status | Proposed |
| Authority Domain | source retention strategy and retention decision framework |
| Applies To | original source evidence, selected derived objects, uploaded PDF, uploaded TXT, original image, original audio, original video, email source, webpage capture, ZIP/package, future external-source snapshot |

## Status

Proposed strategy pending human confirmation.

This document separates accepted architecture principles from recommended source-retention policy. Unless a decision is explicitly marked **Accepted**, it is proposed guidance for human review.

## Objective

Source retention must be defined before Storage Adapter design because storage mechanics should serve evidence semantics, not create them accidentally. A provider interface can decide how bytes are written, read, and deleted only after Atlas decides which objects are original evidence, which objects are derived and regenerable, which objects must remain traceable, and which layer has authority to approve deletion.

Without this policy, a future adapter could preserve today's critical gap by making metadata-only `SourceFile` records look normal, or it could over-retain every derived artifact without distinguishing evidence integrity from cache convenience.

## Scope

This strategy covers original source evidence and selected derived objects. The follow-up [Storage Adapter Design](storage-adapter-design.md) proposes the infrastructure boundary that would execute storage mechanics after retention and ownership decisions are confirmed.

It does not define:

- provider interfaces;
- S3/R2 configuration;
- object keys;
- database schema;
- lifecycle jobs;
- garbage collection implementation;
- encryption implementation;
- backup implementation.

## Source definition

A **Source** is original or authoritative evidence received or captured by Atlas. It is the closest available representation of the real-world information object before Atlas processing changes it.

Examples:

- uploaded PDF;
- uploaded TXT;
- original image;
- original audio;
- original video;
- email source;
- webpage capture;
- ZIP/package;
- future external-source snapshot.

A Source may be a file, stream capture, or durable external reference. Durable external references are appropriate only when Atlas cannot legally or technically retain bytes, such as when a provider forbids copying, a user grants reference-only access, or the source is too dynamic to capture completely. Reference-only Sources still require provenance metadata and explicit policy because the referenced evidence can disappear or change outside Atlas.

## Retention principles

### Accepted principles

The following principles are accepted architecture direction for Atlas:

1. Source represents original evidence.
2. `SourceFile` is not merely upload metadata. It represents the provenance and evidence associated with a `Document`.
3. Original evidence should be durable unless a deliberate policy permits deletion.
4. Derived artifacts should be reproducible whenever practical.
5. Knowledge should remain traceable to original evidence.
6. Storage stores objects. Business gives them meaning.
7. `Document` is a business aggregate, not a Digital Object.
8. Information classification and ownership are orthogonal dimensions.
9. Architecture guides storage. Current requirements justify storage. Compatibility governs storage evolution.
10. Do not design tomorrow's storage objects today. Do not sacrifice tomorrow's architecture for today's convenience.

### Proposed policy principles pending human confirmation

| Principle | Evaluation | Status |
|---|---|---|
| Retain original evidence by default. | Strongly supports auditability, reprocessing, rollback, and evidence-backed knowledge. Increases storage cost. | Proposed |
| Do not rely on derived artifacts as the only surviving evidence. | Prevents rendered pages, OCR JSON, or Markdown from becoming accidental substitutes for originals. | Proposed |
| Deletion must be deliberate and auditable. | Required for trust, enterprise review, and future compliance posture. Exact audit mechanism is deferred. | Proposed |
| Rebuildable artifacts do not automatically require long-term retention. | Keeps storage growth controlled and distinguishes evidence from cache. | Proposed |
| Evidence required for traceability must outlive derived knowledge. | Prevents facts, summaries, or knowledge graph edges from surviving without verifiable support. Exact retention periods are deferred. | Proposed |
| Retention policy may vary by deployment, legal requirements, user choice, and document type. | Supports personal, enterprise, and regulated deployments without hard-coding one policy. | Proposed |
| Storage cost alone should not silently override evidence integrity. | Cost is a valid input, but not an implicit deletion authority. | Proposed |
| A source deletion policy must define downstream effects. | Deleting evidence may affect artifacts, facts, links, indexes, and Reader state. | Proposed |

## Retention and lifecycle dimensions

Atlas will not use one mixed classification vocabulary for retention. Retention and storage policy are described through separate conceptual dimensions so that information type, lifecycle rule, deletion authority, and rebuildability do not become confused.

These dimensions are conceptual only. They are not database enums, fields, tables, migrations, API values, adapter methods, or provider key schemes.

### Dimension 1 — Information Layer

Answers: **What kind of information object is this?**

Accepted values:

- Source;
- Artifact;
- Knowledge;
- Presentation.

Information Layer classifies the object. It does not, by itself, decide retention, deletion authority, or storage mechanics.

### Dimension 2 — Retention Policy

Answers: **How long should it be retained, and under what lifecycle rule?**

Conceptual values:

| Retention policy | Meaning | Notes |
|---|---|---|
| Retained by default | Kept unless an explicit authorized policy or user/admin action deletes it. | Recommended direction for original Source evidence, pending human confirmation. |
| Temporary | Kept only for processing, troubleshooting, cache, or another short-lived operational purpose. | Exact duration and cleanup mechanism are deferred. |
| Policy-controlled | Retained according to deployment, document type, tenant, legal/compliance rule, or administrative policy. | Exact policy engine and retention periods are deferred. |
| External-reference-only | Atlas stores provenance and reference metadata, but not source bytes. | Used only when bytes cannot legally or technically be retained, or after a deliberate reference-only decision. |

Clarifications:

- These are conceptual policy categories only.
- They are not database enums.
- Exact retention periods remain deployment/policy decisions.
- **Permanent** is not a general v1 category. Enterprise and regulated systems usually apply explicit retention schedules, legal holds, or compliance policies rather than literal permanence.

### Dimension 3 — Deletion Authority

Answers: **Who may authorize deletion?**

Conceptual examples:

| Deletion authority | Meaning |
|---|---|
| User-controlled | An authorized user may request or confirm deletion. |
| Administrator-controlled | A deployment, tenant, or system administrator controls deletion. |
| Policy/compliance-controlled | Retention schedule, legal hold, or compliance process controls deletion. |
| System-controlled | The system may delete according to approved operational rules, usually for temporary objects or caches. |

Deletion authority is independent of retention duration. For example, a retained-by-default source may be user-controlled in a personal deployment, administrator-controlled in an enterprise deployment, or policy/compliance-controlled under legal hold.

### Dimension 4 — Rebuildability

Answers: **Can this object be recreated after deletion?**

Conceptual values:

| Rebuildability | Meaning |
|---|---|
| Non-rebuildable | Cannot be recreated by Atlas if deleted. Original Source evidence usually belongs here. |
| Deterministically rebuildable | Can be recreated exactly from retained inputs and deterministic processing. |
| Approximately rebuildable | Can be recreated only approximately because model, dependency, configuration, prompt, or runtime versions may change. |
| Partially rebuildable | Some parts can be recreated, but accepted edits, user input, validation, or external state cannot be fully recovered. |
| Not applicable | Rebuildability is not meaningful for the object or purpose. |

OCR/model artifacts are often only approximately rebuildable because model, dependency, configuration, prompt, and runtime versions may change. Original Source evidence is generally non-rebuildable. Rebuildability does not itself determine retention policy.

### Purpose labels

Terms such as **Diagnostic**, **Cache**, **Evidence**, **Processing output**, and **Application output** describe object purpose or role. They are not retention-policy classes.

### Codex recommendation — Human Confirmation Required

For v1 policy work, describe every relevant object using the separate dimensions above:

1. Information Layer.
2. Retention Policy.
3. Deletion Authority.
4. Rebuildability.

Do not collapse them into mixed labels such as User-managed Source, Regenerable Artifact, or Temporary Diagnostic. Exact database representation, exact retention durations, enterprise/legal policy implementation, and source-retention enforcement remain deferred.

## Object-by-object policy analysis

Future objects listed below are conceptual only unless current behavior is explicitly described.

| Object | Information layer | Retention policy recommendation | Deletion authority | Rebuildability | Evidence value | Current behavior | Future direction | Human decision status |
|---|---|---|---|---|---|---|---|---|
| Original PDF | Source | Retained by default | User/policy controlled, pending confirmation | Non-rebuildable | Very high | Uploaded bytes are written to `uploads/`, rendered, then deleted; `SourceFile.retained=0` | Retain original when source retention implementation is approved | Pending human confirmation |
| Original TXT | Source | Retained by default | User/policy controlled, pending confirmation | Non-rebuildable | High | Uploaded bytes are written to `uploads/`, processed to `output/`, then deleted; `SourceFile.retained=0` | Retain original or explicitly allow deletion under confirmed authority | Pending human confirmation |
| Original image | Source | Retained by default when image ingestion exists | User/policy controlled, pending confirmation | Non-rebuildable | High | Not currently a main upload source in this policy scope | Treat as source evidence if implemented | Pending human confirmation |
| Original audio | Source | Retained by default or policy-controlled | User/policy controlled, pending confirmation | Non-rebuildable | High | Future concept only | Treat as source evidence if implemented | Pending human confirmation |
| Original video | Source | Retained by default or policy-controlled | User/policy controlled, pending confirmation | Non-rebuildable | High | Future concept only | Treat as source evidence if implemented | Pending human confirmation |
| Original email | Source | Retained by default, policy-controlled, or external-reference-only | User/admin/policy controlled, pending confirmation | Non-rebuildable; recapture may differ | High | Future concept only | Define mailbox/export capture semantics before implementation | Pending human confirmation |
| Captured webpage | Source | Retained snapshot when lawful; otherwise external-reference-only | User/admin/policy controlled, pending confirmation | Non-rebuildable; live page may change | High for archive | Future concept only | Capture snapshot/provenance policy required | Pending human confirmation |
| Uploaded ZIP/package | Source | Retained by default | User/policy controlled, pending confirmation | Non-rebuildable | High | Future concept only | Treat package as source; extracted members may become child sources/artifacts later | Pending human confirmation |
| Rendered page image | Artifact | Policy-controlled or temporary | System/policy controlled | Approximately rebuildable only when source and processing configuration remain available | Medium; high only as current fallback evidence | Stored in `pdf_pages.page_image_data` and currently durable while book remains | Keep only as explicitly retained artifact or cache once originals are retained | Pending human confirmation |
| OCR raw JSON | Artifact | Policy-controlled | System/policy controlled | Approximately rebuildable | Medium | Stored in `pdf_pages.ocr_raw_json` after background OCR | Associate with future processing provenance if retained | Pending human confirmation |
| OCR normalized JSON | Artifact | Policy-controlled | System/policy controlled | Approximately rebuildable | Medium | Not a distinct implemented object | Introduce only with processing/canonicalization need | Pending human confirmation |
| OCR Markdown/text | Artifact / Presentation | Policy-controlled or temporary depending use | System/policy controlled | Approximately or deterministically rebuildable depending source | Low to medium | TXT processed output exists for TXT uploads; PDF text assembled from MinerU JSON | Decide canonical vs presentation role before durable retention | Pending human confirmation |
| Layout result | Artifact | Policy-controlled or temporary | System/policy controlled | Approximately rebuildable with same model/configuration | Medium | Mixed: in OCR JSON, MinerU JSON, memory, optional debug JSON | Retain only when needed for provenance or artifact regeneration | Pending human confirmation |
| Cropped figure image | Artifact / Presentation | Policy-controlled while Reader references it | System/policy controlled | Approximately rebuildable when source/page/layout remain available | Medium | Stored in `book_images.image_data` | Preserve compatibility, later classify as artifact/asset | Pending human confirmation |
| Cropped table image | Artifact / Presentation | Policy-controlled while Reader references it | System/policy controlled | Approximately rebuildable when source/page/layout remain available | Medium | Stored in `book_images.image_data` | Preserve compatibility, later classify as artifact/asset | Pending human confirmation |
| MinerU result | Artifact / Presentation input | Policy-controlled while current Reader depends on it | System/policy controlled | Approximately rebuildable if OCR/page inputs remain | Medium | Stored in `mineru_results.result_json` | Keep compatibility until canonical Reader source is approved | Pending human confirmation |
| Processing logs | Artifact | Temporary unless audit policy requires retention | System/policy controlled | Approximately rebuildable at best; exact logs are not reproducible | Low to medium | Runtime logs only; not modeled as durable objects | Define audit logging separately if needed | Pending human confirmation |
| Debug diagnostics | Artifact | Temporary | System-controlled | Not applicable | Low | Optional layout debug JSON may persist under `output/layout_debug` | Keep outside durable Storage unless explicitly retained | Pending human confirmation |
| Canonical content | Knowledge | Policy-controlled once accepted canonicalization exists | User/admin/policy controlled, pending confirmation | Partially rebuildable; accepted revisions may not be exact | High | Not fully implemented as separate canonical object | Design in future canonicalization task | Pending human confirmation |
| Extracted facts | Knowledge | Policy-controlled with evidence links | User/admin/policy controlled, pending confirmation | Partially rebuildable; validated facts may not be exact | High when validated | Future concept only | Retain with provenance when implemented | Pending human confirmation |
| Summary | Knowledge / Presentation | Policy-controlled or temporary depending accepted/user-edited status | User/system/policy controlled, pending confirmation | Generated summaries approximately rebuildable; user edits non-rebuildable | Medium | Future concept only | Distinguish generated cache from accepted/user-authored knowledge | Pending human confirmation |
| Note | Knowledge / Presentation | Retained by default for user-authored notes; policy-controlled otherwise | User/policy controlled, pending confirmation | User notes non-rebuildable; generated notes approximately rebuildable | Medium to high | Future concept only | Treat user-authored notes as non-rebuildable | Pending human confirmation |
| Flashcard | Knowledge / Presentation | Policy-controlled if user-reviewed; temporary for draft generation | User/system/policy controlled, pending confirmation | Drafts approximately rebuildable; user-reviewed cards partially rebuildable | Medium | Future concept only | Define learning ownership before implementation | Pending human confirmation |
| Mind map | Knowledge / Presentation | Policy-controlled if user-edited/accepted; temporary for draft views | User/system/policy controlled, pending confirmation | Drafts approximately rebuildable; user-edited maps partially rebuildable | Medium | Future concept only | Define accepted vs generated status later | Pending human confirmation |
| Quiz | Knowledge / Presentation | Policy-controlled for attempts/results; temporary for draft questions | User/system/policy controlled, pending confirmation | Questions approximately rebuildable; attempts/results non-rebuildable | Medium | Future concept only | Separate generated quiz from user response records | Pending human confirmation |
| Embedding | Knowledge / Index Artifact | Temporary or policy-controlled index artifact | System/policy controlled | Approximately rebuildable from same model/version and text | Low evidence; high retrieval utility | Future concept only | Treat as rebuildable index unless accepted otherwise | Pending human confirmation |
| Search index | Knowledge / Index Artifact | Temporary or policy-controlled index artifact | System/policy controlled | Deterministically or approximately rebuildable depending index type | Low evidence; high retrieval utility | Future concept only | Rebuild from canonical/source-derived content | Pending human confirmation |
| Knowledge graph data | Knowledge | Policy-controlled when accepted; temporary for generated candidates | User/admin/policy controlled, pending confirmation | Partially rebuildable; validated edits may not be exact | High | Future concept only | Require separate design and evidence links | Pending human confirmation |
| Presentation cache | Presentation | Temporary | System-controlled | Deterministically rebuildable where applicable | Low | Current Reader depends on processed TXT, MinerU JSON, and image blobs rather than a named cache | Never authoritative; rebuild from knowledge/artifacts where possible | Pending human confirmation |

## Current critical gap

Original TXT and PDF bytes are currently deleted after processing begins or succeeds. The upload path records `SourceFile` metadata, including original filename, file type, MIME type, byte size, checksum, `retained=0`, and primary-source status, but it does not keep a storage reference to retained source bytes.

As a result, `SourceFile` may retain metadata only. Rendered pages, processed TXT files, OCR raw JSON, and MinerU outputs may become de facto evidence because the original source is gone. This violates the intended evidence model in which Source represents original evidence and derived artifacts remain derived. This state is transitional and must be corrected by a future implementation task approved after this policy is confirmed.

## User choice

Users may need explicit choices in these areas:

- retain original;
- delete original;
- retain selected artifacts;
- keep diagnostics;
- export before deletion.

Personal deployments should favor understandable defaults: retain originals by default, allow explicit delete, and provide export-before-delete guidance when implemented. Enterprise deployments should allow administrator or tenant policy to constrain user choices. Regulated deployments may require retention schedules, legal holds, audit logs, or deletion restrictions that override ordinary user preference.

This section does not design UI. It identifies policy choices that future UI/API work must respect.

## Enterprise and compliance considerations

Enterprise and regulated use cases may treat originals and selected artifacts as records. Contracts, quality records, test records, medical records, financial records, and legal documents may require retention schedules, legal holds, auditability, evidence provenance, and controlled purge. Atlas should be able to express these concepts without embedding jurisdiction-specific legal rules into the generic storage layer.

This document is not legal advice and does not define jurisdiction-specific requirements. Human legal/compliance review is required before applying Atlas retention policy to regulated records.

## Deletion semantics

Future implementation must answer these questions before building source deletion, purge, or garbage collection:

- What does deleting a `Document` mean?
- Are `SourceFile` records and retained source bytes deleted immediately?
- Can a source be detached from an active `Document` but retained for audit, hold, or archive?
- What happens to derived artifacts when the source is deleted?
- What happens to facts and evidence links when evidence disappears?
- Is soft delete required later?
- Is purge distinct from archive?
- What must be logged, and who can see the log?

This document does not implement soft delete, purge, archive, or lifecycle jobs.

## Recommended v1 source policy

### Codex Recommendation — Human Confirmation Required

Codex recommends **Option B: Retain originals by default; user may explicitly delete** for the next implementation stage, with policy hooks left open for Option C in enterprise/regulatory deployments.

| Option | Simplicity | Evidence integrity | Storage cost | User control | Enterprise suitability | Rollback | Future migration | Assessment |
|---|---|---|---|---|---|---|---|---|
| Option A: Always retain originals | Highest implementation simplicity | Strongest | Highest | Lowest | Good for locked-down archives, weak for privacy choice | Strong | Easy to migrate retained objects | Too rigid as a universal policy |
| Option B: Retain originals by default; user may explicitly delete | High | Strong by default | Moderate to high | Strong | Good if admin policy can restrict deletion later | Strong unless user deletes | Good; retained source references exist for most records | Recommended v1 source-retention policy, pending confirmation |
| Option C: Retention depends on document type or deployment policy | Medium to low | Strong when policy is correct | Tunable | Depends on policy | Strongest long-term enterprise fit | Strong for retained classes | Good, but needs policy machinery | Defer as configurable extension |
| Option D: Metadata-only `SourceFile` remains allowed as a normal state | High short-term | Weak | Lowest | Ambiguous | Poor for audit and reprocessing | Weak | Preserves current gap | Not recommended except as explicit external-reference or deliberate deletion state |

This recommendation is not accepted. Human confirmation is required before implementation.

## Open questions

1. Should v1 retention apply to both PDF and TXT originals, or only PDF originals first?
2. Should users be able to delete originals while keeping Reader content?
3. What explicit warning or export requirement is needed before source deletion?
4. Should retained source deletion be blocked when knowledge/facts cite it?
5. Are any M1 deployments expected to require policy-controlled enterprise or regulated retention behavior?
6. What retention should apply to failed uploads that created partial `Document` or `SourceFile` state?
7. Should exact OCR reproducibility require retaining processing versions and parameters before deleting artifacts?

## Non-goals

This document does not implement retention. It does not define provider interfaces, S3/R2 configuration, object keys, database schema, lifecycle jobs, garbage collection, encryption, backups, soft delete, purge, or UI.

## Decision table

| Decision | Status | Notes |
|---|---|---|
| Source represents original evidence. | Accepted | Reuses accepted Atlas architecture principles. |
| `Document` is a business aggregate, not a Digital Object. | Accepted | Storage should not treat `Document` as stored bytes. |
| Information layer and ownership are orthogonal. | Accepted | Classification does not decide owner by itself. |
| Information layer remains Source / Artifact / Knowledge / Presentation. | Accepted | Existing Atlas Digital Object Taxonomy. |
| Retention policy is a separate dimension. | Accepted | Retention duration/lifecycle is not inferred from information layer, owner, purpose, or rebuildability. |
| Deletion authority is a separate dimension. | Accepted | Who may authorize deletion is independent of retention duration. |
| Rebuildability is a separate dimension. | Accepted | Rebuildability informs policy but does not determine it by itself. |
| Mixed three-class v1 vocabulary. | Rejected | Atlas will not collapse policy into labels such as User-managed Source, Regenerable Artifact, or Temporary Diagnostic. |
| Exact source retention policy. | Pending human confirmation | Option B remains a recommendation only. |
| Metadata-only `SourceFile` as a normal state. | Pending human confirmation | Not accepted except where future policy deliberately allows deletion or external-reference-only sources. |
| Exact database fields/enums. | Deferred | No schema representation is defined here. |
| Exact retention periods. | Deferred | Deployment and policy decisions remain future work. |
| Enterprise/compliance policy implementation. | Deferred | Legal hold, compliance schedules, and enterprise policy engines are not implemented here. |
| Deletion semantics, audit logs, soft delete, purge, archive. | Deferred | Requires future design. |
| Provider interface, object keys, schema, migrations, lifecycle jobs. | Not in scope | Explicit non-goals for this document. |

## M1-003D retained-state implementation

For M1-003D, `SourceFile.retained = 1` means Atlas successfully stored the original source bytes through the configured Storage provider and recorded `SourceFile.storage_reference`. It is not a continuous proof that the object still exists. Infrastructure loss, manual deletion, or provider failure may leave `retained = 1` and `storage_reference != null` while the object is missing; treat that as a broken-reference / infrastructure-consistency condition and verify actual existence with `Storage.exists()` or `Storage.get()`. `retained = 0` means the original source bytes are not retained by Atlas. Existing columns (`storage_reference`, `retained`, `byte_size`, `checksum_sha256`, `original_filename`, `mime_type`, and `file_type`) are sufficient, so no Alembic migration is needed.

Upload ordering is: read upload bytes, generate a logical source reference, write bytes through Storage with expected size/checksum, create `Document` and primary `SourceFile` metadata with actual Storage metadata, then commit. If the metadata commit fails after object write, upload code rolls back and attempts best-effort deletion of the new object, logging cleanup failures. Book deletion performs the inverse business action. It reads bytes before source deletion, tracks every source deleted during the attempt, restores already-deleted sources if a later retained-source delete fails, and also restores deleted sources if the metadata delete commit fails. If TXT/PDF processing fails after the source is retained, the retained source remains available as evidence while the document may be marked failed.

The current Hugging Face Space is a test-only deployment with no Persistent Storage configured; retained source bytes and SQLite data are stored on ephemeral container storage and may be lost during rebuilds. This is accepted only for the disposable test environment. Production must use persistent mounted storage or a durable provider before real user data is accepted. TXT processing still writes a transitional processed TXT file under `output/` for Reader compatibility. PDF page images, OCR JSON, MinerU JSON, and other BLOB/text persistence remain unchanged and are explicitly deferred.
