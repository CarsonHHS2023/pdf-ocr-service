# M4 Slice 4D — Legacy Compatibility and Remaining Decisions

## Metadata

| Field | Value |
|---|---|
| Document Type | Decision / Review |
| Approval Status | Proposed |
| Lifecycle Status | Active |
| Milestone | M4 — Structured Content / Structured Document Foundation |
| Milestone Status | In Progress |
| Date | 2026-07-24 |
| Scope | M4 Slice 4D legacy Reader parity verification, Observation persistence confirmation, and legacy migration/deprecation sequencing |
| Implementation Authorized | Tests and documentation only |
| Reader Cutover Authorized | No |
| Migration/Backfill Authorized | No |
| Related ADRs | ADR-002, ADR-003, ADR-004, ADR-005 |
| Related Plan | `docs/plans/m4-slice-4-structured-document-projection-plan.md` |

## Scope

This Slice 4D artifact records shadow/parity evidence between current legacy Reader Content Stream v2 behavior and the Slice 4C Structured Document Reader v2 projection. It also records the remaining M4 decisions S4-DEC-005, S4-DEC-007, and S4-DEC-008. This slice does not modify Reader routes/services, projection semantics, Structured Document semantics, ORM models, migrations, selected/current orchestration, or any production runtime path.

## Governance Basis

Documentation governance requires using accepted ADRs, milestone state, roadmap sequencing, and implementation evidence within their scopes rather than silently redefining released behavior. The Slice 4 plan keeps Structured Document assembly application-independent, keeps projection derived and noncanonical, reserves Reader route cutover for M5, and requires legacy compatibility and migration decisions before M4 completion. ADR-004 bounds provenance to retained evidence and compact anchors unless durable Observation rows are justified. ADR-005 makes projection compatibility presentation compatibility and forbids treating projection caches or legacy Reader serialization as canonical.

## Legacy Reader Characterization

Current `/api/v1/books/{book_id}/content` behavior is implemented by `app/routers/books.py`. For completed PDF books it loads the first `MineruResult` row for the book and serializes `result_json`; missing books, incomplete books, and missing PDF content return 404. TXT books read the processed text path through the book service. `_assemble_txt_from_mineru` parses JSON block lists and falls back to returning the raw string on parse failure. Legacy title blocks clamp heading levels to one through six `#` markers, strip content, omit empty headings, and append one newline internally before final `strip()`. Legacy text and toc blocks are stripped and omitted when empty. Legacy image/table blocks emit `$%$%$%{image_id}$%$%$%`; table continuation images emit an additional marker; captions are stripped and emitted after markers. Legacy serialization performs no evidence, recovery, table structure, header/footer/footnote, or durable Observation output.

Legacy `/api/pdf/book-text/{book_id}` returns `ContentBlock` text rows grouped by page with block index, content, confidence, and bbox. `/api/pdf/book-images/{book_id}` returns `BookImage` metadata. `/api/pdf/image/{image_id}` returns image metadata only in the inspected route. `ContentBlock`, `BookImage`, `PdfPage`, and `MineruResult` remain compatibility and migration evidence sources, not M4 canonical content.

## New Projection Characterization

Slice 4C projects exactly one assembled `StructuredDocument` and matching `StructuredContentCandidate` to `ReaderContentStreamV2Projection`. It validates source identity, produces deterministic entries and payload, preserves source node/page/asset/evidence refs in metadata, records projection losses for unexpressible structure/recovery/assets, strips text lines, joins stable `\n` separators, clamps heading markers, emits image markers only for compatible available assets, omits headers/footers/footnotes by policy, flattens list items, emits captions/formulas/unknown text as paragraph-compatible lines, and records recovery metadata outside the plain text payload. It does not query legacy tables or Reader routes.

## Parity Method

Test-only shadow fixtures invoke current legacy `_assemble_txt_from_mineru` directly and compare its payload with `StructuredContentCandidate -> assemble_structured_document(...) -> project_structured_document(...)`. The test-only `ReaderParityClassification` enum bounds each observed difference to: REQUIRED_SEMANTIC_PARITY, INTENTIONAL_RICHER_CANONICAL_SOURCE, INTENTIONAL_LEGACY_LOSS, UNSUPPORTED_LEGACY_FEATURE, RECOVERY_DIFFERENCE, or ORDERING_DIFFERENCE_REQUIRES_INVESTIGATION. The classification model is not production semantics.

## Parity Classification

Required semantic parity covers visible paragraph text, heading visible text, heading marker grammar, compatible image/table marker grammar, caption/formula visible text, deterministic `\n` line separators, and relative reading order. Byte-sensitive parity is limited to marker syntax, heading marker grammar, stable line separators, and absence of unsafe transient payload. Semantic parity covers ordering and visible content under documented lossiness. Additional evidence metadata, recovery metadata, source anchors, and intentionally omitted unsafe/transient assets are nonblocking differences.

## Parity Matrix

| Case | Legacy behavior | New projection | Classification | Blocking? | Evidence |
|---|---|---|---|---|---|
| Simple paragraph | stripped text line, no trailing newline | stripped paragraph entry, no trailing newline | REQUIRED_SEMANTIC_PARITY | No | parity test |
| Multiple paragraphs / whitespace | empty strings omitted; final payload stripped | empty entries omitted; final payload joined without trailing newline | REQUIRED_SEMANTIC_PARITY | No | parity test |
| h1/h2/h6/level >6/title | `#` grammar clamped 1-6 | same heading grammar helper | REQUIRED_SEMANTIC_PARITY | No | legacy characterization + projection tests |
| Empty heading | omitted | omitted | REQUIRED_SEMANTIC_PARITY | No | legacy characterization |
| Image with stable id | image marker line | compatible asset marker line | REQUIRED_SEMANTIC_PARITY | No | parity test |
| Image with transient/signed id | legacy would emit raw id if present | projection refuses unsafe marker and records asset loss | INTENTIONAL_RICHER_CANONICAL_SOURCE | No | parity test |
| Missing/unavailable image | no marker if no image id | no marker; asset loss metadata | RECOVERY_DIFFERENCE | No | parity test |
| Table rendered image | marker line and optional caption | marker line and caption when compatible asset exists | REQUIRED_SEMANTIC_PARITY | No | parity test |
| Table structure | no table structure in stream | structure dropped loss | INTENTIONAL_LEGACY_LOSS | No | parity test |
| Table continuation image | legacy has second marker | no canonical continuation unless represented as asset/node | UNSUPPORTED_LEGACY_FEATURE | No | characterization; future migration must map explicitly |
| Captions | stripped line after marker when present | caption node line in reading order | REQUIRED_SEMANTIC_PARITY | No | parity test |
| Lists | no dedicated legacy list grammar | list container omitted; list item text emitted | INTENTIONAL_LEGACY_LOSS | No | parity test |
| Nested lists | no durable structure in v2 | list item text emitted; nesting loss recorded | INTENTIONAL_LEGACY_LOSS | No | parity test |
| Formula | legacy text-compatible when represented as text | formula visible text emitted | REQUIRED_SEMANTIC_PARITY | No | parity test |
| Header/footer/footnote | no dedicated v2 grammar | omitted by policy with loss | UNSUPPORTED_LEGACY_FEATURE | No | parity test |
| Unknown/code/quote/reference/page number | no dedicated v2 grammar; text-like content can pass as text | unknown text emitted; unsupported typed semantics not invented | UNSUPPORTED_LEGACY_FEATURE | No | parity test + projection characterization |
| Recovery | absent from payload | recovery summary/loss metadata only | RECOVERY_DIFFERENCE | No | parity test |
| Evidence anchors | absent from payload | source/evidence refs preserved in metadata | INTENTIONAL_RICHER_CANONICAL_SOURCE | No | parity test |
| Ordering | legacy block order | structured page/node reading order | REQUIRED_SEMANTIC_PARITY when semantic order matches | No | parity test |
| Ordering divergence | raw legacy order may be arbitrary | deterministic Structured Document order may differ | ORDERING_DIFFERENCE_REQUIRES_INVESTIGATION | Potential | no representative blocking divergence found |

## Required Semantic Parity

Future Reader compatibility requires preservation of visible text for paragraphs, headings, captions, formulas, list items, and unknown text where emitted; relative visible reading order; stable heading marker grammar; stable image marker grammar for compatible asset identifiers; stable line separators; and non-leakage of unsafe payload. Byte-identical parity is required only for client-dependent grammar segments, not for richer projection metadata.

## Intentional Differences

The new projection intentionally keeps canonical evidence/source anchors, recovery summary, and projection losses outside the plain text payload. It intentionally refuses transient/signed/path-like asset identifiers. It intentionally records table/list/header/footer/footnote loss instead of fabricating unsupported Reader v2 structure. It intentionally does not make legacy continuation-image oddities canonical unless a future migration maps them into explicit assets/nodes.

## Ordering Findings

Representative fixtures show required visible ordering parity when legacy block order and Structured Document reading order represent the same semantic source. No blocking ordering difference was found. Any future migration fixture whose deterministic Structured Document reading order differs from raw legacy order must justify the new order under Structured Content semantics or classify the case as ORDERING_DIFFERENCE_REQUIRES_INVESTIGATION before cutover.

## Recovery Findings

Legacy Reader v2 plain text lacks recovery semantics. The new projection records page recovery and asset recovery losses in metadata while preserving safe visible payload. This is classified as RECOVERY_DIFFERENCE and is nonblocking.

## Evidence Findings

The current evidence chain is `Document -> SourceFile -> raw result/ProcessingRun refs -> SPR -> StructuredContentCandidate evidence refs -> StructuredDocument source refs -> projection source anchors`. Projection evidence does not appear in the Reader v2 plain text payload and must not be removed for byte parity. The richer metadata is classified as INTENTIONAL_RICHER_CANONICAL_SOURCE.

## Blocking Findings

No blocking difference was identified in the deterministic Slice 4D fixture set. A blocker would be visible text loss, heading content loss, materially wrong reading order, missing compatible image marker, unexpected caption loss, nondeterminism, or unsafe payload leakage.

## Nonblocking Findings

Nonblocking findings are: legacy lacks evidence and recovery metadata; Reader v2 cannot represent table/list/header/footer/footnote structure; table continuation images require explicit future migration mapping; production SLO/batch-size conclusions remain deferred; and DEC-019 remains required before actual migration/backfill execution.

## S4-DEC-005 Reader v2 Parity Decision

**Decision: Reader Content Stream v2 compatibility target is SEMANTIC PARITY WITH CLASSIFIED INTENTIONAL DIFFERENCES, not universal byte-identical output.** Marker syntax, heading grammar, stable line separators, and absence of unsafe payload remain byte-sensitive. Ordering, text content, captions, formulas, and compatible asset markers require semantic equality. Rich evidence/recovery metadata and documented lossiness are accepted nonblocking differences. Legacy defects are not canonical.

## S4-DEC-007 Observation Persistence Decision

**Decision: For M4, no durable Observation graph is required.** Observations remain in SPR, retained upstream evidence artifacts, candidate evidence refs, page/node/asset anchors, and projection source anchors. This is sufficient for Reader navigation, future Notes/highlights anchors, future M6 citation grounding at current scope, and audit/provenance at the Structured Document/projection boundary. Durable Observation rows may be reconsidered later only for queryable cross-document evidence, fine-grained audit mandates, independent observation lifecycle, indexing requirements, or other evidence-backed product/operational needs.

## S4-DEC-008 Legacy Migration Sequencing Decision

**Decision: No destructive migration, backfill execution, legacy deletion, route deprecation, or Reader cutover is authorized by M4 Slice 4D.** Current legacy Reader remains active and unchanged through M4. Legacy data remains retained as compatibility, parity, and possible migration evidence. Slice 4E may verify selected-candidate assembly/projection orchestration but still must not cut Reader routes over. M5 requires an explicit Reader adapter/cutover task and comparison evidence. Migration/backfill/deprecation execution requires separate later authorization and DEC-019 resolution before execution.

## DEC-019 Status

M4-DEC-019 is `Initial persistence types/backfill scope`. ADR-005 leaves the initial supported migration/backfill document-type list as a later decision. Slice 4D records this dependency only. DEC-019 remains open/applicable and must be resolved before actual legacy backfill or migration execution.

## DEC-020 Status

M4-DEC-020 is `Performance SLOs and batch sizes`. Current scale tests are regression evidence only; they do not establish production SLOs or batch-size policy. DEC-020 remains nonblocking for Slice 4D and is not closed by this document.

## Legacy Entity/Route Matrix

| Legacy entity/path | Current role | Before M5 cutover | After M5 cutover evidence | Canonical? |
|---|---|---|---|---|
| `MineruResult.result_json` | legacy Reader v2 PDF serialization source | retain unchanged; shadow/parity and possible migration source | deprecate/migrate only by separate authorization | No |
| `ContentBlock` | legacy `/api/pdf/book-text` source | retain unchanged; migration/compatibility evidence | migrate/deprecate only by separate authorization | No |
| `PdfPage` | page image/OCR raw JSON evidence | retain unchanged as legacy processing/page evidence | retain until verified migration/retention policy | No |
| `BookImage` | legacy image/table asset storage | retain unchanged as compatibility asset serving source | deprecate/migrate only after cutover evidence | No |
| `/api/v1/books/{book_id}/content` | active Reader content route | retain unchanged | cut over only in explicit M5 task | Derived stream only |
| `/api/pdf/book-text` | legacy compatibility route | retain unchanged | deprecate only after explicit policy | No |
| `/api/pdf/book-images` | legacy asset metadata route | retain unchanged | deprecate only after explicit policy | No |
| `/api/pdf/image` | legacy image metadata route | retain unchanged | deprecate only after explicit policy | No |

## Migration Safety Requirements

Future migration must be additive, non-destructive, idempotent, restartable, dry-run capable, explicitly tied to document and candidate identity, avoid auto-selection, avoid candidate overwrite, retain source until verified, emit parity reports before cutover, and skip unsupported document types with traceable reasons.

## Backfill Safety Requirements

Consistent with ADR-005, future backfill must not auto-promote newly built candidates, silently overwrite selected candidates, delete legacy source, or create mixed-version projections. It must create or map candidate/version identity explicitly and run only after separate authorization.

## Remaining Slice 4 Work

Slice 4E remains: selected candidate lookup, candidate reconstruction, Structured Document assembly, projection, selection-change behavior, and integrated deterministic/scale verification. Slice 4E still does not modify Reader routes/services, persist projections, execute migration/backfill, add schema, mark M4 Complete, or begin M5.

## Slice 4E Readiness

**READY FOR SLICE 4E WITH NONBLOCKING FINDINGS.** The nonblocking findings are DEC-019/DEC-020 remaining open in their scopes, table continuation image migration mapping remaining future work, and production cutover evidence remaining an M5 responsibility.

## Milestone Status

M4 remains In Progress. M5 remains Planned. Slice 4D does not mark M4 Complete and does not begin M5.
