# M4 → M5 Handoff Package

## Metadata

| Field | Value |
|---|---|
| Document Type | Milestone Handoff Package |
| Date | 2026-07-24 |
| Upstream milestone | M4 — Structured Content / Structured Document Foundation |
| Downstream milestone | M5 — Reader MVP |
| Status effect | None; this handoff does not start M5 and does not complete M4 |

## Purpose

This package gives M5 an explicit, reviewed input boundary from M4. It is an M4 deliverable and not an authorization to implement M5, cut over Reader routes, execute migration/backfill, delete legacy rows, or claim production/commercial readiness.

## Upstream Milestone

M4 provides durable Structured Content candidate contracts, explicit selection/current-content identity, ProcessingRun provenance, evidence/asset/recovery anchors, deterministic Structured Document assembly, and derived Reader Content Stream v2 projection.

## Downstream Milestone

M5 is Planned Reader MVP work. It may use this handoff to plan Reader projection consumption, Reader API minimum, content granularity, navigation/location identity, Recovery Presentation, large-document delivery, image/table presentation, and compatibility/cutover strategy.

## Canonical Content Boundary

M5 canonical source is:

explicit selected StructuredContentCandidate
→ StructuredDocument
→ derived Reader projection

M5 MUST NOT treat as canonical: provider JSON; Raw Processing Result payload; SPR payload; MineruResult; ContentBlock; PdfPage; BookImage; Reader v2 serialization. Legacy objects may only be used through explicit compatibility/migration paths.

## Selected/Current Content Identity

Current content is the explicit zero-or-one Structured Content selection for a document. Candidate creation does not auto-select. Projection services must require explicit selection and must not infer latest.

## Structured Content Contract

StructuredContentCandidate contains schema identity/version, document/candidate/lineage identity, candidate recovery summary, pages, nodes, evidence refs, assets, warnings, extension metadata, transformer/policy refs, ProcessingRun ref, Raw Result ref, and SPR ref. Pages preserve page order and roots; nodes preserve page, parent, sibling order, type, text, attributes, source locations, evidence, asset refs, warnings, recovery state, and safe extensions.

## Structured Document Contract

StructuredDocument is a deterministic, derived, in-memory view of exactly one validated StructuredContentCandidate. It preserves document identity, source candidate identity/version/lineage, assembly policy version, source ProcessingRun/Raw Result/SPR refs, pages, node views, child refs, traversal indexes, page reading order, and document reading order.

## Assembly Boundary

Assembly validates candidate input, supported schema version, candidate contract, page roots, parent/child hierarchy, no cycles, no duplicate traversal, no cross-page traversal, and reachability from page roots. It does not mutate or persist.

## Projection Boundary

Projection consumes StructuredDocument plus source candidate and emits Reader Content Stream v2 projection. Projection is derived, lossy, version-bound, rebuildable, noncanonical, and not persisted by M4.

## Reader Content Stream v2 Compatibility

Reader Content Stream v2 is the initial compatibility projection. S4-DEC-005 sets semantic parity with classified intentional differences, not universal byte-identical equivalence. Known losses include list structure, table structure, header/footer/footnote, unsupported typed semantics, and recovery/evidence facts not fully expressible in a text stream.

## Service Boundary

The reusable service is `build_selected_document_projection(...)`. It guarantees explicit selection lookup, no latest fallback, no auto-selection, selected candidate reconstruction, document/candidate mismatch protection, deterministic assembly, deterministic projection, no mutation, and no projection persistence. It is not the final M5 Reader service/API.

## Page / Heading / Node Navigation Foundations

M4 provides document identity, page identity/order, node identity/order, hierarchy through parent/child refs, headings with levels, page-local reading order, document reading order, and source anchors. No first-class section DTO currently exists. M5 must decide whether heading-derived navigation is sufficient or whether a richer section projection/view is required.

## Asset / Image / Table References

M4 provides logical AssetReference, table rendered asset refs, figure rendered asset refs, compatible image marker identifiers, evidence refs, captions/alt text where available, asset recovery state, and unsafe/missing asset degradation. M4 does not fabricate assets. M5 owns presentation and asset delivery behavior.

## Recovery Facts

M4 hands off complete, degraded/partial, unavailable, no usable semantic content, warnings, and missing/degraded asset facts. M5 must map these facts to user-facing Recovery Presentation and must not expose raw provider diagnostics directly.

## Provenance

M4 provenance links Document/SourceFile context to ProcessingRun, Raw Result ref, SPR ref, candidate evidence, Structured Document source refs, and projection source anchors.

## Evidence Anchors

Evidence anchors include source file refs, source page indexes, source locations/bounding boxes/spans, raw result refs, SPR refs, SPR node/observation/evidence refs, warning refs, content node refs, asset refs, and projection entry/loss source refs.

## ProcessingRun Linkage

ProcessingRun is durable in M4 and linked to candidates through processing_run_ref plus raw_result_ref and structured_processing_result_ref. M5 may use this for provenance/status linkage but must not treat ProcessingRun payloads as canonical Reader content.

## Legacy Compatibility Rules

Current legacy Reader remains active. MineruResult, ContentBlock, PdfPage, and BookImage are retained. Semantic parity evidence exists for Reader Content Stream v2 projection. Migration/deprecation requires explicit later authorization. No destructive migration happened in M4.

## Migration / Backfill Constraints

S4-DEC-008 prohibits destructive migration, backfill execution, legacy deletion, route deprecation, and Reader cutover in M4. Future migration/backfill must be separately authorized, additive/non-destructive until evidence justifies otherwise, idempotent, candidate/version explicit, dry-run/comparison capable, and non-auto-promoting.

DEC-019 disposition: OPEN BUT NONBLOCKING FOR M4 / REQUIRED BEFORE ACTUAL MIGRATION EXECUTION.

## Observation Posture

S4-DEC-007 confirms no full durable Observation graph is required for M4. Observations remain SPR/evidence/source/projection-anchor facts. Durable Observation rows may be reconsidered later only for evidence-backed query, audit, lifecycle, indexing, or product requirements.

## Versioning / Rebuild Semantics

Structured Content, Structured Document assembly, and projection are versioned. Projection is rebuildable from selected candidate plus policy. If a cache is introduced later, it must be version-keyed, invalidatable, rebuildable, and noncanonical.

## Error Semantics

M5 should preserve bounded errors: no selected content, selected candidate/document mismatch, invalid candidate, unsupported schema/policy versions, projection input mismatch, unsafe asset omission/degradation, and recovery/loss reporting.

## Determinism Guarantees

M4 evidence supports deterministic Structured Content serialization, deterministic SPR transformation for accepted fixtures, stable page/node order, deterministic Structured Document assembly, deterministic Reader v2 projection, repeatable selected-candidate service output, and deterministic rollback/reselection behavior.

Scale evidence covers 100 pages / approximately 10,000 nodes/entries as regression evidence only. It is not an SLA, maximum supported document size, throughput promise, or memory guarantee. DEC-020 is explicitly deferred to M5 / production readiness and is nonblocking for M4.

## Known Limitations

Known limitations are no first-class section DTO, no standalone validator-resolvable rendition collection, Reader Content Stream v2 lossiness, no projection cache, no Reader route cutover, no migration/backfill execution, no product-level deletion semantics, and no production SLO/batch-size policy.

## Deferred Items

Deferred items include DEC-019 execution detail before actual migration/backfill, DEC-020 production SLOs/batch sizes, richer section/navigation view if needed, richer image/table rendition/delivery behavior, projection cache if justified, Reader adapter/cutover, migration/backfill/deprecation execution, product retention/deletion semantics, and final retention/privacy/security policy.

## M5 Must Not Do

M5 must not treat provider JSON, Raw Processing Result payloads, SPR payloads, legacy tables, or Reader v2 serialization as canonical content. It must not implement hidden latest selection, auto-selection, destructive migration/backfill, Reader cutover, or production/commercial readiness claims without separate authorization.

## M5 May Build On

M5 may build on explicit selected candidate identity, candidate reconstruction, Structured Document assembly, derived projection, Reader v2 compatibility semantics, navigation foundations, source anchors, evidence/provenance refs, ProcessingRun linkage, recovery facts, logical asset/table refs, and documented legacy parity evidence.

## Recommended First M5 Planning Decisions

Recommended first M5 planning decisions are Reader projection consumption contract, Reader API minimum, content granularity, navigation/location identity, Recovery Presentation mapping, large-document delivery strategy, image/table presentation behavior, and compatibility/cutover strategy.

## Handoff Acceptance Conditions

M5 planning should accept this handoff only if it preserves the canonical boundary, requires explicit selection, treats projection as derived/noncanonical, respects legacy compatibility rules, carries recovery/evidence/provenance facts forward, and keeps deferred production/migration decisions explicit.

## Authorization Boundary

This handoff does not change M4 status, does not start M5, does not authorize Reader cutover, does not authorize migration/backfill, does not authorize legacy deletion/deprecation, and does not claim production or commercial readiness.
