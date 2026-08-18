# M4 Slice 4 Completion Review — Structured Document and Projection Boundary

## Review Metadata

| Field | Value |
|---|---|
| Document Type | Completion Review |
| Review Type | Point-in-time implementation completion review |
| Status | Completed |
| Milestone | M4 — Structured Content / Structured Document Foundation |
| Milestone Status | Unchanged — In Progress |
| Normative | No |
| Implementation Authorized | No |
| Review Date | 2026-07-24 |

## Executive Decision

**SLICE 4 COMPLETE WITH NONBLOCKING FINDINGS — READY FOR M4 COMPLETION REVIEW.**

This decision applies only to M4 Slice 4. It does not declare M4 complete, does not start M5, does not authorize Reader route cutover, and does not authorize migration/backfill execution.

## Scope

This review evaluates the merged Slice 4 path:

selected Structured Content → candidate reconstruction → Structured Document assembly → Reader-compatible derived projection.

Reviewed scope includes contracts, assembly, selection integration, projection, parity, provenance/evidence, Observation posture, migration/deprecation decisions, and remaining M4 exit items. It does not evaluate Reader UI, Reader route cutover, production rollout, M5 Reader MVP behavior, migration execution, backfill execution, retention execution, M6 intelligence, or M7 archive.

## Governance Basis

The review read the project governance, current roadmap, Roadmap v3 decision, M4 and M5 milestone records, ADR-002 through ADR-005, Slice 2 and Slice 3 plans/reviews, the Slice 4 plan, and the Slice 4D decision artifact. Governance requires M4 to remain In Progress until a separate M4 Completion Review and any remaining required exit items are complete. M5 remains Planned. Projection remains derived/noncanonical. Structured Document remains application-independent and candidate-bound. Selection remains explicit with no implicit latest and no auto-selection.

## Reviewed Sources

Production sources inspected included `app/structured_document/*`, `app/structured_document/projection/*`, Structured Content model, serializers, validators, candidate repository, selection repository, ProcessingRun persistence rows, and `app/routers/books.py`. Tests inspected included Structured Document contracts, assembly, projection, parity, and service integration tests. Legacy compatibility sources inspected included `MineruResult`, `ContentBlock`, `PdfPage`, `BookImage`, and the legacy Reader content route.

## Merge and CI Evidence

Baseline commands verified the repository root at `/workspace/pdf-ocr-service`, branch `work` initially at `1e59f1658adff38784d093d3ee0ca19ddcd2c396`, a clean tree, no staged files, and local history containing PRs #119-#146. A fresh review branch was created from that commit. No remote URL is configured in this checkout, and `gh` is not installed. Direct GitHub API access from the container was blocked with `Tunnel connection failed: 403 Forbidden`; therefore GitHub Required Backend CI could not be independently re-opened from this environment. Local merge history still confirms the expected merge commits.

| PR | Purpose | Merge SHA | Files/scope | CI | Result |
|---|---|---|---|---|---|
| #141 | Slice 4 plan | `3cc36c3` | Planning document | GitHub CI unavailable in container | Merge present; CI not independently rechecked |
| #142 | Slice 4A contracts | `4397ea6` | Structured Document contracts and tests | GitHub CI unavailable in container | Merge present; CI not independently rechecked |
| #143 | Slice 4B assembly | `e227741` | Assembler and assembly tests | GitHub CI unavailable in container | Merge present; CI not independently rechecked |
| #144 | Slice 4C projection | `1587659` | Projection contracts/projector/tests | GitHub CI unavailable in container | Merge present; CI not independently rechecked |
| #145 | Slice 4D parity/decisions | `0dd878c` | Parity tests and decisions | GitHub CI unavailable in container | Merge present; CI not independently rechecked |
| #146 | Slice 4E integration | `1e59f16` | Service integration and scale tests | GitHub CI unavailable in container | Merge present; CI not independently rechecked |

## Slice 4 Plan Review

The accepted Slice 4 plan called for a deterministic application-independent Structured Document from exactly one validated `StructuredContentCandidate`, a derived Reader v2 projection, explicit selection service integration, no persistence for Structured Document/projection, no Reader route cutover, no migration/backfill execution, and documented decisions for Observation and legacy compatibility. The merged implementation satisfies the core Slice 4 boundary. Two planned expectations remain classified rather than treated as defects: first-class section DTOs are absent, and standalone rendition collections remain deferred.

## Slice 4A Review

Slice 4A successfully established frozen Structured Document contracts, source candidate identity/schema/lineage binding, assembly policy/version fields, bounded validation and assembly errors, pure assembler entrypoints, and tests preventing repository/Reader/provider dependencies. No Structured Document persistence or Reader dependency was introduced.

## Slice 4B Review

Slice 4B implements deterministic page ordering by page order, source page index, and page id. It traverses page roots in page-local order, sorts children by sibling order and node id, emits pre-order DFS document and page-local reading order, preserves source refs for pages/nodes/evidence/warnings, rejects cycles, duplicate traversal, dangling roots, cross-page roots, parented roots, and unreachable nodes, and covers 100 pages / 10,000 nodes in regression tests. Tables, figures/assets, captions, formulas, recovery, and warnings remain represented by source candidate nodes and refs rather than duplicated document DTOs.

Section view assessment: Slice 4B did not add a first-class section DTO. The current contracts expose `section_ref` only on node views and preserve headings in deterministic hierarchy. Because M4 requires document reading order, headings/sections foundation, and page/section/node navigation foundations, but does not explicitly require a first-class section DTO before Slice 4 completion, this is a deferred enhancement rather than a blocker.

## Slice 4C Review

Slice 4C provides frozen projection contracts, projection type/version/policy, source document/candidate binding, Reader v2 heading/image/text serialization helpers, validation, explicit loss records, source anchors, recovery metadata, payload safety checks for assets, deterministic serialization, and 100-page / 10,000-entry regression evidence. Projection remains derived, noncanonical, rebuildable, in-memory, safe to discard, and candidate/version bound.

## Slice 4D Review

The Slice 4D decision artifact confirms S4-DEC-005: Reader v2 target is **semantic parity with classified intentional differences**, not universal byte-identical parity. It confirms S4-DEC-007: no durable Observation graph for M4; observations remain SPR/evidence/source/projection-anchor facts. It confirms S4-DEC-008: no destructive migration, backfill, deprecation, or Reader cutover in Slice 4; Reader cutover requires explicit M5 authorization. Parity tests cover visible text/heading/image marker/order semantics, richer metadata, intentional structure loss, recovery classifications, unsafe asset omission, and deterministic parity summaries. No legacy defect became canonical authority.

## Slice 4E Review

Slice 4E adds `build_selected_document_projection(...)` as a read/orchestration service over explicit selection lookup, candidate reconstruction, assembly, and projection. Tests cover no-selection behavior, Candidate A selected while Candidate B persists without selection, explicit A→B switch, B→A rollback reproducing A, idempotency/conflict behavior, ProcessingRun/Raw Result/SPR provenance, recovery/evidence/table/asset integration, no projection persistence, no cache, no Reader/provider coupling, and integrated 100-page / 10,000-node behavior. The pure assembler/projector remain uncontaminated by repositories.

## Commitment Matrix

| Area | Planned commitment | Merged evidence | Test/CI evidence | Result | Finding |
|---|---|---|---|---|---|
| Structured Document contracts | Application-independent, immutable, exactly one candidate, version-bound, no persistence | Frozen dataclasses and candidate identity fields | Contract tests; CI not rechecked | Satisfied | None |
| Assembly | Page/root/child/pre-order reading order, hierarchy, recovery, evidence, tables/assets | Pure assembler with invariant checks | Assembly tests and scale regression; CI not rechecked | Satisfied | S4R-D01 for section DTO |
| Projection | Derived Reader v2 compatibility, source binding, lossiness, safety | Projection contracts/projector/validator | Projection and parity tests; CI not rechecked | Satisfied | None |
| Selection | Explicit selected candidate, no latest, no auto-selection, rollback/reselection | Selection repository plus service lookup | Service integration tests; CI not rechecked | Satisfied | None |
| Persistence integration | Candidate reconstruction, idempotency, conflict, provenance | Candidate repository/ProcessingRun refs | Service integration tests; CI not rechecked | Satisfied | None |
| Legacy compatibility | Semantic parity with classified differences, no route change | Legacy route unchanged; parity artifact | Parity tests; CI not rechecked | Satisfied | S4R-O01 |
| Decisions | Observation and migration/deprecation decisions recorded; DEC-019/020 tracked | Slice 4D decision artifact and plan | Documentation/tests; CI not rechecked | Satisfied for Slice 4 | S4R-N01, S4R-D02, S4R-D03 |
| Verification | Determinism, integrated scale, CI | Local tests present; merge history present | Local checks pass; GitHub CI unavailable | Mostly satisfied | S4R-N02 |

## Canonical Authority Review

Authority chain is preserved: `StructuredContentCandidate` is the durable canonical content version; `StructuredDocument` is a deterministic application-independent assembled view; projection is a derived compatibility representation; Reader v2 stream is presentation compatibility only; legacy `MineruResult` / `ContentBlock` / `PdfPage` / `BookImage` are compatibility/migration evidence and not canonical truth. No implementation inversion was found.

## Structured Document Contract Review

Contracts are frozen, minimal, candidate-bound, schema/version-bound, and contain no persistence or Reader dependency. They retain document, candidate, lineage, transformer/policy, ProcessingRun, Raw Result, and SPR refs.

## Structured Document Assembly Review

Assembly is pure and deterministic over a validated candidate. It preserves ordering, hierarchy, page locality, evidence/warning refs, recovery page representation, and source-node identity while rejecting graph invariant violations. It does not dereference assets or duplicate candidate content.

## Selection Lifecycle Review

ADR-002 behavior is preserved: no selection exists before explicit set; candidate creation does not select; new candidates do not become current; A remains current after B persistence; explicit B selection changes output; rollback/reselect A reproduces A; candidates are immutable; projection calls do not mutate selection; no hidden latest exists.

## Persistence Integration Review

Structured Content candidate persistence reconstructs the candidate graph, validates persisted candidates, handles idempotent duplicate creates, reports conflicts for mismatched duplicate ids, validates ProcessingRun/document/source evidence relationships, and leaves transaction ownership to the caller. Slice 4 service uses this durable candidate only as input to in-memory assembly/projection.

## Projection Review

Projection validates document/candidate identity, schema/version, projection type/version/policy, entries, losses, source anchors, and recovery summaries. It maps headings, paragraphs, list items, captions, formulas, unknown text, figures, and rendered tables into Reader-compatible lines/markers while preserving loss metadata for omitted or simplified structures.

## Projection Lossiness Review

Lossiness is explicit and bounded: list containers/nesting, table structure, header/footer/footnote omission, unavailable/unsafe assets, unsupported node types, recovery not expressible in plain stream, and evidence not expressible in payload are recorded as projection losses or metadata. The projection does not claim round-trip reconstruction.

## Reader v2 Compatibility Review

Reader v2 compatibility covers heading marker grammar, paragraph text, compatible image marker grammar, deterministic newline separators, relative reading order, caption/formula visible text, and absence of unsafe transient payload. Richer metadata and recovery/loss details are intentionally out-of-band.

## Legacy Parity Review

Legacy Reader routes still assemble content from `MineruResult.result_json` for PDFs and file content for TXT books. Slice 4 parity tests characterize the legacy serialization and compare semantic parity rather than byte-identical universal parity. No route cutover occurred, which is expected for M4.

## Observation / Evidence Review

Current evidence chain remains Document → SourceFile → ProcessingRun / Raw Result → SPR → candidate evidence → Structured Document refs → projection anchors. S4-DEC-007 concludes no durable Observation graph is needed for M4. This is sufficient for Slice 4 and M4 review readiness unless the separate M4 Completion Review finds an unaddressed audit/query requirement.

## Migration / Deprecation Review

S4-DEC-008 confirms no migration execution, backfill execution, legacy deletion, route deprecation, or Reader cutover in Slice 4. Future migration/backfill must be separately authorized, additive, non-destructive, idempotent, dry-run capable, candidate/version explicit, and non-auto-promoting. M4 requires policy/decision readiness, not destructive execution.

## Section View Review

No first-class section DTO was implemented. Headings and deterministic hierarchy are preserved, and projection maps headings to Reader v2 lines. The section DTO absence is a deferred enhancement because current M4 wording requires headings/sections foundation and navigation handoff, but not necessarily a first-class section DTO before Slice 4 completion.

## Rendition Limitation Review

`StructuredContentCandidate` has logical asset references and rendition ref ids but no validator-resolvable standalone top-level rendition collection. Current behavior can emit Reader v2-compatible image/table markers for compatible available assets and record unavailable/unsafe assets as losses. This does not block Slice 4 or the M4 Completion Review, but it may block or constrain M5 image/table cutover until resolved.

## DEC-019 Review

DEC-019 remains open in Slice 4 planning scope as a future migration/backfill/retention dependency. It does not block Slice 4 completion or proceeding to the M4 Completion Review. The M4 Completion Review must decide whether DEC-019 must be resolved before milestone closure or can remain tied only to later migration/backfill execution.

## DEC-020 Review

DEC-020 remains open for production performance/SLO/batch-size decisions. The 100-page / ~10,000-node tests are regression evidence only, not an SLA, throughput guarantee, or memory capacity guarantee. DEC-020 does not block Slice 4 completion; production-readiness or M5 large-document behavior should own actual SLOs.

## Error Boundary Review

Bounded errors exist for invalid content input, unsupported versions, assembly invariant violations, no selection, selected-candidate document mismatch, invalid/corrupt candidates, selection conflicts, candidate conflicts, and projection validation/version mismatches. No raw SQL leak, provider payload leak, raw candidate dump, or silent fallback was found in the reviewed boundaries.

## Dependency / Layering Review

Dependency direction is preserved: service → repositories/selection → assembler/projector; assembler → Structured Content domain and validation only; projector → Structured Document and Structured Content domain only. Reader production routes do not depend on the new service, and assembler/projector do not import repositories, SQLAlchemy sessions, providers, or Reader routes.

## Determinism Review

Candidate reconstruction, assembly, projection, service orchestration, and A→B→A reselection tests demonstrate deterministic repeat behavior. Ordering uses explicit page/root/sibling ordering plus stable tie-breakers, not time/random/current-row-order.

## Scale Review

Regression evidence covers 100 pages and approximately 10,000 nodes/entries, including integrated persistence → selection → service → assembly → projection. This is regression evidence only. It is not a production SLA, throughput guarantee, or memory capacity guarantee.

## Reader Isolation Review

Current production Reader content routes remain on the legacy path. No M4 route cutover occurred. This is expected and not a Slice 4 defect.

## Blocking Findings

None.

## Nonblocking Findings

- **S4R-N01 — DEC-019 remains open for milestone/migration governance.** It does not block Slice 4, but the M4 Completion Review must explicitly disposition it.
- **S4R-N02 — GitHub CI evidence could not be independently re-opened from this container.** Local merge history and local validation are present; Required Backend CI should be checked on the PR before merge.

## Deferred Findings

- **S4R-D01 — First-class section DTO not implemented.** Headings and deterministic hierarchy are sufficient for Slice 4; section navigation DTOs can be future enhancement if M5 needs them.
- **S4R-D02 — Standalone rendition collection remains deferred.** Current logical asset/rendition refs are sufficient for Slice 4; richer image/table cutover may require a future model/cache decision.
- **S4R-D03 — DEC-020 production SLO/batch sizing deferred.** Scale tests are regression evidence only.
- **S4R-D04 — Projection cache remains deferred.** No cache is required now; any future cache must be derived, noncanonical, version-keyed, and rebuildable.

## Out-of-Scope Findings

- **S4R-O01 — Reader route cutover is M5/out of scope for Slice 4.**
- **S4R-O02 — Legacy migration/backfill execution is out of scope and separately authorized.**
- **S4R-O03 — Durable Observation graph is not required by S4-DEC-007 for M4.**

## Slice 4 Readiness Decision

**SLICE 4 COMPLETE WITH NONBLOCKING FINDINGS — READY FOR M4 COMPLETION REVIEW.**

## Remaining M4 Exit Items

| M4 exit item | Status | Evidence | Required before milestone completion? |
|---|---|---|---|
| Formal M4 Completion Review | Not yet performed | M4 requires documented completion evidence | Yes |
| M5 handoff package | Not yet standalone | M4 requires explicit M5 handoff package | Yes, likely as part of or immediately after M4 Completion Review |
| DEC-019 resolution | Open | Slice 4 plan carried it as migration/backfill/retention dependency | To be decided before milestone closure or explicitly deferred to migration execution |
| DEC-020 resolution | Open/deferred | Slice 4 plan treats scale as regression, not SLO | Not required for Slice 4; M4 closure should explicitly defer or resolve |
| Legacy migration/backfill policy | Policy recorded | S4-DEC-008 | Policy required; execution not required in M4 |
| Retention/deletion policy | Partial through ADR/S4 decisions | ADR-005 and S4-DEC-008 constrain destructive action | May require explicit M4 closure disposition |
| Observation decision | Recorded | S4-DEC-007 | Yes; satisfied for Slice 4 |
| Projection/Reader compatibility evidence | Present | Projection/parity tests and Slice 4D decisions | Yes; satisfied subject to CI confirmation |
| M4 limitations/deferred scope | Present here and prior reviews | This review records limitations | Yes; should be carried into M4 Completion Review |
| Milestone status change | Not performed | Governance separates slice completion from milestone completion | Required only after M4 Completion Review succeeds |

## Next Governance Task

The next governance task supported by repository evidence is **M4 Completion Review — Structured Content / Structured Document Foundation**, unless maintainers choose to resolve DEC-019/DEC-020 or a standalone M5 handoff package first. This review does not begin that task.

## M5 Handoff Readiness

Enough Slice 4 evidence exists to prepare an eventual M5 handoff: selected candidate service exists, Structured Document assembly exists, Reader v2 projection exists, parity evidence exists, and Reader routes remain legacy. The M5 handoff should be finalized through the M4 Completion Review or a separate handoff artifact after it; this document grants no M5 implementation authorization.

## Milestone Status

M4 remains In Progress. M5 remains Planned. Slice 4 completion is independent from M4 milestone completion.
