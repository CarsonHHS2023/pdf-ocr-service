# ADR-004 — Provenance, Evidence, Assets, and Processing Runs

| Field | Value |
|---|---|
| Document Type | Architecture Decision Record |
| Decision Status | Accepted |
| Lifecycle Status | Active |
| Decision Date | 2026-07-21 |
| Effective Date | 2026-07-21 |
| Authority Domain | M4 durable processing-run identity, Structured Content provenance and evidence anchors, Observation persistence boundary, and content-visible asset identity/storage-reference boundary |
| Related Milestone | M4 — Structured Content / Structured Document Foundation |
| Related Roadmap | Roadmap v3 |
| Depends On | ADR-002 — Structured Content Lifecycle and Accepted/Current Selection; ADR-003 — Structured Content Shape and SPR Transformation Boundary |
| Supersedes | None |
| Implementation Status | Not authorized / Not implemented by this ADR |

## Context

SourceFile preserves source evidence identity, source checksum information, source media metadata, retention state and storage references. Raw Processing Result preserves provider-specific processing evidence, including provider payloads, provider status, provider identifiers and retained artifact references. The Structured Processing Result (SPR) preserves provider-independent normalized processing output, including normalized observations, evidence links, warnings, assets and provenance needed by later transformation.

ADR-002 defines immutable Structured Content versions and explicit accepted/current selection. ADR-003 defines the Structured Content version/page/node shape and the deterministic Raw Result/SPR-to-content transformation boundary. M4 now needs durable traceability from accepted Structured Content back to the source and processing evidence that produced it.

Current runtime envelopes already contain useful run-like identity, including attempt, correlation, provider job, request, profile, status and raw-result references, but no durable ProcessingRun model exists. SPR contains observations and evidence links, but durable Observation rows are not automatically required for the minimum M4 foundation. Legacy BookImage stores image bytes and metadata for compatibility, but it is not the target asset architecture. Provider-native payloads and observations must remain noncanonical evidence and must not become canonical document content.

The accepted traceability chain is:

```text
Source Evidence / SourceFile
→ ProcessingRun / Raw Processing Result evidence
→ SPR
→ Structured Content provenance/evidence anchors
→ Structured Document
→ derived projections
```

## Decision drivers

- Auditability.
- Retry/rebuild lineage.
- Source-to-content traceability.
- Citation/evidence resolution.
- Recovery diagnostics.
- Provider independence.
- Bounded storage growth.
- Avoiding duplication of Raw Result and SPR.
- Avoiding a full Observation ontology before justified.
- Asset lifecycle and deletion.
- Image/table projection.
- Immutable content-version semantics.
- Deterministic transformation.
- M6 evidence-backed Q&A/citations.
- M7 archive provenance.
- Large-document scalability.
- Object-storage compatibility.
- Additive migration feasibility.
- Testability.
- No second canonical store.
- No provider leakage.

## ProcessingRun options

### Option A — No durable ProcessingRun

Use runtime job/attempt IDs and raw-result metadata only. This has the lowest complexity and preserves current compatibility, but it leaves weak durable retry/rebuild history, weak failure/status auditability and difficult relationships among multiple results for one Document.

### Option B — Minimal durable ProcessingRun

Persist one durable execution/provenance identity containing, conceptually, Document, SourceFile/source identity, run identity, provider/profile/model/config identity, status, timestamps, attempt/retry/rebuild lineage, Raw Processing Result reference, SPR reference, transformation/content-version references where applicable and safe error summary. This is strong enough provenance for M4 while keeping complexity bounded and avoiding a detailed orchestration ledger.

### Option C — Rich ProcessingRun ledger

Persist stages, attempts, costs, token/GPU usage, metrics, artifacts, timings and subtasks. This has operational value, but it is too broad for the minimum M4 foundation and would turn a provenance decision into an orchestration telemetry product.

### Option D — ProcessingRun only as artifact manifest

Persist run manifests in object storage with only a minimal database reference. This reduces relational shape, but weakens querying, constraints, lineage validation and retention coordination for accepted content.

## Accepted ProcessingRun decision

Option B is accepted: M4 requires a minimal durable ProcessingRun.

### Role

ProcessingRun is durable processing/provenance identity. It is not document content, not accepted/current Structured Content, not a canonical content version, not an Observation, not a projection and not a product workflow record.

### Minimum conceptual information

A run must be able to identify or reference:

- Document.
- SourceFile.
- Source checksum/version identity.
- Provider.
- Provider profile/model/revision/config identity.
- Attempt/correlation/job identity where available.
- Run purpose, such as initial processing, retry, rebuild or backfill.
- Status.
- Start/completion/failure timestamps.
- Parent/prior run when representing retry or rebuild lineage.
- Raw Processing Result reference/checksum.
- SPR identity/schema version/reference.
- Transformer version/policy identity when content transformation occurs.
- Resulting candidate content version identity where applicable.
- Safe error category/summary.
- Optional artifact references.

Exact field names and schema remain deferred.

### Status scope

Run status may conceptually distinguish created/pending, running, succeeded, partially succeeded, failed, cancelled if supported and superseded or obsolete if later justified. This ADR does not finalize enum spelling.

Run success does not imply content acceptance. The latest successful run does not become current automatically. One run may produce no valid candidate. One Document may have many ProcessingRuns. One content version must retain lineage to the run or equivalent processing identity that produced it.

### Retry and rebuild

Retry/rebuild produces a new ProcessingRun identity or explicit attempt lineage, does not mutate prior historical run evidence, does not automatically select new content, remains traceable to source/raw/SPR/transformer inputs, supports deterministic duplicate detection under ADR-002 and ADR-003, and must not overwrite prior errors or artifacts.

### Rich telemetry deferred

Costs, fine-grained stage events, detailed performance metrics, provider billing, GPU utilization and full orchestration event history remain deferred unless later production evidence requires them.

## Observation options

### Option A — No durable Observation table

Keep normalized observations inside retained SPR and Raw Result artifacts. Content evidence anchors reference stable SPR observation/evidence IDs.

### Option B — Selective durable Observation persistence

Persist only evidence units needed for citation, recovery, audit, direct query or retained source-region resolution. This can be introduced later without making every observation a row.

### Option C — Full normalized Observation model

Persist every provider/normalized observation as first-class rows. This improves query flexibility but creates high duplication, lifecycle complexity and storage growth.

### Option D — Provider-native observations only

Reject provider-native observations only because provider-native observations are not provider-independent and must remain Raw Result evidence.

## Accepted Observation decision

The accepted minimum M4 direction is:

- No full durable Observation table is required for the minimum M4 foundation.
- Observations remain retained within Raw Processing Result and/or SPR artifacts.
- Structured Content persists selective evidence anchors and references.
- Selective durable Observation records may be introduced later only when a documented query, citation, audit or retention requirement cannot be met safely by references.

The conceptual term Observation remains valid. No full Observation table does not mean evidence is discarded. Content nodes must still resolve back to stable evidence. Provider-native observations remain noncanonical. M6 generated claims may cite M4 evidence anchors but must not rewrite them as generated truth. Future selective persistence must not duplicate all provider payloads.

## Provenance model

M4 accepts a layered provenance model.

### Source provenance

Minimum traceability must include Document, SourceFile, source checksum/hash, storage reference, source media/type where known, and source page index and dimensions where applicable.

### Processing provenance

Minimum traceability must include ProcessingRun, Raw Processing Result identity/reference/checksum, provider/profile/model/revision/config, SPR identity/schema/version/reference, normalizer version, transformer version and transformation policy/config hash.

### Content provenance

Content version/page/node must retain sufficient references to determine which source and source page produced it, which run/raw result/SPR produced it, which transformer/policy produced it, which evidence anchors justify it, which recovery facts apply, which assets it references and which acceptance/current selection applies through ADR-002.

### Acceptance provenance

Accepted/current selection must be traceable to selected content version, prior selected version where replaced, selection timestamp, actor/system policy identity where applicable, and reason or acceptance policy identity where applicable. This ADR does not finalize event tables; ADR-002 governs the lifecycle requirement.

## Evidence-anchor model

M4 accepts selective durable evidence anchors. An evidence anchor conceptually identifies owning content version, owning page/node/asset when applicable, evidence kind, SourceFile, source page, source region/geometry or text span where available, Raw Processing Result reference, SPR result and SPR node/observation/evidence identity, recovery/warning identity where relevant, coordinate frame/unit/version and optional confidence when provider-independent and meaningful.

An anchor is a reference/locator, not duplicated provider payload. One content node may have zero, one or many anchors. One anchor may justify text, structure, asset, recovery or classification. Missing geometry must not invalidate text/page-level evidence. Anchors must remain resolvable for as long as the accepted content retention policy requires. Exact relational cardinalities remain deferred. Unsafe provider metadata must not be copied wholesale.

## Evidence categories

Conceptual evidence categories include:

- Source-page evidence.
- Source-region evidence.
- Source-text-span evidence.
- SPR-node evidence.
- SPR-observation evidence.
- Asset evidence.
- Recovery-selection evidence.
- Transformation warning evidence.
- Manual/import/backfill evidence, if later supported.

Exact enum spelling remains deferred. Generated M6 answer content is not source evidence.

## Asset options

### Option A — Direct storage URI on content node

A direct storage URI on a content node is simple, but leaks storage mechanics and weakens lifecycle/provenance boundaries.

### Option B — Asset entity referenced by content nodes

An Asset entity referenced by content nodes provides durable identity, source linkage, storage reference and metadata.

### Option C — Asset plus rendition model

Asset is logical identity; one or more renditions/artifacts represent original, cropped, thumbnail, rendered table, OCR preview or derived display forms.

### Option D — Embedded bytes/provider metadata

Embedded bytes/provider metadata are rejected as the target architecture. Current BookImage is compatibility evidence only.

## Accepted asset decision

M4 accepts a minimal logical Asset identity with optional rendition references.

### Asset role

Asset represents content-visible or evidence-relevant non-text material such as image, figure, page crop, rendered table, original embedded object, formula rendering, thumbnail/preview or other supported media. Exact asset-type enum remains deferred.

### Minimum asset identity

An asset must conceptually identify or reference Document, content version where content-visible, source file, source page/region, logical asset identity, media/type/role, storage reference or artifact reference, MIME/media type, checksum, byte size when known, dimensions when known, recovery/degraded/missing state, provenance/evidence anchors and optional caption/alt/description when accepted as content.

### Asset versus rendition

One logical asset may have zero or more stored renditions/artifacts, including original/source-derived rendition, cropped rendition, thumbnail, display rendition and rendered table image. Exact separate tables are deferred. Storage reference is not canonical content identity. Changing a rendition does not change content node identity unless accepted content semantics change. Derived renditions are rebuildable. Checksums/version identity are required for deterministic reference.

### Content-node association

Content nodes refer to logical Asset identity, not provider JSON or raw bytes. A node may own one primary asset, reference multiple assets, reference no asset when unavailable/degraded, and retain an evidence anchor even when rendition is missing. Exact cardinality remains deferred.

## Tables

A table is primarily Structured Content, not merely an image. Table structure belongs to the content model defined under ADR-003. An optional rendered table image may be represented as an Asset/rendition. Source-region evidence must link the table to source evidence. Missing rendered asset must not erase table structure. Image-only fallback may be retained as degraded content when structured table extraction is unavailable. Provider-native table payloads remain Raw Result/SPR evidence. This ADR does not finalize cell schema.

## Asset storage boundary

Bytes/renditions belong in the storage layer or storage-backed artifact system. Structured Content stores logical identity and references. Large binary payloads should not be embedded directly in content nodes. The relational database may contain compact metadata but is not required to contain all bytes. Object/file storage provider selection remains deferred. Storage reference changes must preserve logical asset identity and checksum traceability. Signed URLs and delivery behavior are M5/API concerns. Projection must identify asset version/reference without making storage URI canonical identity.

## Recovery and missing assets

A missing asset does not automatically invalidate the entire content version. The affected node/asset may be marked degraded or projection-ineligible. Source/evidence link must remain. A content version may be accepted with missing/degraded assets only under an explicit acceptance policy. Invalid checksums or unresolved required assets may block acceptance when policy requires. M5 later decides user-facing placeholders/presentation.

## Retention and deletion principles

Source, Raw Result, SPR, ProcessingRun, content version, evidence anchors, logical asset and rendition retention are related but distinct policies. Deleting a rendition must not erase logical asset/evidence identity. Deleting an unselected candidate must not affect current accepted content. Deleting accepted content must follow ADR-002 safe selection/deletion rules. Evidence required by accepted content must not be silently deleted. Deleting a SourceFile while accepted content still depends on it requires an explicit policy. Projection/cache artifacts are derived and may be invalidated/rebuilt. Exact retention periods, legal hold, cascade and tombstone rules remain D4.

## Error and diagnostic handling

ProcessingRun stores a safe structured error category/summary, not necessarily full provider payload. Detailed provider errors remain in Raw Result/log/artifact where appropriate. Content evidence anchors may reference relevant warning/diagnostic IDs. Secrets, credentials and unsafe provider metadata must not be copied. User-facing error phrasing remains M5/API scope. Diagnostics are not canonical document content.

## Consequences

Positive consequences include durable end-to-end traceability, rebuild/retry auditability, a bounded ProcessingRun model, evidence without full Observation duplication, provider independence, future citation support, asset lifecycle separation, table structure preserved independently of rendered image, projection-ready asset references and clear deletion dependencies.

Costs include new run/provenance/asset persistence, evidence-anchor resolution complexity, storage-reference lifecycle work, retention coordination, more integration tests, asset checksum/rendition management and backfill complexity.

Neutral consequences are that exact physical schema remains open, current BookImage/legacy entities remain compatibility paths, there is no Reader cutover, and D4 still decides migration/deletion/projection details.

## Rejected alternatives

The following are rejected as primary architecture:

- No durable run identity at all.
- Rich orchestration ledger in minimum M4.
- Latest run automatically becoming current content.
- Full durable Observation table for every SPR observation.
- Provider-native Observation rows as canonical evidence.
- Copying entire Raw Result/SPR into Structured Content rows.
- Content nodes storing raw provider payload.
- Direct storage URI as logical asset identity.
- Bytes embedded directly in core content nodes.
- BookImage as the target canonical asset model.
- Table-as-image-only architecture.
- Generated M6 output as source evidence.
- Deleting evidence because a projection was regenerated.
- Implementing Reader delivery in this ADR.

## Normative invariants

1. ProcessingRun is processing provenance, not document content.
2. Run success does not imply content acceptance.
3. Latest successful run is not automatically current.
4. Retry/rebuild preserves prior run history.
5. Accepted content retains resolvable source and processing lineage.
6. Raw Processing Result remains provider-specific evidence.
7. SPR remains provider-independent but noncanonical.
8. Full provider payloads are not copied into Structured Content.
9. A full durable Observation table is not required for minimum M4.
10. Evidence is not discarded merely because Observation rows are not created.
11. Evidence anchors resolve content back to stable source/SPR evidence.
12. Provider-native IDs are provenance inputs, not content business identity.
13. Logical asset identity is distinct from storage location.
14. Content nodes reference logical assets, not raw bytes.
15. Derived renditions are rebuildable and noncanonical.
16. Table structure is content even when rendered images exist.
17. Missing assets do not fabricate replacement semantic content.
18. Evidence required by accepted content is not silently deleted.
19. Generated M6 intelligence is not source evidence.
20. Implementation remains unauthorized by this ADR alone.

## Deferred decisions

Deferred decisions include exact ProcessingRun table/class, exact run status enum, detailed attempt/stage/event model, cost/metrics telemetry, exact provenance columns, exact evidence-anchor tables/cardinality, selective Observation persistence trigger, evidence query API, exact asset/rendition tables, storage provider, object key conventions, checksum algorithms, table-cell schema, caption/alt authoring policy, content acceptance policy for degraded/missing assets, retention periods, legal hold, deletion/cascade/tombstone, backfill/migration, projection DTO, signed URL/delivery API, Reader cutover, M6 generated-content provenance schema and M7 archive metadata extensions.

## Implementation guidance — non-normative and not authorized

Illustrative future components may include a ProcessingRun repository/model, ProvenanceReference, EvidenceAnchor, Asset, AssetRendition, EvidenceResolver, AssetResolver and run/content lineage validator. These names are illustrative only. This ADR includes no code, no schema and no implementation authorization.

## Validation and future evidence expectations

Later implementation must demonstrate that one Document may have multiple ProcessingRuns; run success does not update accepted/current selection automatically; retry creates traceable lineage; content version resolves to source/raw/SPR/run/transformer identity; node evidence resolves to source page/region or stable SPR evidence; absence of full Observation rows does not lose evidence traceability; duplicate observations are not copied unnecessarily; provider payloads remain outside core content; asset logical identity survives storage-reference changes; checksum mismatch is detected; missing rendition preserves asset/evidence identity; table structure survives missing rendered image; deletion cannot remove evidence required by accepted content; and the current Reader route remains unchanged until separately authorized.

These are future evidence expectations and are not claims that tests already pass.

## Relationship to other decisions

### ADR-002

This ADR conforms to immutable versions, explicit accepted/current selection, atomic acceptance and no latest-run-wins behavior.

### ADR-003

This ADR attaches provenance, evidence and assets to content version, content page, content node, recovery state and deterministic transformation lineage. It does not redefine node identity or hierarchy.

### D4

D4 will decide projection DTO/cache, Reader Content Stream role, legacy migration, backfill/rebuild operational strategy and deletion/retention details. D4 must preserve evidence and asset dependencies accepted here.

## References

- [Documentation governance](../../project/document-governance.md)
- [Roadmap v3 decision](../../roadmap/roadmap-v3-decision.md)
- [Roadmap](../../roadmap/roadmap.md)
- [M2](../../milestones/M2.md)
- [M3](../../milestones/M3.md)
- [M4](../../milestones/M4.md)
- [M5](../../milestones/M5.md)
- [M6](../../milestones/M6.md)
- [M7](../../milestones/M7.md)
- [ADR-002](ADR-002-structured-content-lifecycle-and-selection.md)
- [ADR-003](ADR-003-structured-content-shape-and-transformation.md)
- [Canonical data flow](../canonical-data-flow.md)
- [Document core information model](../document-core-information-model.md)
- [Structured-content architecture](../document-core-structured-content-architecture.md)
- [Processing contract](../document-processing-contract.md)
- [Persistence processing foundation](../persistence-processing-foundation.md)
- [Recovery-presentation architecture](../recovery-presentation-architecture.md)
- [SPR contract](../../contracts/structured-processing-result-v1.md)
- [Reader Content Stream contract](../../contracts/reader-content-stream-v2.md)
- [Mixed recovery ADR](../../adr/ADR-0001-mixed-multi-page-recovery-policy.md)
- [Service-boundaries ADR](ADR-001-service-boundaries.md)
