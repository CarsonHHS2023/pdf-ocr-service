# ADR-005 — Projection, Compatibility, Migration, and Retention

| Field | Value |
|---|---|
| Document Type | Architecture Decision Record |
| Decision Status | Accepted |
| Lifecycle Status | Active |
| Decision Date | 2026-07-21 |
| Effective Date | 2026-07-21 |
| Authority Domain | M4 derived projection boundary, Reader Content Stream compatibility role, legacy Reader migration and retirement conditions, backfill/rebuild strategy, and source/content/evidence/asset/projection deletion-retention interaction |
| Related Milestone | M4 — Structured Content / Structured Document Foundation |
| Related Roadmap | Roadmap v3 |
| Depends On | ADR-002 — Structured Content Lifecycle and Accepted/Current Selection; ADR-003 — Structured Content Shape and SPR Transformation Boundary; ADR-004 — Provenance, Evidence, Assets, and Processing Runs |
| Supersedes | None |
| Implementation Status | Not authorized / Not implemented by this ADR |

## Context

ADR-002 defines immutable Structured Content versions and explicit accepted/current selection. ADR-003 defines the content version, page, and node shape, the pure SPR-to-content transformer, validation, and recovery propagation into Structured Content and Structured Document assembly. ADR-004 defines ProcessingRun lineage, provenance, evidence anchors, logical Assets, and renditions.

M4 must provide a stable derived boundary to M5 without making Reader serialization canonical. The governing handoff is:

Selected Structured Content version
→ Structured Document assembled view
→ derived projection
→ optional Reader Content Stream v2 compatibility serialization
→ M5 Reader

The current Reader path consumes legacy `MineruResult.result_json`, processed text for TXT/non-PDF content, `ContentBlock`, `PdfPage`, and `BookImage` behavior. Current image marker serialization uses the Reader Content Stream marker form `$%$%$%{image_id}$%$%$%`. These entities and stream forms remain compatibility structures and migration sources, not the target Structured Content model. No Structured Content-derived projection exists yet.

Current deletion behavior is centered on legacy data, document cascades, and source/storage cleanup. That behavior must not be assumed sufficient for immutable content versions, evidence anchors, logical assets, renditions, ProcessingRuns, Raw Processing Results, or SPR artifacts. M4 therefore needs an additive transition strategy that preserves current behavior until parity and rollback conditions are met.

Projection is noncanonical. Reader remains M5. This ADR does not authorize Reader route cutover, endpoint changes, schema changes, code changes, data deletion, backfill execution, rebuild execution, or M5 Reader behavior.

## Decision drivers

- canonicality protection;
- deterministic source-version binding;
- projection regeneration;
- current Reader compatibility;
- no destructive cutover;
- parity validation;
- rollback;
- legacy data preservation;
- idempotent backfill;
- restartable migration;
- rebuild safety;
- immutable content lifecycle;
- accepted/current selection safety;
- evidence and asset retention;
- deletion consistency;
- source/raw/SPR retention dependencies;
- large-document performance;
- optional cache invalidation;
- SQLite/PostgreSQL compatibility;
- additive Alembic sequencing;
- M5 handoff clarity;
- testability;
- bounded M4 scope;
- avoiding dual canonical stores.

## Projection options

### Option A — Direct application DTO assembled on demand

Assemble an application-independent projection DTO from Structured Document for each request. This has the simplest canonicality model, remains always current with the selected version, and needs no cache invalidation. Its cost is possible performance pressure for large documents or frequent reads.

### Option B — Persisted projection rows/documents

Persist Reader-facing or application-facing projection as durable data. This enables fast reads, but creates stale-state risk, shadow-canonical risk, lifecycle complexity, and invalidation complexity.

### Option C — Derived projection plus optional cache artifact

Define a stable derived projection DTO or equivalent assembled result and optionally cache its deterministic serialization using source content version and projection version. This protects canonicality while preserving a future performance path. It requires cache invalidation rules and explicit projection-contract versioning.

### Option D — Dual-write legacy Reader entities

Write Structured Content and simultaneously populate `MineruResult`, `ContentBlock`, `PdfPage`, or `BookImage`. This may ease migration, but it is rejected as the primary architecture because it creates dual truth, synchronization, and retirement problems.

## Accepted projection decision

Option C is accepted in a minimal form:

- the authoritative projection is a derived, application-independent DTO or equivalent assembled result;
- it is created from one explicitly selected Structured Content version through the Structured Document boundary;
- it is noncanonical and rebuildable;
- it must identify the source content version;
- it must identify the projection contract/version;
- it must preserve content order, recovery state, and evidence/asset references required by the receiving boundary;
- it must not modify accepted/current content;
- projection failure must not alter selection;
- persisted or cached projection artifacts are optional and may be introduced only when performance evidence justifies them.

This ADR does not finalize DTO fields or a JSON schema.

## Projection cache rules

If a projection cache or artifact is later introduced, it must include or be bound to:

- source content version identity;
- projection contract/version;
- assembler/projection implementation version;
- deterministic cache key;
- checksum where appropriate;
- generation timestamp;
- invalidation on accepted/current selection change;
- invalidation when a referenced required asset/rendition changes;
- invalidation when projection contract changes;
- rebuildability from accepted content;
- no independent editorial mutation;
- no use as accepted/current content identity.

A stale cache must never select content. Cache absence must not make canonical content unavailable. Exact cache provider and storage remain deferred.

## Reader Content Stream options

### Option A — Canonical content contract

Rejected because Reader serialization is presentation-oriented and cannot replace Structured Content.

### Option B — Compatibility/projection serialization

Map the derived projection into the existing Reader Content Stream v2 format for temporary compatibility.

### Option C — Deprecated immediately

Rejected because current routes and clients may still require it.

### Option D — Dual canonical contract

Rejected because Structured Content and Reader stream cannot both be canonical.

## Accepted Reader Content Stream decision

Option B is accepted. Reader Content Stream v2 is a compatibility/presentation serialization derived from the projection boundary. It:

- is noncanonical;
- is versioned independently from Structured Content;
- identifies or can be associated with its source content version;
- may omit domain details not required by legacy Reader behavior;
- may carry recovery/asset information needed by compatibility consumers;
- must not be used as the persistence source for Structured Content;
- must not be mutated and written back as canonical content;
- may remain temporarily supported during migration;
- may later be superseded by an M5 Reader API/contract.

Exact mapping remains deferred to implementation and contract work.

## Legacy Reader entities

### `MineruResult`

- compatibility-only current PDF Reader source;
- potential migration/backfill input;
- not target canonical content;
- must not remain the direct Reader source after authorized projection cutover.

### `ContentBlock`

- compatibility data and potential migration source;
- not the target Structured Content node model;
- may be retained until parity and backfill conditions pass.

### `PdfPage`

- compatibility/evidence-adjacent page data;
- may remain temporarily while source/raw/evidence coverage is validated;
- provider/raw JSON stored there must not become canonical content.

### `BookImage`

- compatibility asset store and migration source;
- not target logical Asset model;
- must remain until asset/rendition parity and rollback conditions pass.

### Current Reader serialization

- compatibility projection format;
- never canonical content.

### Current book routes

- M5/product read path;
- remain unchanged by this ADR;
- may be tested for parity but not switched here.

## Compatibility strategy

An adapter-based compatibility strategy is accepted. The target path is:

Selected Structured Content
→ Structured Document
→ derived projection
→ Reader Content Stream compatibility adapter
→ existing Reader consumer

Required rules:

- no direct provider JSON read in the target path;
- no direct SPR interpretation by Reader;
- no requirement to dual-write legacy tables;
- legacy reads may continue until cutover;
- new projection may be generated in shadow/parity mode;
- differences must be categorized and reviewed;
- compatibility adapter must be deterministic;
- adapter must not mutate Structured Content;
- adapter failure must not affect accepted/current selection.

Endpoint changes are not authorized.

## Legacy retirement conditions

A legacy read path or entity must not be retired until all applicable conditions are met:

1. Supported documents can be projected from selected Structured Content.
2. Deterministic projection fixtures pass.
3. Legacy/new parity fixtures pass or intentional differences are documented and accepted.
4. Reader route no longer depends directly on provider JSON, SPR, or legacy entity as canonical truth.
5. Backfill/rebuild strategy is approved and tested.
6. Existing data is migrated or explicitly excluded by policy.
7. Rollback path exists.
8. Asset/image/table compatibility is verified.
9. Recovery-state compatibility is verified.
10. Deletion and retention behavior is verified.
11. Monitoring/diagnostics for projection failures exist if required.
12. M5 separately authorizes Reader cutover.

Legacy physical deletion remains a later separately approved action.

## Migration options

### Option A — Destructive replacement migration

Replace legacy tables/data in one migration. Rejected due to rollback and data-loss risk.

### Option B — Additive schema plus immediate cutover

Add Structured Content tables and immediately switch Reader. Rejected because parity and backfill evidence would be insufficient.

### Option C — Additive schema, shadow transformation/projection, controlled backfill and later cutover

This is the safest rollout because it enables parallel validation, shadow projection, rollback, and an explicit retirement path. It adds temporary complexity.

### Option D — Permanent dual-write

Rejected as a long-term architecture due to divergence and dual-truth risk.

## Accepted migration strategy

Option C is accepted conceptually. The required conceptual sequence is:

1. Accept ADRs/contracts.
2. Add new schema additively.
3. Introduce in-memory domain types and deterministic fixtures.
4. Implement SPR-to-content transformation and validation.
5. Persist candidate/accepted content with provenance/assets.
6. Build Structured Document and derived projection.
7. Run compatibility/parity validation without primary cutover.
8. Backfill eligible legacy documents non-destructively.
9. Validate rollback and deletion behavior.
10. Perform Reader cutover only under separate M5 authorization.
11. Retire legacy reads later.
12. Remove legacy data/schema only under a separate destructive-cleanup decision.

This ADR does not authorize any step.

## Backfill strategy

A non-destructive, idempotent, restartable backfill strategy is accepted. Backfill must conceptually:

- support dry-run;
- identify eligible documents;
- record source legacy records used;
- identify the source, migration policy, and transformer version;
- produce a candidate content version;
- validate candidate content;
- avoid automatic accepted/current replacement unless explicit policy allows;
- avoid duplicating an equivalent candidate;
- retain error/result status;
- continue safely after partial failure;
- support retry;
- leave legacy records unchanged;
- produce a summary of succeeded, skipped, failed, and already-migrated items;
- preserve evidence/provenance links;
- avoid treating legacy Reader serialization as canonical truth.

Exact script, API, and job shape remain deferred.

## Backfill eligibility

Conceptual eligibility checks include:

- Document and source identity available;
- required legacy data exists;
- legacy payload parses safely;
- source checksum/identity can be resolved where required;
- migration adapter supports the document type/version;
- no existing equivalent content version;
- assets can be resolved or marked degraded under explicit policy;
- recovery state can be mapped;
- unsupported cases are skipped with traceable reason.

Operational filters remain deferred.

## Rebuild strategy

Rebuild is accepted with these constraints:

- rebuild begins from retained source/raw/SPR evidence according to an available supported path;
- rebuild creates a new ProcessingRun;
- rebuild uses an explicit transformer/policy version;
- rebuild produces a new candidate unless deterministic equivalence identifies an existing candidate;
- rebuild does not automatically select the new candidate;
- prior accepted content remains available;
- failed rebuild leaves accepted/current selection unchanged;
- rebuild artifacts and diagnostics remain traceable;
- projection is regenerated only from the selected version unless explicitly previewing a candidate;
- rollback selects a prior valid version under ADR-002.

Backfill converts legacy existing data into the new content foundation. Rebuild reprocesses or retransforms retained evidence under a defined policy.

## Deletion and retention options

### Option A — One document cascade deletes everything

Simple, but unsafe for immutable evidence and accepted-content dependencies.

### Option B — Independent retention with unrestricted deletion

Flexible, but risks dangling provenance/evidence.

### Option C — Dependency-aware layered retention and deletion

Separate policy domains with referential safeguards and derived-cache cleanup.

### Option D — Permanent retention of all versions/evidence

Strong audit, but unbounded storage and potentially inappropriate privacy/legal behavior.

## Accepted retention/deletion decision

Option C is accepted: dependency-aware layered retention and deletion. Distinct policy layers are:

- Document/business record;
- SourceFile/source evidence;
- Raw Processing Result;
- SPR artifact;
- ProcessingRun;
- candidate content version;
- selected accepted/current content version;
- evidence anchors;
- logical Asset;
- Asset rendition;
- projection/cache;
- legacy compatibility entities.

Exact periods remain deferred.

## Minimum deletion invariants

### Document deletion

Deleting a Document requires an explicit policy covering selected content, candidate versions, ProcessingRuns, Raw Result/SPR evidence, SourceFiles, assets/renditions, evidence anchors, projections/caches, and legacy compatibility records. Current legacy cascade behavior is not automatically sufficient.

### Candidate deletion

Deleting an unselected candidate must not affect selected content. Dependent candidate projections/caches must be invalidated. Required run/evidence history must follow policy. Shared assets/evidence must not be deleted while still referenced.

### Selected version deletion

Selected version deletion must not occur silently. It requires prior reselection, tombstone, or Document deletion policy; must invalidate derived projections; and must preserve required audit/provenance according to policy.

### Source evidence deletion

Source evidence deletion must not leave accepted content with falsely resolvable evidence. It requires explicit detachment, tombstone, archival substitution, or content deletion policy, and evidence-anchor resolvability must be considered.

### Raw Result / SPR deletion

Raw Processing Result and SPR deletion must respect accepted-content provenance dependencies. Derived content does not automatically justify deleting processing evidence. Exact retention period is deferred.

### Asset deletion

Deleting a rendition does not delete logical Asset identity. Deleting logical Asset requires checking content-node and evidence references. Missing asset state may remain after rendition deletion when policy allows.

### Projection/cache deletion

Projection/cache deletion is always safe when it is purely derived and rebuildable. It must not alter accepted/current content and can occur through invalidation/cleanup policy.

### Legacy deletion

Legacy deletion is allowed only after retirement criteria and separate destructive-cleanup approval.

## Retention classes

Conceptual retention classes, without durations, are:

- required for accepted/current content;
- required for audit/provenance;
- rebuild source;
- migration compatibility;
- derived/rebuildable;
- temporary operational artifact;
- legal/privacy-policy controlled;
- orphaned/unreferenced candidate;
- superseded but retained history.

Exact retention periods and legal requirements remain deferred.

## Tombstones and soft deletion

Later implementation may use hard deletion, soft deletion, tombstone, archived/unavailable state, or retention lock depending on the data class. This ADR does not select one universal method. An unavailable/deleted dependency must be represented truthfully rather than silently appearing resolvable.

## Projection and deletion interaction

- projection identifies source content version;
- selection change invalidates prior selected-version projection cache;
- deleted/deselected content invalidates dependent projections;
- deleted rendition invalidates projection artifacts that embed it;
- projection regeneration must not restore deleted source/evidence improperly;
- projection deletion does not affect content;
- cache cleanup can be independent when rebuildable.

## Recovery presentation boundary

M4 projection carries application-relevant recovery state. Reader Content Stream compatibility mapping may carry recovery metadata only as required by the contract. M5 owns user-facing wording, placeholders, banners, and interaction. Missing/degraded pages or assets must not be presented as complete merely because a projection was generated. Projection parity must include recovery-state cases.

## Supported initial document types

Initial migration/backfill support may be limited to document types with deterministic legacy adapters and sufficient evidence. PDF and existing TXT/non-PDF compatibility paths may be treated separately. Unsupported document types must be skipped with traceable reason. This ADR does not mandate all DocumentType values. Exact initial supported list remains a later implementation-plan decision. M4-DEC-019 remains open or later planning-bound and is not accepted by this ADR.

## Performance principles

- projections should avoid unbounded query-per-node behavior;
- large-document projection may justify caching after measurement;
- backfill must support bounded batches;
- rebuild/backfill must avoid loading all documents into memory;
- cache use must remain optional and derived;
- exact SLOs and batch sizes remain deferred under M4-DEC-020.

No production SLO values are selected here.

## Consequences

Positive consequences:

- canonicality remains protected;
- stable M4→M5 boundary;
- Reader compatibility without dual truth;
- safe additive migration;
- deterministic parity testing;
- rollback and restartable backfill;
- rebuild safety;
- evidence-aware deletion;
- projection cache can be added later;
- legacy retirement has measurable gates.

Costs:

- temporary dual-read/shadow complexity;
- parity fixture maintenance;
- backfill orchestration;
- retention dependency tracking;
- projection invalidation;
- more migration and deletion tests;
- delayed destructive cleanup;
- possible temporary storage growth.

Neutral consequences:

- current Reader path remains;
- Reader cutover is still M5;
- exact DTO/cache/schema/scripts remain open;
- legacy tables remain until separately retired.

## Rejected alternatives

The following are rejected as primary architecture:

- projection as canonical content;
- Reader Content Stream as canonical content;
- Reader serialization written back into Structured Content;
- direct Reader consumption of provider JSON or SPR;
- permanent dual-write to legacy and new content stores;
- immediate Reader cutover with no parity;
- destructive one-step migration;
- latest successful backfill/rebuild automatically becoming current;
- backfill mutating legacy rows;
- rebuild overwriting accepted content;
- one universal cascade deleting all evidence;
- deleting source/raw/SPR because a projection exists;
- deleting selected content without reselection/tombstone/document policy;
- `BookImage`, `MineruResult`, `ContentBlock`, or `PdfPage` as permanent target architecture;
- implementing M5 Reader behavior in this ADR.

## Normative invariants

1. Projection is derived and noncanonical.
2. Projection binds to exactly one source content version.
3. Projection failure does not change accepted/current selection.
4. Reader Content Stream is a compatibility/presentation serialization.
5. Reader Content Stream is not canonical content.
6. Reader does not treat provider JSON or SPR as canonical truth.
7. Legacy entities are migration/compatibility sources, not the target model.
8. Legacy records remain unchanged during non-destructive backfill.
9. Backfill is idempotent and restartable.
10. Backfill does not automatically replace selected content.
11. Rebuild creates a new run and candidate or identifies an equivalent candidate.
12. Rebuild does not silently overwrite accepted content.
13. Failed rebuild preserves current selection.
14. Legacy read retirement requires parity and rollback evidence.
15. Reader cutover requires separate M5 authorization.
16. Projection caches are rebuildable and noncanonical.
17. Deleting a projection does not delete content.
18. Evidence required by accepted content is not silently deleted.
19. Selected content cannot be silently deleted.
20. Shared assets/evidence are not deleted while referenced.
21. Storage location is not logical asset identity.
22. Exact retention periods remain policy decisions.
23. Current legacy cascade behavior is not assumed sufficient.
24. Destructive legacy cleanup requires separate approval.
25. Implementation remains unauthorized by this ADR alone.

## Deferred decisions

- exact projection DTO;
- projection JSON/schema;
- projection cache provider;
- cache key implementation;
- Reader Content Stream field mapping;
- public Reader API;
- Reader cutover;
- exact parity tolerance;
- migration scripts/jobs;
- backfill operational interface;
- batch size;
- supported initial document types;
- exact legacy adapter rules;
- exact rebuild source priority;
- exact retention periods;
- legal hold/privacy erasure policy;
- hard delete vs soft delete/tombstone by entity;
- deletion API;
- cascade constraints;
- orphan cleanup;
- destructive legacy schema removal;
- performance SLOs;
- production rollout;
- external pilot;
- commercial release.

## Implementation guidance — non-normative and not authorized

Illustrative future components include `StructuredDocumentAssembler`, `ProjectionBuilder`, `ReaderContentStreamAdapter`, `ProjectionCache`, `LegacyContentAdapter`, `BackfillService`, `RebuildService`, `ProjectionParityHarness`, `RetentionPolicyResolver`, and `DeletionDependencyChecker`. These names are illustrative only. No implementation, code, schema, script, API, route change, migration, or operational execution is authorized by this guidance.

## Validation and future evidence expectations

Later implementation must demonstrate:

- projection identifies selected source content version;
- projection output is deterministic for the same content/projection version;
- projection failure leaves selection unchanged;
- cache invalidates on selection change;
- cache invalidates on relevant asset/projection-version change;
- Reader Content Stream adapter is deterministic;
- legacy/new parity for headings, paragraphs, lists, images, tables, and recovery-state fixtures;
- intentional parity differences are documented;
- backfill dry-run changes nothing;
- repeated backfill does not duplicate equivalent content;
- partial backfill failure is restartable;
- backfill does not alter legacy rows;
- rebuild creates run/candidate without automatic promotion;
- failed rebuild preserves current content;
- rollback reselects prior valid content;
- candidate deletion does not affect current selection;
- selected deletion is blocked or governed explicitly;
- projection deletion does not affect content;
- shared evidence/assets are protected while referenced;
- legacy Reader route remains unchanged until separately authorized.

These are future expectations; this ADR does not state that these tests already pass.

## Relationship to other decisions

### ADR-002

This ADR conforms to immutable versions, explicit accepted/current selection, atomic acceptance, no latest-run-wins, and rollback through selection.

### ADR-003

Projection consumes the deterministic content version/page/node shape, hierarchy/order, recovery state, and Structured Document assembled view. It does not redefine content shape.

### ADR-004

Migration, rebuild, and deletion must preserve ProcessingRun lineage, evidence-anchor resolvability, logical Asset identity, rendition separation, and source/raw/SPR provenance.

### M5

M5 owns Reader API and product behavior, user-facing Recovery Presentation, navigation, lexical search, Speed Reading, and authorized Reader read-path cutover. This ADR only defines the boundary and migration preconditions.

## References

- [Documentation governance](../../project/document-governance.md)
- [Roadmap v3 decision](../../roadmap/roadmap-v3-decision.md)
- [Current roadmap](../../roadmap/roadmap.md)
- [M3](../../milestones/M3.md)
- [M4](../../milestones/M4.md)
- [M5](../../milestones/M5.md)
- [M6](../../milestones/M6.md)
- [M7](../../milestones/M7.md)
- [ADR-002 — Structured Content Lifecycle and Selection](ADR-002-structured-content-lifecycle-and-selection.md)
- [ADR-003 — Structured Content Shape and Transformation](ADR-003-structured-content-shape-and-transformation.md)
- [ADR-004 — Provenance, Evidence, Assets, and Processing Runs](ADR-004-provenance-evidence-assets-and-processing-runs.md)
- [Canonical data flow](../canonical-data-flow.md)
- [Document core information model](../document-core-information-model.md)
- [Structured-content architecture](../document-core-structured-content-architecture.md)
- [Processing contract](../document-processing-contract.md)
- [Recovery-presentation architecture](../recovery-presentation-architecture.md)
- [Persistence processing foundation](../persistence-processing-foundation.md)
- [SPR contract](../../contracts/structured-processing-result-v1.md)
- [Reader Content Stream contract](../../contracts/reader-content-stream-v2.md)
- [Mixed recovery ADR](../../adr/ADR-0001-mixed-multi-page-recovery-policy.md)
- [Service-boundaries ADR](ADR-001-service-boundaries.md)
