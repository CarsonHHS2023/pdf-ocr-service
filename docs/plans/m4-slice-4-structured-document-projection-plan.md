# M4 Slice 4 — Structured Document Assembly and Projection Boundary Plan

## Metadata

| Field | Value |
|---|---|
| Document Type | Implementation Plan |
| Status | Proposed |
| Milestone | M4 — Structured Content / Structured Document Foundation |
| Milestone Status | Unchanged — In Progress |
| Normative | No |
| Implementation Authorized | No |
| Date | 2026-07-23 |
| Scope | Planning only for Structured Document assembly and derived projection boundary |
| Related Governance | [Document Governance](../project/document-governance.md) |
| Related Roadmap | [Roadmap](../roadmap/roadmap.md), [Roadmap v3 Decision](../roadmap/roadmap-v3-decision.md) |
| Related ADRs | [ADR-002](../architecture/adr/ADR-002-structured-content-lifecycle-and-selection.md), [ADR-003](../architecture/adr/ADR-003-structured-content-shape-and-transformation.md), [ADR-004](../architecture/adr/ADR-004-provenance-evidence-assets-and-processing-runs.md), [ADR-005](../architecture/adr/ADR-005-projection-compatibility-migration-and-retention.md) |
| Upstream Plans/Reviews | [Slice 2 Plan](m4-slice-2-structured-content-persistence-plan.md), [Slice 3 Plan](m4-slice-3-spr-to-structured-content-transformation-plan.md), [Slice 2 Review](../reviews/m4-slice-2-completion-review.md), [Slice 3 Review](../reviews/m4-slice-3-completion-review.md) |

## Executive Summary

M4 Slice 4 should define an application-independent Structured Document view assembled deterministically from exactly one validated `StructuredContentCandidate`. The Structured Document is an assembled canonical view over canonical selected/candidate Structured Content, not a new independently persisted canonical store. The recommended posture is in-memory deterministic assembly with optional derived projection caching only when later evidence justifies it.

The initial projection should be a Reader Content Stream Protocol v2 compatibility projection. It is derived, version-bound, lossy where the legacy text stream cannot express richer content, safe to delete and rebuild, and must never become canonical content. M5 may later add the Reader adapter and route cutover; this plan does not authorize Reader implementation, endpoint changes, schema changes, migrations, backfill, retention execution, or M5 work.

## Governance and Architectural Basis

- Documentation governance separates accepted ADR/milestone authority from advisory plans and point-in-time reviews; this plan is Proposed and non-normative.
- Roadmap v3 places M4 before M5: `Structured Processing Result → Structured Content / Structured Document → projection boundary`, then M5 Reader MVP.
- M4 remains In Progress and includes Structured Document assembly, projection boundary, legacy migration/deprecation decisions, ProcessingRun/Observation decisions, deterministic tests, and M5 handoff.
- M5 remains Planned and must consume M4 content/projection without treating provider JSON, Raw Result, SPR, `MineruResult`, `ContentBlock`, `PdfPage`, `BookImage`, or Reader serialization as canonical.
- ADR-002 requires immutable candidates and explicit selected/current content.
- ADR-003 defines candidate pages, nodes, hierarchy, order, evidence/assets, recovery, and validated SPR transformation boundaries.
- ADR-004 keeps provenance/evidence bounded and currently recommends no full durable Observation graph initially.
- ADR-005 controls this slice: projection is derived, version-bound, rebuildable, optional-cacheable, and Reader Content Stream v2 compatibility is presentation compatibility only.

## Baseline

The inspected branch was `work` at `1d3ef1e1511d632561cb48276d680b834e27704c`, whose local history contains the required M4 Slice 3 completion review merge and preceding Slice 3, Slice 2, Slice 1, and ADR PRs #119-#140. The working tree was clean at start with no staged or untracked files. No remote URL was configured in this local checkout, but the local branch history reflects latest merged main through PR #140.

## Current State

### Structured Content foundation

The current code defines frozen in-memory candidate dataclasses with schema id/version, document/candidate/lineage identity, pages, nodes, evidence, assets, warnings, recovery summary, transformer/policy refs, processing run refs, raw-result refs, and SPR refs. It also provides validation, deterministic serialization, relational persistence/reconstruction, repository idempotency/conflict behavior, and explicit selection repository/service behavior.

### Slice 3 transformer

The current transformer validates SPR input, maps supported SPR node types to Structured Content node types, preserves page/node identity, hierarchy, sibling order, tables, assets, captions, formulas, evidence, warnings, recovery, and provenance, then validates the candidate. It performs no persistence, selection, Reader work, provider calls, file IO, media fetching, or rendering.

### Current Reader compatibility paths

The current Reader-facing routes still assemble book content from legacy storage. `/api/v1/books/{book_id}/content` reads `MineruResult.result_json` for PDFs and serializes a plain text stream with image markers; TXT books read a processed text file. The accepted Reader Content Stream v2 contract is plain text lines with paragraph lines, heading marker lines, and image marker lines only. Older `/api/pdf/book-text/{book_id}` and `/api/pdf/book-images/{book_id}` expose `ContentBlock` and `BookImage` compatibility data. `PdfPage` stores page images and OCR raw JSON; `MineruResult` stores cross-page post-processed JSON. These are compatibility and migration sources, not M4 canonical content.

## Problem Statement

M4 has selected/candidate Structured Content and deterministic SPR-to-candidate transformation, but it still needs a clear application-independent document view and a derived projection boundary. Without Slice 4 planning, Reader compatibility could leak into canonical models, projection caches could become accidental source of truth, selection lookup could be hidden inside assembly, version identity could be lost, or legacy tables could remain indefinitely authoritative.

## Scope

This plan defines Structured Document assembly semantics, projection semantics, initial Reader Content Stream v2 compatibility mapping, cache/invalidation posture, selected/current behavior, legacy shadow/parity strategy, Observation and migration decision paths, test strategy, risks, readiness criteria, and proposed implementation sub-slices.

## Explicit Non-Goals

This plan excludes Reader UI, Reader endpoint cutover, Speed Reading, Notes/highlights product, AI Tutor, summaries, flashcards, mind maps, RAG, semantic search, Smart Archive, provider execution, OCR changes, Raw Result changes, SPR changes, candidate transformation changes, automatic selection, production deployment, destructive migration, backfill execution, retention execution, M4 completion, M5 start, schema/migration changes, repository changes, selection changes, Reader route/service changes, and API/orchestration implementation.

## Terminology

- `StructuredContentCandidate`: durable/versioned immutable candidate content and lifecycle/persistence concern.
- `Structured Document`: deterministic application-independent assembled document view over one candidate/version.
- `Projection`: derived noncanonical representation from one Structured Document, optimized for compatibility or consumption.
- `Reader adapter`: M5 presentation/API compatibility layer that may consume projection but cannot redefine canonical content.

## Canonical Data Flow

```text
selected/candidate Structured Content
→ Structured Document
→ derived projection
→ future Reader-compatible adapter
```

Candidate rebuild and projection rebuild are distinct. Candidate rebuild maps SPR to a new candidate and does not auto-promote. Projection rebuild regenerates a derived artifact from the same immutable source candidate and never creates or selects a candidate.

## Structured Content vs Structured Document vs Projection

| Concept | Canonical status | Persistence posture | Version boundary | Must not be |
|---|---|---|---|---|
| StructuredContentCandidate | Canonical candidate content once persisted and valid | Durable immutable candidate graph | Candidate id/schema/version/lineage | Reader stream, provider result, SPR |
| Structured Document | Assembled canonical view over one canonical candidate | In-memory view recommended; no independent canonical table | Source candidate id plus assembly version | Second mutable canonical store, Reader DTO |
| Projection | Noncanonical derived compatibility/consumption representation | On demand initially; optional derived cache later | Source candidate + assembly/projection versions | Selected content, evidence authority, canonical document |
| Reader adapter | Presentation/API compatibility layer | M5 concern | Projection version/API contract | Canonical model or migration authority |

## Structured Document Definition

A Structured Document is an application-independent, deterministic, version-bound assembled view of exactly one `StructuredContentCandidate`. It organizes candidate pages, root nodes, hierarchical nodes, tables, figures/assets, captions, formulas, evidence references, warnings, and recovery facts into a document traversal suitable for downstream projection. It is not provider output, not Raw Result, not SPR, not `MineruResult`, not `ContentBlock`, not Reader Content Stream serialization, and not a mutable database snapshot.

Structured Document itself should be described as an assembled canonical view over canonical content, not as newly derived content with independent authority. Its authority comes entirely from its source candidate and the documented deterministic assembly policy.

## Persistence Posture

### Option A — Pure in-memory Structured Document

Pros: no duplicate durable state; simplest consistency and retention model; aligns with immutable candidates and explicit selection; avoids schema churn. Cons: repeated assembly cost; no persisted artifact for expensive compatibility reads.

### Option B — Persisted Structured Document snapshot

Pros: faster reads and easier direct inspection. Cons: duplicates canonical content; requires invalidation, migration, retention, drift detection, and cross-version consistency; risks becoming a second canonical store contrary to ADR-002/005.

### Option C — In-memory canonical assembly + optional derived cache

Pros: keeps candidate as durable canonical store; keeps assembly deterministic; permits bounded cache if scale evidence later requires it; aligns with ADR-005 optional caching. Cons: requires careful cache key/versioning and tests proving deletion/rebuild safety.

**Recommendation:** choose Option C. Structured Document is assembled in memory from one candidate; only projections may later use a derived, noncanonical cache. Slice 4 should not add a canonical Structured Document table or projection table. Any durable projection cache must be a separate later implementation decision with explicit noncanonical metadata and safe deletion/rebuild behavior.

## Input Contract

The pure assembler boundary should be:

```python
assemble_structured_document(candidate: StructuredContentCandidate, policy: StructuredDocumentAssemblyPolicy) -> StructuredDocument
```

The service orchestration boundary should be separate:

```python
load_selected_structured_document(document_id, selection_repository, candidate_repository, policy) -> StructuredDocument
```

The pure assembler must not query repositories, inspect current time, choose latest candidate, select content, read files, fetch assets, call providers, or mutate input. It receives one already-loaded candidate and a versioned policy. The service may perform selected/current lookup and cache lookup, but it must pass the resolved candidate explicitly into the pure assembler.

## Selected/Current Relationship

- A Structured Document represents exactly one candidate/version.
- Selected/current lookup happens outside pure assembly.
- There is no implicit latest candidate and no automatic selection.
- Candidate id, candidate schema version, document id, lineage key, transformer/policy refs, processing run ref, raw-result ref, and SPR ref remain visible in source provenance.
- Changing selection from Candidate A to Candidate B changes the current source view; A remains reconstructable by candidate id.
- Projections must never combine nodes/assets/evidence from different candidates.
- If no selection exists, the service returns a bounded `no_selected_candidate` error or equivalent; the assembler is not called.
- If the selected candidate is degraded or contains no-usable pages allowed by validation, the Structured Document preserves those states.
- Missing/degraded assets remain logical degraded references; assembly does not fabricate or fetch assets.

## Structured Document Shape

Minimum view fields should include: document identity; source candidate identity/schema/lineage; assembly schema/version; source provenance refs; ordered pages; document reading order; page-local reading order; root node refs; hierarchical node wrappers that point to original candidate nodes; derived headings/section view if accepted; table wrappers preserving structured cells; figure/asset wrappers preserving logical asset refs; captions; formulas; evidence refs; warning refs; document/page/node recovery; and extension metadata. Use current Structured Content dataclasses wherever possible, with lightweight view wrappers for traversal and derived indexes rather than duplicating the entire candidate model.

## Page Assembly

Pages are ordered by candidate `page_order`, then `source_page_index`, then `page_id` as a defensive deterministic tie-breaker even though validation rejects duplicate page order. Each page view preserves page id, source page index, page label, dimensions, rotation, coordinate frame, recovery state, evidence ids, warning ids, root node ids, and page-local ordered traversal. Empty pages and no-usable-semantic-content pages remain present with empty page-local reading order; degraded/unavailable pages are not silently omitted.

## Reading Order

Document reading order is assembled by page order, then each page's `root_node_ids` in stored order, then depth-first child traversal ordered by `sibling_order` and stable node id tie-breakers. Existing candidate page/root/sibling ordering is authoritative. Geometry must not be reinterpreted to infer order when candidate order exists. Tables, figures, captions, formulas, headers, footers, and footnotes appear where their candidate nodes appear. Projection or Reader presentation may later hide/reorder presentation-only items, but Structured Document preserves canonical assembled order.

## Sections and Headings

Slice 4 should expose both raw heading nodes and a derived section view. The section view is noncanonical derived navigation metadata in the Structured Document, not new semantic content. It must be deterministic and based only on explicit `HeadingAttributes.level` on heading nodes. It must not use LLM inference, font-size guessing, semantic topic clustering, provider heuristics, or text rewriting.

Policy: heading levels above 6 may be preserved as raw heading nodes and either clamped only in Reader projection or excluded from section navigation with a warning; skipped levels create nested sections under the nearest prior lower level; headings without explicit levels default only if candidate transformation already created a level; multiple titles are just headings in order; page-spanning sections are ranges from heading to before next appropriate heading; headingless documents have no section view but still have page/node reading order; unknown nodes do not start sections.

## Hierarchy

The Structured Document tree/walk must guarantee no cycles, no dangling refs, deterministic parent/child order, page ownership retention, source candidate refs on every assembled node, list hierarchy preservation, explicit captions, and structured table objects. The assembler should rely on candidate validation and add assembly-specific invariant checks. Nodes must not be duplicated merely to satisfy Reader shape; projections may create flattened entries separately.

## Tables

Structured Document exposes table nodes as structured objects with row/column dimensions, ordered cells, row/column spans, optional cell text, header metadata in extensions, caption links where present, rendered asset ref if present, evidence refs, asset refs, and recovery state. It must not flatten tables into canonical text. The Reader compatibility projection may derive a text-friendly summary or image marker where legacy v2 cannot carry cells, and that loss must be explicit.

## Figures and Assets

Structured Document exposes figure nodes and logical assets with asset id, role, availability/degraded state, source location, media type, checksum, byte size, dimensions, rendition ref ids, caption/alt/description fields, evidence refs, and warning refs. Assembly does not fetch assets, render crops, dereference storage, or generate images. Missing/degraded assets remain explicit degradation facts.

## Rendition Limitation

Slice 3 found that `StructuredContentCandidate` has `AssetReference.rendition_refs` but no top-level validator-resolvable standalone rendition collection. Slice 4 should continue treating rendition availability as logical metadata, introduce no model change, and record S4-DEC-006 for a future model/cache decision before richer image/table projection. This does not block text-centric Reader Content Stream v2 compatibility because v2 supports only image id markers, but it limits faithful image/table rendering until M5 or a later M4 decision defines asset serving/mapping.

## Evidence

Structured Document preserves existing evidence refs and source candidate anchors. It must not duplicate provider payloads or make observations durable by side effect. Projection entries may include compact evidence/node/page/asset refs back to Structured Document/candidate evidence, allowing future Notes/highlights/citations/navigation without copying full evidence payloads or defining final M6 citation UX.

## Warnings and Recovery

Structured Document preserves document recovery summary, page recovery, node recovery, warnings, no-usable states, missing asset degradation, and unresolved associations. The assembler may produce new assembly warnings only for assembly-specific invariant issues such as inconsistent section derivation or unresolved optional view associations not already covered. It must not reinterpret transformation warnings or use `ProcessingRun.status` as content quality.

## Validation

Reuse Structured Content validation before assembly. Add a future pure Structured Document validator or assembler invariant checker for: exactly one source candidate/version; no dangling assembled refs; deterministic ordered traversal; no cross-version refs; all required asset/evidence refs resolve to source candidate collections where required; recovery summary consistency; section ranges valid; projection refs valid. Projection validation is separate and should validate projection-specific shape/version/lossiness metadata.

## Determinism

The same candidate plus same assembly schema/version/policy must yield identical Structured Document canonical comparison output. The same Structured Document plus same projection policy/version must yield identical projection. Determinism forbids timestamps, randomness, DB row order, environment-sensitive order, selection lookup inside pure assembly, asset fetching side effects, and nondeterministic map iteration. Even if the Structured Document is not persisted, tests should serialize its comparable view deterministically.

## Versioning

Use minimal version metadata: `structured_document_schema_version = 1`, `assembly_policy_version = 1`, and optional `assembly_implementation_ref` for diagnostics. Projection uses `projection_type` and `projection_schema_version`. Version bumps are required when assembly traversal, section policy, recovery summarization, evidence anchoring, or compatibility mapping changes in a way that can alter deterministic output or cache validity.

## Projection Definition

A projection is a derived, noncanonical, regenerable, version-bound representation from one Structured Document. It is safe to delete/rebuild and intended for downstream compatibility or consumption. It is not selected content, not the canonical document, not provider result, not Raw Result, not SPR, not `MineruResult`, not `ContentBlock`, and not a new evidence authority. Projection failure never changes candidate persistence or selection.

## Initial Projection Type

The minimum initial projection should be a Reader Content Stream v2 compatibility projection rather than a broad generic projection framework. The planned type is `reader_content_stream_v2` with `projection_schema_version = 1`. A small internal `StructuredDocumentProjection` envelope may hold common identity/version/lossiness metadata, but the only initial payload target should be the existing plain text v2 stream.

## Reader Content Stream v2 Compatibility

Reader Content Stream v2 is plain text with paragraph lines, heading marker lines `$#$#1` through `$#$#6`, and image marker lines `$%$%$%{image_id}$%$%$%`. It has no JSON blocks.

| Structured Document concept | Reader Content Stream v2 field/block | Compatibility rule |
|---|---|---|
| Document | `BookContentSchema.content` stream body | Adapter returns legacy content string; source candidate/version stays in projection metadata, not v2 text. |
| Page | No native field | Preserve ordering in stream; page anchors stay in projection metadata/parity fixtures. |
| Paragraph/text | Plain text line ending `\n` | Normalize internal line breaks according to v2 paragraph rules; do not rewrite semantics. |
| Heading level 1-6 | `$#$#{level}{text}\n` | Emit only explicit heading levels; preserve raw heading in metadata. |
| Heading outside 1-6 | Plain text or compatibility warning | Do not invent a level; record lossiness. |
| List/list item | Plain text lines in traversal order | Preserve text order; list structure is lost in v2. |
| Table | Optional image marker if rendered asset id maps to legacy image id; otherwise text-friendly rows if approved | Rich cells/spans lost; Structured Document remains authoritative. |
| Figure/image | `$%$%$%{image_id}$%$%$%` when compatible id is available | Do not fabricate image ids; missing/degraded assets produce metadata warning and may omit marker. |
| Caption | Plain text line at candidate traversal position | Target links preserved only in projection metadata. |
| Formula | Plain text notation/text where available | Rendering/notation richness may be lost. |
| Header/footer/footnote | Plain text in candidate order unless projection policy excludes in M5 | M4 projection should preserve order; Reader UI can later decide display treatment. |
| Evidence | No native field | Compact refs in projection metadata only. |
| Warnings/recovery | No native field | Summary/refs in projection metadata; v2 text cannot express full state. |
| Ordering | Logical line order | Derived from Structured Document reading order. |

## Projection Lossiness

Allowed lossiness must be explicit: evidence refs are compact refs not payloads; page identity is metadata not text; table cells/spans may be simplified; list nesting may become ordered text; rich attrs/extensions may be omitted; recovery may be summarized; unsupported asset/rendition details may be omitted. Projection must not silently alter text semantics, mix candidate versions, fabricate assets, infer sections, become authoritative, or promise round-trip reconstruction.

## Projection Caching

Recommendation: no durable projection cache for initial Slice 4 implementation. Assemble and project on demand, with optional process-local cache only if tests reveal repeated cost and if cache identity includes full source/version/policy. Durable cache remains a later derived-cache decision. Conceptual durable key, if later accepted:

```text
(document_id, candidate_id, candidate_schema_version, structured_document_schema_version,
 assembly_policy_version, projection_type, projection_schema_version, projection_policy_version)
```

Never use `latest` or selected/current pointer alone as cache identity.

## Invalidation and Rebuild

Because candidates are immutable, invalidation should be key-based rather than mutable synchronization. A projection is stale or bypassed when selected candidate changes, assembly version changes, projection schema/policy changes, compatibility mapping changes, or cache metadata is missing/inconsistent. Projection rebuild from an immutable candidate regenerates the same derived projection for the same versions and must not create, mutate, select, or delete candidates.

## Selection Change Behavior

If Candidate A is selected, current service lookup returns Structured Document A and Projection A. If Candidate B is explicitly selected later, current lookup returns B; Projection A may remain historical/cacheable if retention allows, but it is no longer current. A remains reconstructable by id. No content is auto-promoted, mutated, or rebuilt as part of projection lookup.

## Service Boundary

Pure layer: `assemble_structured_document(candidate, assembly_policy)` and `project_structured_document(document, projection_policy)`. Service layer: load selected candidate, validate, assemble, project, consult optional cache, and return an adapter result. M5 layer: route/API adapter and Reader cutover. M4 Slice 4 planning must not finalize HTTP routes.

## Legacy Compatibility

| Legacy entity/path | Current role | Slice 4 classification | Future handling |
|---|---|---|---|
| `MineruResult.result_json` | PDF Reader content source for current route | Compatibility input and migration/parity source | Shadow compare; deprecated after M5 cutover evidence. |
| `ContentBlock` | Older text/table/image block storage and `/api/pdf/book-text` source | Transitional read path/migration source | Do not extend as canonical; parity/migration decision before M4 completion. |
| `PdfPage` | Page image/OCR raw JSON/status storage | Compatibility processing/page evidence | Do not use as Structured Document page truth; may inform legacy parity. |
| `BookImage` | Legacy binary image/table storage and image marker target | Compatibility asset serving source | Map only through explicit asset/projection adapter; not canonical asset model. |
| `/api/v1/books/{book_id}/content` | Current Reader content endpoint | Legacy route unchanged in M4 | M5 may adapt/cut over under explicit task/flag. |
| `/api/pdf/book-text`, `/api/pdf/book-images`, `/api/pdf/image` | Legacy page/content/image APIs | Transitional compatibility paths | Retain until deprecation policy and parity evidence exist. |
| Reader Content Stream v2 | Plain text presentation stream | Initial projection compatibility target | Noncanonical, lossy, rebuildable. |

## Shadow / Parity Migration

Phase 1: existing Reader routes continue unchanged while Structured Document/projection runs in tests/shadow fixtures. Phase 2: compare legacy Reader output to new projection and classify differences as required semantic parity, intentional richer content, intentional legacy loss, unsupported legacy feature, recovery difference, or ordering difference requiring investigation. Phase 3: M5 may read projection under explicit task/flag. Phase 4: legacy deprecation occurs only after evidence and approved migration policy. M4 Slice 4 does not authorize cutover.

## Observation Persistence Decision Path

ADR-004 recommends no full durable Observation graph initially. Current evidence anchors are sufficient for Structured Document and Reader v2 projection because candidate evidence refs can retain page/node/source/SPR refs without duplicating provider payloads. Slice 4 should include S4-DEC-007 to formally confirm retaining observations as SPR/evidence-only for M4 before Slice 4 implementation completion or immediately in Slice 4D. Do not add Observation ORM models in this plan.

## Legacy Migration Decision Path

M4 needs a migration/deprecation policy before completion. This belongs in Slice 4D after projection contract and shadow/parity fixtures expose compatibility gaps, and before M4 Completion Review. DEC-019 becomes required before any legacy backfill or migration execution. No migration/backfill is authorized by this plan.

## M4 Completion Path

1. Slice 4A — Structured Document contracts, assembly policy/version, pure assembler boundary, and validation contract.
2. Slice 4B — Deterministic Structured Document assembly for pages, hierarchy, reading order, sections, tables, assets, evidence, warnings, and recovery.
3. Slice 4C — Reader Content Stream v2 projection contract, lossiness metadata, deterministic projector, and versioning.
4. Slice 4D — Legacy shadow/parity compatibility verification plus Observation and legacy migration/deprecation decision records.
5. Slice 4E — Integrated verification through selected candidate lookup, assembly, projection, selection-change behavior, and scale regression.
6. M4 Completion Review.
7. M5 Handoff Package.

## Proposed Slice 4 Sub-Slices

| Slice | Purpose | Deliverables | Exclusions |
|---|---|---|---|
| 4A | Contracts | In-memory DTO plan/types, assembly policy, validation contract | No projection/Reader cutover. |
| 4B | Assembly | Deterministic page/tree/order/section/table/asset/evidence/recovery assembly | No persistence schema. |
| 4C | Projection | `reader_content_stream_v2` projection mapping, lossiness/version policy | No generic projection platform. |
| 4D | Shadow/parity | Legacy comparison fixtures/tests, Observation confirmation, migration sequencing decision | No destructive migration. |
| 4E | Integration | Selected candidate service orchestration tests, deterministic rebuild, selection change, scale regressions | No M5 routes. |

Listing these sub-slices is not implementation authorization; each requires its own reviewed task.

## Error Model

Plan bounded errors for: no selected candidate; selected candidate not found; selected candidate corrupt/invalid; candidate/document mismatch; unsupported candidate schema; unsupported assembly version; assembly invariant failure; unresolved required asset/evidence ref; unsupported projection type/version; projection invariant failure; missing compatible image id; cache key mismatch/stale cache; and legacy parity mismatch classification. Errors must be safe summaries and must not expose raw provider payloads.

## Evidence Anchors for Downstream Use

Structured Document nodes and projection entries should retain stable refs to document id, candidate id/schema/version, page id/source page index, node id, evidence id, asset id, warning id, and source provenance refs. These anchors support future M5 navigation and optional notes/highlights, and future M6 citations, without copying full evidence payloads.

## Scale and Regression Strategy

Use Slice 3 scale evidence as regression input, not SLA. Plan representative deterministic tests for 100 pages, 10,000 nodes, 1,000 table cells, and hundreds of assets/evidence refs where practical. DEC-020 remains nonblocking until production-readiness or M5 large-document delivery decisions set actual SLOs/batch sizes.

## Test Strategy

Structured Document tests: deterministic assembly; candidate-bound identity; page order; root/child traversal; no cycles/dangling refs; section derivation; headingless/skipped-level cases; tables; assets; captions; formulas; evidence; warnings/recovery; degraded/no-usable pages; missing assets.

Projection tests: deterministic output; version-bound identity; no canonical mutation; Reader v2 mapping; explicit lossiness; image markers; headings; paragraphs; tables; captions; formulas; recovery metadata.

Selection tests: selected Candidate A; switch to B; current assembly/projection switches to B; A remains reconstructable; no implicit promotion.

Compatibility tests: legacy Reader output vs projection with classified differences, without making legacy defects canonical.

Purity tests: assembler and projector are pure; service lookup is separate; no DB row order/current time/randomness/provider/file IO in pure layers.

## Schema / Persistence Impact

Slice 4 should require no durable schema for Structured Document and no canonical projection table. No Alembic migration is planned. Optional durable projection cache is deferred to a later derived-cache decision and must be noncanonical, version-keyed, safe to delete, and rebuildable. No Structured Content, selection, repository, ProcessingRun, SPR, or Reader schema changes are authorized here.

## Open Decisions

| ID | Decision | Options | Recommended direction | Required before |
|---|---|---|---|---|
| S4-DEC-001 | Structured Document persisted vs assembled | In-memory; persisted snapshot; in-memory with optional derived cache | In-memory assembly with optional derived projection cache | Slice 4A implementation |
| S4-DEC-002 | Section view | Raw headings only; derived section view; first-class persisted sections | Derived noncanonical section view from explicit heading levels | Slice 4B implementation |
| S4-DEC-003 | Projection DTO shape | Reader-only payload; generic envelope plus Reader payload; broad framework | Minimal envelope plus Reader v2 payload | Slice 4C implementation |
| S4-DEC-004 | Projection caching | None; process-local; durable derived cache | No durable cache initially; optional process-local only with full key | Slice 4E if cache added |
| S4-DEC-005 | Reader Content Stream v2 parity level | Byte-identical; semantic parity; classified differences | Semantic parity with classified intentional differences | Slice 4D implementation |
| S4-DEC-006 | Rendition limitation treatment | Ignore; logical metadata; model revision | Logical metadata now; future decision for richer rendition collection | M5 image/table cutover or richer projection |
| S4-DEC-007 | Observation persistence confirmation | Durable Observation graph; SPR/evidence-only; separate artifact | SPR/evidence-only for M4 with formal confirmation | Slice 4D / before M4 completion |
| S4-DEC-008 | Legacy migration sequencing | Inside Slice 4; immediately after Slice 4; M5-only | Slice 4D decision before M4 completion, execution later | M4 Completion Review |

DEC-019 remains important before legacy migration/backfill execution. DEC-020 remains nonblocking for Slice 4 planning and should not be silently closed.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Duplicate canonical state | Do not persist Structured Document as canonical; candidate remains durable authority. |
| Projection becomes authoritative | Mark projection derived/noncanonical/version-bound; tests prove rebuild/delete safety. |
| Reader compatibility leaks into canonical model | Keep Reader v2 mapping in projector/adapter only. |
| Version mixing | Require one candidate id/version per Structured Document and projection key. |
| Stale cache | Use complete versioned keys; prefer no durable cache initially. |
| Hierarchy drift | Reuse candidate validation and add assembly invariant checks. |
| Section over-inference | Use explicit heading levels only; no LLM/font/topic inference. |
| Legacy path becomes permanent | Add Slice 4D migration/deprecation decision deadline. |
| Asset/rendition mismatch | Preserve logical refs; defer standalone rendition model decision. |
| Migration before parity evidence | Require shadow/parity phases before cutover/backfill. |
| Selection hidden inside assembler | Keep lookup in service layer; pure assembler receives candidate. |
| Performance overclaiming | Treat scale tests as regression only until DEC-020/SLO decisions. |

## Implementation Readiness Criteria

Before Slice 4A implementation begins: Structured Document definition settled; persistence posture accepted; pure assembler boundary settled; source candidate/version identity settled; selected/current service boundary settled; page/reading-order/section/table/asset/evidence/recovery policies settled; projection definition and initial `reader_content_stream_v2` type settled; lossiness documented; version/cache/invalidation rules documented; legacy Reader source contract inspected; shadow/parity strategy documented; Observation persistence sequencing clear; no blocking plan findings remain.

## Readiness Decision

**READY WITH NONBLOCKING FINDINGS FOR SLICE 4 IMPLEMENTATION PLANNING / 4A.** Nonblocking findings are: durable projection cache should remain deferred unless evidence requires it; standalone rendition collection remains deferred; Observation persistence requires a formal confirmation decision before M4 completion; DEC-019 and DEC-020 remain open in their respective scopes.

## Milestone Status

M4 remains In Progress. M5 remains Planned. This plan does not mark M4 Complete, does not authorize Reader cutover, does not claim production-ready status, and does not begin M5.
