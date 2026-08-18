# M4 Completion Review — Structured Content / Structured Document Foundation

## Review Metadata

| Field | Value |
|---|---|
| Document Type | Completion Review / Governance Evidence |
| Review date | 2026-07-24 |
| Milestone reviewed | M4 — Structured Content / Structured Document Foundation |
| Upstream baseline | `f65bfbaeb79e24d507802d447e895291eeba6e6d` / PR #147 merge commit |
| Scope | M4 Slice 1 through Slice 4 merged implementation, tests, decisions, and review evidence |
| Milestone status action | None; this review does not edit `docs/milestones/M4.md` or `docs/milestones/M5.md` |

## Executive Decision

M4 COMPLETION EVIDENCE SATISFIED WITH NONBLOCKING FINDINGS —
READY FOR MILESTONE STATUS RECONCILIATION

## Scope

This review evaluates whether M4 completion evidence is demonstrated. It is documentation/governance only. It does not modify production code, tests, fixtures, schemas, migrations, Reader routes/services, legacy routes, selection behavior, projection behavior, or milestone status. It does not authorize Reader cutover, destructive migration, backfill execution, M5 implementation, production readiness, or commercial readiness.

## Governance Basis

The governing basis is `docs/project/document-governance.md`, Roadmap v3, `docs/milestones/M4.md`, `docs/milestones/M5.md`, accepted ADR-002 through ADR-005, the M4 Slice 2/3/4 plans and reviews, and the Slice 4D Observation/legacy decision artifact. Point-in-time reviews are evidence records, not status changes. M4 requires an explicit M5 handoff and evidence before any later milestone-status reconciliation.

## Reviewed Evidence

Reviewed documents include Roadmap v3 proposal/decision/review, M4 and M5 milestone plans, ADR-002 through ADR-005, Slice 2/3/4 plans and reviews, Slice 4D decisions, structured content/domain code, structured content transformation code, persistence and selection repositories, ProcessingRun model/repository, Structured Document assembler/validation/service/projection code, legacy Reader route behavior, Alembic migrations, and tests covering contracts, validation, fixtures, determinism, persistence, selection, transformation, projection, parity, and integration.

## Delivery History

Local history at the review baseline contains PR #110 through PR #147, including Roadmap v3 proposal/acceptance/reconciliation, M4/M5 redefinition, ADR-002 through ADR-005, M4 Slice 1 PRs #123-#126, M4 Slice 2 PRs #127-#133, M4 Slice 3 PRs #134-#140, and M4 Slice 4 PRs #141-#147. PR #147 is merged at `f65bfbaeb79e24d507802d447e895291eeba6e6d`.

## GitHub CI Evidence

Live GitHub check inspection was attempted from this environment but GitHub API/page access for this repository was not available to the agent. Local git history demonstrates the required implementation/review PR merges and local validation in this PR re-runs repository checks. The CI evidence table therefore records local merge evidence plus the required follow-up CI expectation for this PR.

| PR / range | Scope | Required Backend CI | Result |
|---|---|---|---|
| #123-#126 | M4 Slice 1 domain contracts, validation, fixtures, regression/scale | Required Backend CI expected on merged PRs; local environment could not query live checks | Merged into baseline; no blocking CI evidence found locally |
| #128-#133 | M4 Slice 2 schema, repository, selection, ProcessingRun, integrated review | Required Backend CI expected on merged PRs; local environment could not query live checks | Merged into baseline; no blocking CI evidence found locally |
| #135-#140 | M4 Slice 3 transformation contracts/core/structure/tables/assets/verification | Required Backend CI expected on merged PRs; local environment could not query live checks | Merged into baseline; no blocking CI evidence found locally |
| #142-#147 | M4 Slice 4 Structured Document, projection, parity, service integration, review | Required Backend CI expected on merged PRs; local environment could not query live checks | Merged into baseline; no blocking CI evidence found locally |
| This PR | Documentation-only final completion review and M4→M5 handoff | Required Backend CI must pass before merge | Pending external CI |

## Architecture Boundary

M4 establishes a provider-independent chain: Raw Processing Result and SPR are upstream evidence; selected StructuredContentCandidate is durable canonical content for this foundation; StructuredDocument is a deterministic derived in-memory view; Reader Content Stream v2 projection is derived, lossy, rebuildable, and noncanonical.

## Canonical Authority

Canonical authority for downstream M5 planning is explicit selected StructuredContentCandidate → StructuredDocument → derived Reader projection. Provider JSON, Raw Processing Result payloads, SPR payloads, MineruResult, ContentBlock, PdfPage, BookImage, and Reader v2 serialization are not canonical product content.

## Slice 1 Review

Slice 1 established in-memory Structured Content types, identity wrappers, enums, pages, nodes, assets, evidence, warnings, recovery states, validators, serializers, golden fixtures, deterministic serialization, and bounded scale tests. This satisfies the contract foundation used by later persistence and transformation slices.

## Slice 2 Review

Slice 2 added durable ORM schema and migrations for candidates, pages, nodes, page roots, evidence, warnings, assets, renditions, table cells, selection, and ProcessingRun linkage. Repository tests cover roundtrip reconstruction, idempotency, conflict behavior, explicit selection, optimistic versioning, rollback/reselection, no-selection behavior, ProcessingRun provenance, migration-chain expectations, and integrated transaction/concurrency behavior.

## Slice 3 Review

Slice 3 added SPR-to-Structured Content transformation contracts, context, core text mapping, structural mapping, table/asset mapping, unknown/recovery behavior, safe warnings, evidence propagation, deterministic golden output, provider-payload isolation, fixture immutability, scale regression, and persistence integration.

## Slice 4 Review

Slice 4 added Structured Document contracts, deterministic assembler, validation, derived projection contracts/projector/Reader v2 serializer, projection safety validation, semantic Reader parity verification, explicit selected-candidate service integration through `build_selected_document_projection(...)`, no latest fallback, no auto-selection, no mutation, no projection persistence, and no Reader cutover.

## Formal Exit Criteria Assessment

| # | Formal criterion | Evidence | Decision | Finding |
|---|---|---|---|---|
| 1 | A valid SPR fixture transforms deterministically into candidate Structured Content. | Slice 3 transformer and golden/determinism tests. | SATISFIED | None |
| 2 | Minimum accepted/current-content lifecycle explicitly defined and implemented. | ADR-002; selection repository/service; optimistic version tests. | SATISFIED | None |
| 3 | Accepted/selected content distinguishable from Raw Result and SPR. | Candidate identity, selection rows, ProcessingRun/raw/SPRs refs. | SATISFIED | None |
| 4 | Structured Document preserves stable ordering and supported hierarchy. | Slice 4B assembler sorts pages and traverses root/child order deterministically. | SATISFIED | M4R-N01 |
| 5 | Evidence anchors trace content/assets/recovery to source and processing evidence. | ADR-004; EvidenceReference; persisted candidate evidence; projection source anchors. | SATISFIED | None |
| 6 | Recovery states survive into content and projection-ready output. | Candidate/page/node/asset recovery plus projection recovery/loss summaries. | SATISFIED | None |
| 7 | Projection generated without becoming canonical content. | Slice 4C projector/service produce in-memory derived output; no projection persistence. | SATISFIED | M4R-D03 |
| 8 | Current Reader compatibility has documented adapter/migration/deprecation rule. | S4-DEC-005 and S4-DEC-008; parity tests. | SATISFIED WITH NONBLOCKING LIMITATION | M4R-D04 |
| 9 | ProcessingRun persistence has recorded decision and is implemented if required. | ADR-004; `ProcessingRun` ORM/repository/migration/tests. | SATISFIED | None |
| 10 | Observation persistence has a recorded decision and is implemented only if required. | S4-DEC-007 records no durable Observation graph required for M4. | SATISFIED | M4R-O03 |
| 11 | Required schema changes are reviewed and validated. | Slice 2A migration/schema tests and migration chain tests. | SATISFIED | None |
| 12 | Tests cover success, partial, degraded, empty semantic content, invalid, ordering, assets, provenance, selection, projection and compatibility. | Domain, validation, fixture, transformation, persistence, projection, parity, service tests. | SATISFIED | None |
| 13 | Provider-specific payload semantics do not leak past SPR. | Provider isolation tests and extension-key validation. | SATISFIED | None |
| 14 | No provider secrets persisted in content/provenance metadata. | Secret-leak transformation tests and safe projection asset filtering. | SATISFIED | None |
| 15 | M4 limitations and deferred scope documented. | Slice reviews plus this review. | SATISFIED WITH NONBLOCKING LIMITATION | M4R-N01, M4R-N02, M4R-D02, M4R-D03, M4R-D04 |
| 16 | M5 can consume explicit content/projection handoff without provider JSON or legacy tables as canonical truth. | `docs/handoffs/m4-to-m5-handoff.md` created by this task. | SATISFIED | None |
| 17 | Completion evidence recorded before milestone status changes. | This review records evidence while M4 remains In Progress and M5 remains Planned. | SATISFIED | None |

No criterion is NOT SATISFIED.

## M4 Design Decision Reconciliation

| Decision area | Original status | Accepted resolution/evidence | Completion disposition |
|---|---|---|---|
| SCV vs accepted snapshot | Open | ADR-002 selects explicit selected/current content over hidden latest; implementation uses selected candidate snapshots. | Resolved for M4 |
| Canonical/selected lifecycle | Open | Selection repository provides zero-or-one explicit selection with versioned replacement/rollback. | Resolved for M4 |
| Content-node minimum | Open | ADR-003 and Slice 1/3 define supported node vocabulary, attributes, hierarchy, evidence, and recovery. | Resolved for M4 |
| Evidence/asset anchors | Open | ADR-004 and implementation persist compact evidence/asset references. | Resolved for M4 |
| ProcessingRun persistence | Open | ADR-004 and Slice 2D implement durable runs and candidate/run linkage. | Resolved for M4 |
| Observation persistence | Open | S4-DEC-007 decides no durable Observation graph for M4. | Resolved for M4 |
| Projection boundary | Open | ADR-005 and Slice 4C/4E keep projection derived, rebuildable, noncanonical. | Resolved for M4 |
| Legacy compatibility/migration | Open | S4-DEC-005/008 define semantic parity, retained legacy, and no cutover/migration execution in M4. | Resolved for M4 policy; execution deferred |
| Partial/degraded acceptance | Open | Domain and transformer preserve complete/partial/degraded/unavailable/no-usable states. | Resolved for M4 |
| Asset storage/reference approach | Open | AssetReference and rendition refs are logical persisted anchors; richer delivery deferred. | Resolved for M4; richer rendition view deferred |
| Current-content selection | Open | Explicit selection row and service are authoritative; no latest fallback. | Resolved for M4 |
| Schema migration strategy | Open | Additive Alembic migrations 0002/0003 and migration tests. | Resolved for M4 |

## Content Lifecycle Review

The content lifecycle is candidate creation, explicit selection, versioned replacement, rollback/reselection, and deterministic reconstruction. No code path reviewed makes latest candidate implicit current content. The service raises no-selection instead of auto-selecting.

## SPR-to-Content Review

The transformer accepts provider-independent SPR plus context and emits StructuredContentCandidate with deterministic IDs/order, source locations, evidence, warnings, recovery state, tables, figures, captions, and assets. Provider-specific raw payload semantics are kept out of downstream content.

## Structured Document Review

The Structured Document assembler derives page views, node views, child refs, traversal indexes, and document reading order from one validated candidate. It is deterministic and in-memory. The first-class section DTO remains absent but heading levels and hierarchy satisfy the current M4 foundation.

## Selection Review

Selection persistence is explicit per document, zero-or-one, candidate-validated, optimistic-versioned, replacement-capable, and rollback-capable. Candidate creation does not implicitly select, and selected-candidate projection does not use latest fallback.

## Provenance / ProcessingRun Review

ProcessingRun persistence is implemented by ORM/repository/migration and linked to candidates via processing_run_ref, raw_result_ref, and structured_processing_result_ref. This satisfies M4's durable run/provenance decision at foundation scope.

## Evidence / Asset Review

Evidence references trace source file/page/location, raw result, SPR, SPR node/observation/evidence refs, and warning refs. AssetReference captures logical assets, evidence, recovery, compatible rendition refs, captions, alt text, and metadata without fabricating missing assets.

## Recovery Review

Recovery states cover candidate summaries, page state, node state, warning summaries, assets, and projection recovery/loss facts. Degraded, partial, unavailable, no usable semantic content, and unsafe/missing assets are represented as facts for M5 presentation mapping.

## Projection Review

Projection is derived from Structured Document plus candidate, validated, lossy, rebuildable, and noncanonical. It records source candidate/document identity and losses for structure dropped, tables, lists, omitted header/footer/footnote, unsupported semantics, unavailable assets, and recovery facts not expressible in text stream.

## Reader Compatibility Review

S4-DEC-005 sets semantic parity with classified intentional differences for Reader Content Stream v2. The current legacy Reader route remains active. M4 does not cut over Reader routes, deprecate legacy entities, or authorize migration/backfill execution.

## Observation Decision

S4-DEC-007 is confirmed: no full durable Observation graph is required for M4. SPR observations, retained upstream artifacts, candidate evidence refs, Structured Document refs, and projection anchors are adequate for M5 navigation, future Notes/highlights anchoring, M6 citation grounding at current scope, and audit/provenance at the reviewed boundary.

## Legacy Migration / Deprecation Review

Legacy MineruResult, ContentBlock, PdfPage, BookImage, and current Reader content route are retained and noncanonical. They may be used only through explicit compatibility/migration paths. M4 records policy and parity evidence; execution is later-authorized work.

## DEC-019 Disposition

**B. OPEN BUT NONBLOCKING FOR M4 / REQUIRED BEFORE ACTUAL MIGRATION EXECUTION.** DEC-019 concerns initial persistence types/backfill scope. M4 requires legacy compatibility/migration policy but not destructive migration/backfill execution. S4-DEC-008 postpones migration/backfill execution and requires DEC-019 before actual execution. Therefore DEC-019 does not block M4 completion evidence but remains a required later gate before real migration/backfill work.

## DEC-020 Disposition

**A. EXPLICITLY DEFERRED TO M5 / PRODUCTION READINESS — NONBLOCKING FOR M4.** DEC-020 concerns production SLOs and batch sizes. Current 100-page / approximately 10,000-node tests are regression evidence, not an SLA, maximum size, throughput commitment, or memory guarantee.

## Retention / Deletion Disposition

M4 satisfies foundation constraints: dependency-aware safety, retained canonical/evidence relationships, no destructive migration before evidence, and a migration/deprecation policy. Product-level delete/remove behavior belongs to M5, while final retention/privacy/security policy remains a downstream commercial gate. A separate final retention policy is not required to close M4 evidence.

## Section View Limitation

M4 has deterministic headings, levels, hierarchy, page order, node order, and source anchors. No first-class section DTO currently exists. This is a nonblocking limitation and likely M5 planning decision, not an M4 blocker.

## Rendition Limitation

M4 persists logical AssetReference and rendition refs but does not provide a standalone validator-resolvable rendition collection for rich presentation. This does not block M4 foundation; it constrains future M5 image/table presentation and asset delivery design.

## Projection Cache Disposition

No durable projection cache exists and none is required for M4. Projection remains rebuildable and noncanonical. If introduced later, a cache must be version-keyed, rebuildable, invalidatable, and explicitly noncanonical.

## Error / Safety Review

Reviewed errors are bounded at repository, selection, transformation, assembly, service, and projection boundaries. Unsafe extension keys are rejected; provider payloads/secrets are tested not to leak; unsafe asset refs are omitted/degraded rather than serialized into Reader stream.

## Determinism / Scale Review

Determinism is covered by serialization, fixture/golden, transformation retry/deepcopy/reparse, page/node order, assembly order, projection repeatability, selection rollback, and integrated service tests. Scale evidence covers 100 pages and approximately 10,000 nodes/entries as regression coverage only.

## Production-Minimum Review

M4 boundary-level production discipline is satisfied: additive migration safety, deterministic behavior, explicit failure/recovery states, provenance, cleanup/transitional rules, no secret leakage, compatibility/migration policy, documented limitations, and ProcessingRun linkage. Full auth, quotas, enterprise observability, commercial backup, commercial retention/privacy, public pilot readiness, and release readiness are out of scope.

## Blocking Findings

No blocking findings were identified.

## Nonblocking Findings

- **M4R-N01 — First-class section DTO absent.** Heading/hierarchy foundations satisfy M4; M5 must decide whether derived headings are sufficient.
- **M4R-N02 — Standalone validator-resolvable rendition collection absent.** Logical asset/rendition refs satisfy M4; richer presentation remains M5 work.
- **M4R-N03 — Live GitHub CI check details unavailable in this agent environment.** Required history is merged locally and this PR must still pass Required Backend CI before merge.

## Deferred Findings

- **M4R-D01 — DEC-019 remains required before actual migration/backfill execution.**
- **M4R-D02 — DEC-020 production SLO/batch-size policy deferred to M5 / production readiness.**
- **M4R-D03 — Projection cache deferred as optional noncanonical optimization.**
- **M4R-D04 — Reader cutover, route adapter, migration execution, and legacy deprecation deferred to explicit M5/later authorization.**
- **M4R-D05 — Product-level delete/remove semantics and final retention/privacy/security policy deferred downstream.**

## Out-of-Scope Findings

- **M4R-O01 — M5 Reader UI/API behavior not evaluated or implemented.**
- **M4R-O02 — M6 intelligence/citation product behavior not evaluated or implemented.**
- **M4R-O03 — Durable Observation graph not required by accepted M4 decision.**
- **M4R-O04 — Production/commercial readiness not evaluated or claimed.**

## M4 Completion Evidence Decision

All 17 formal M4 criteria are SATISFIED or SATISFIED WITH NONBLOCKING LIMITATION. M4 completion evidence is sufficient for a later milestone status reconciliation task. This review does not perform that status reconciliation.

## M4→M5 Handoff Assessment

The explicit handoff package is recorded in `docs/handoffs/m4-to-m5-handoff.md`. It defines canonical M5 inputs, forbidden canonical inputs, service boundary, navigation foundations, asset/table references, recovery facts, provenance/evidence anchors, ProcessingRun linkage, legacy compatibility, migration constraints, observation posture, rebuild semantics, known limitations, deferred items, and M5 first planning decisions.

## Milestone Status

M4 Milestone Status remains In Progress. M5 Milestone Status remains Planned. Recommended next governance action: M4 Milestone Status Reconciliation.
