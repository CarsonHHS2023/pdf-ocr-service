# Roadmap v3 Review — Delivery-Stage Decomposition for M4–M7

Structured Content, Reader MVP, Smart Reading Intelligence, and Smart Archive

> **Notice:** This document is a Roadmap v3 review/proposal record. It captures the project-owner-approved planning direction for formal decision preparation, but it does not itself replace the current roadmap, change milestone status, permit implementation work, or create release authority. Roadmap v2 and the current roadmap remain historical/current authority until a later Roadmap v3 decision record is accepted and the authoritative roadmap is updated.

| Field | Value |
|---|---|
| Document Type | Roadmap Review and Proposal |
| Approval Status | Proposed |
| Lifecycle Status | Active |
| Review Date | 2026-07-20 |
| Authority Domain | Roadmap v3 planning analysis, proposed M4–M7 decomposition, scope-transfer review, and decision preparation |
| Applies To | Atlas forward roadmap after completed M1–M3 |
| Related Current Roadmap | [roadmap.md](roadmap.md) |
| Related Roadmap v2 Review | [roadmap-v2-review.md](roadmap-v2-review.md) |
| Related Roadmap v2 Decision | [roadmap-v2-decision.md](roadmap-v2-decision.md) |
| Related Milestone Index | [../milestones/README.md](../milestones/README.md) |
| Related Governance | [../project/document-governance.md](../project/document-governance.md) |

## 1. Purpose

This review exists to prepare a formal Roadmap v3 decision by recording the current repository evidence, the project-owner-approved planning direction, the proposed M4–M7 delivery-stage decomposition, and the unresolved decisions that must remain visible. It is a planning record only; it does not update [roadmap.md](roadmap.md), change [M4](../milestones/M4.md), rewrite [M5](../milestones/M5.md), create M6 or M7 milestone files, or authorize implementation.

## 2. Governance and authority

The project owner has approved the planning package and workflow for Roadmap v3 decision preparation. This file remains `Approval Status: Proposed`, meaning it is active planning evidence rather than repository authority for the new sequence. Roadmap v2 history remains recorded in [roadmap-v2-review.md](roadmap-v2-review.md) and accepted through [roadmap-v2-decision.md](roadmap-v2-decision.md). The current authoritative roadmap remains [roadmap.md](roadmap.md) until a later Roadmap v3 decision record is accepted and the roadmap plus milestone index are updated. `Lifecycle Status: Active` means this review is the active planning record for that workflow; it does not mean the proposed roadmap has been accepted.

## 3. Confirmed historical state

This section records current reconciled state only. It does not present proposed M4–M7 as current authority.

| Milestone | Current Reconciled State | Historical Meaning |
|---|---|---|
| M1 | Complete | Foundation, migrations, `Document`/`SourceFile`, Storage Adapter, source retention, and M1-to-M2 handoff are complete historical foundation. |
| M2 | Complete for revised boundary | M2 closed at retained Raw Processing Result and controlled provider integration; Raw Result interpretation moved forward. |
| M3 | Complete for revised scope | M3 completed SPR v1, normalization, recovery semantics, diagnostics, evidence, fixtures, and deterministic validation; durable Structured Content and Reader-facing work transferred to M4. |
| M4 | In Progress under old/current roadmap | Current roadmap names M4 Smart Reading OS and includes inherited Structured Content / Structured Document, Recovery Presentation, Reader projection, and Smart Reading capabilities. |
| M5 | Planned under old/current roadmap | Current roadmap names M5 Smart Archive as a future application over shared Structured Content, provenance, and Document Intelligence Core. |

M1–M3 remain unchanged. The old M4 is not labeled failed or cancelled, the old M5 is not labeled wrong or invalid, and proposed renaming does not retroactively rename historical milestone records. Roadmap v2 remains historical evidence.

## 4. Current implementation frontier

Primary architecture and implementation evidence supports this current boundary:

```text
Source Evidence
  → Storage
  → Processing Provider
  → Raw Processing Result
  → Structured Processing Result
```

The next frontier is:

```text
Structured Processing Result
  → Structured Content / Structured Document
  → projection / presentation
  → Reader / API / downstream applications
```

SPR is noncanonical. It is provider-independent normalized processing evidence and recovery output, not durable canonical Structured Content. Reader streams and Reader presentation formats are also noncanonical projection/compatibility formats.

## 5. Problem statement

Current M4 is overloaded because it combines inherited M3 platform work with application and intelligence features: Structured Content, canonicalization, Structured Document assembly, Reader projection, Recovery Presentation, Speed Reading, Notes, Flashcards, Mind Map, broad Smart Reading scope, and production concerns. Those items have different dependencies and exit criteria.

Current M5 Smart Archive sequencing is premature as a full milestone because Smart Archive depends on shared Structured Content, provenance, evidence, lifecycle, retrieval, ownership, and deletion foundations. Treating it as the immediate next application risks duplicating Reader content models or consuming provider JSON as archive truth before the shared content foundation exists.

## 6. Owner-approved planning direction

The owner-approved direction for decision preparation is:

1. Adopt Roadmap v3 delivery-stage decomposition.
2. Preserve M1–M3 historical records and reconciled statuses.
3. Keep the project in M4 while redefining proposed M4 as Structured Content / Structured Document Foundation.
4. Define proposed M5 as Reader MVP.
5. Add proposed M6 as Smart Reading Intelligence.
6. Move Smart Archive to proposed M7.
7. Separate Structured Content foundation from Reader and Smart Reading intelligence.
8. Scope M5 around general reading, basic Speed Reading, stable Reader behavior, navigation, Recovery Presentation, and lexical search.
9. Treat Notes/highlights as optional M5 scope only with content anchors, identity, ownership, and retention/deletion behavior.
10. Exclude Flashcards, Mind Map, AI Tutor, RAG, semantic search, full Translation, and full TTS from required M5 scope.
11. Place selected evidence-backed Smart Reading intelligence in M6.
12. Prioritize M6 candidates as: evidence-backed chapter summaries; citation-backed document Q&A; Flashcards; Mind Map; broader AI Tutor. This order does not make every item mandatory.
13. Place semantic search in M6.
14. Keep Smart Reading and Smart Archive as peer applications over shared Structured Content, provenance, and evidence foundations.
15. Keep SPR and Reader presentation formats outside canonical Structured Content.
16. Permit a temporary SPR-to-Reader bridge only when explicitly noncanonical, isolated behind a projection boundary, governed by a documented migration condition, and prohibited from becoming the durable content model.
17. Require M4 decisions on minimal content-version lifecycle, canonical/selected-content model, projection boundary, legacy compatibility path, and whether minimal ProcessingRun persistence is required.
18. Avoid automatically requiring durable Observation persistence in M4.
19. Use horizontal milestone requirements plus an explicit external pilot/commercial gate for production/commercial readiness policy.
20. Preserve deferred decisions for schemas, APIs, AI provider, vector database, deployment target, auth provider, final retention policy, and complete M6 feature set.

This is owner-approved direction for decision preparation, not yet current roadmap authority.

## 7. Proposed roadmap principles

1. Shared content before application intelligence.
2. SPR is not canonical content.
3. Reader projection does not define canonical content.
4. Smart Reading and Smart Archive are peer applications.
5. Temporary compatibility bridges remain noncanonical.
6. Milestones require measurable exit criteria.
7. Product milestones do not silently absorb unfinished platform work.
8. AI outputs require evidence/provenance policy.
9. External release requires explicit production/security gates.
10. Historical scope transfers remain visible.

## 8. Proposed milestone sequence

This table is proposed. M1–M3 remain historical and unchanged, and the current authoritative roadmap has not yet been updated.

| Milestone | Proposed Name | Proposed Status | Purpose |
|---|---|---|---|
| M4 | Structured Content / Structured Document Foundation | In Progress | Convert SPR evidence into minimal durable Structured Content / Structured Document foundations, with canonical/selected lifecycle and projection boundary decisions. |
| M5 | Reader MVP | Planned | Deliver stable general reading, basic Speed Reading, navigation, Recovery Presentation, lexical search, and Reader projection behavior over shared content foundations. |
| M6 | Smart Reading Intelligence | Planned | Add selected evidence-backed Smart Reading intelligence such as summaries, citation-backed Q&A, and semantic search with provenance, safety, and cost controls. |
| M7 | Smart Archive | Planned | Build the archive peer application over shared content, provenance, metadata, lifecycle, retrieval, and cross-document evidence foundations. |

## 9. Current-to-proposed scope-transfer ledger

| Scope | Existing Location | Proposed Location | Reason | Historical Treatment |
|---|---|---|---|---|
| Structured Content | Current M4 inherited from M3 | Proposed M4 | Shared foundation before Reader or archive apps. | Transfer remains visible. |
| SCV/versioning | Current M4 inherited frontier | Proposed M4 | Minimal accepted/versioned snapshot is a foundation decision. | Existing M3 transfer preserved. |
| canonicalization | Current M4 inherited frontier | Proposed M4 | Canonical/selected lifecycle must precede projections. | Not retroactive to M3. |
| Structured Document | Current M4 inherited frontier | Proposed M4 | Needed as application-independent assembled document boundary. | Current M4 remains understandable. |
| ProcessingRun | Current M4/open platform concern | Proposed M4 decision | M4 must decide whether minimal persistence is required. | Not silently decided here. |
| Observation | Current M4/SPR evidence concern | Proposed M4 deferred/minimal decision | Durable Observation persistence is not automatically required. | Deferred explicitly. |
| evidence/assets | Current M3/M4 evidence frontier | Proposed M4 | Anchors and provenance support future Reader and AI. | M3 evidence completion preserved. |
| projection boundary | Current M4 | Proposed M4 | Separates canonical content from Reader/API presentation. | Bridge constraints documented. |
| Reader API | Current M4 Smart Reading OS | Proposed M5 | Reader API is application delivery over projection. | Old M4 scope split. |
| Reader serialization | Current M4 compatibility | Proposed M5 | Stream/serialization is presentation, not canonical content. | Historical Reader relocation preserved. |
| Recovery Presentation | Current M4 subset | Proposed M5 with M4 propagation support | User-facing recovery belongs in Reader; source recovery policy begins in M4. | Not the whole M4. |
| navigation | Current M4 Reader scope | Proposed M5 | Reader MVP behavior. | Scope transfer documented. |
| image/table support | Current M4 Reader/content scope | Proposed M4 anchors and M5 display | Anchors in content foundation; presentation in Reader MVP. | Split by boundary. |
| lexical search | Current M4 broad Smart Reading | Proposed M5 | Basic Reader utility without semantic infrastructure. | Not AI scope. |
| Speed Reading | Current M4 Smart Reading OS | Proposed M5 basic only | Basic mode belongs in Reader MVP; full product expansion deferred. | Old scope narrowed. |
| Notes/highlights | Current M4 Smart Reading OS | Optional proposed M5 | Allowed only with anchors, identity, ownership, retention/deletion. | Optional, not mandatory. |
| Translation | Current M4 broad Smart Reading | Deferred beyond required M5, possible M6/later | Full Translation is not required for M5. | Non-decision preserved. |
| TTS | Current M4 broad Smart Reading | Deferred beyond required M5, possible M6/later | Full TTS is not required for M5. | Non-decision preserved. |
| summaries | Current M4 broad Smart Reading | Proposed M6 candidate | Evidence-backed AI output. | Candidate, not mandatory. |
| citation-backed Q&A | Current M4 broad Smart Reading | Proposed M6 candidate | Requires citations/evidence and safe no-answer behavior. | Candidate, not mandatory. |
| Flashcards | Current M4 Smart Reading OS | Proposed M6 candidate | Intelligence feature after Reader/content foundation. | Candidate, not mandatory. |
| Mind Map | Current M4 Smart Reading OS | Proposed M6 candidate | Intelligence/knowledge surface after evidence foundations. | Candidate, not mandatory. |
| AI Tutor | Current M4 Smart Reading OS | Proposed M6 candidate/later | Broad tutor requires provider, safety, and provenance policy. | Candidate, not mandatory. |
| RAG | Current M4 broad intelligence | Proposed M6/later decision | Retrieval-augmented intelligence needs evidence, vector, and policy decisions. | Deferred details. |
| semantic search | Current M4/M5 broad retrieval | Proposed M6 | Belongs with intelligence/retrieval infrastructure. | Not M5 lexical search. |
| Smart Archive | Current M5 | Proposed M7 | Archive should follow shared content and Reader MVP foundations. | Old M5 remains historical evidence. |
| production foundation | Cross-cutting concern in current M4/M5 | Horizontal requirements plus external pilot/commercial gate | Quality and release gates apply across milestones. | Does not create release authority. |

## 10. Proposed M4 — Structured Content / Structured Document Foundation

- **Name:** M4 — Structured Content / Structured Document Foundation.
- **Goal:** Establish the minimal shared content foundation between SPR and application projections:

```text
Structured Processing Result
  → Structured Content / Structured Document
  → projection boundary
```

- **Scope:** minimal content model; minimal accepted/versioned snapshot or SCV approach; canonical/selected lifecycle; SPR-to-content assembly; Structured Document assembly; evidence and asset anchors; source/provenance traceability; recovery propagation; compatibility adapter; legacy migration rule; deterministic tests; and a ProcessingRun decision.
- **Explicit non-goals:** full Reader UI; full Speed Reading; durable Notes product; Flashcards; Mind Map; AI Tutor; RAG; semantic search; Translation/TTS completion; Smart Archive; commercial release.
- **Inputs:** retained Source Evidence, Storage references, Processing Provider results, Raw Processing Result, SPR v1, recovery diagnostics, architecture constraints, and existing Reader compatibility behavior.
- **Outputs:** selected minimal Structured Content / Structured Document foundation, projection boundary definition, compatibility adapter behavior, migration condition for legacy paths, and deterministic validation evidence.
- **Measurable exit criteria:** SPR-to-content assembly is deterministic for representative fixtures; canonical/selected lifecycle is documented; projection boundary is documented; recovery state propagates into content/projection; evidence and asset anchors are traceable; compatibility adapter is explicitly noncanonical; legacy migration rule is recorded; ProcessingRun persistence is decided; tests cover success, partial, and degraded cases.
- **Open design decisions:** SCV versus accepted snapshot; minimal content-version lifecycle; exact canonical/selected-content model; exact projection boundary; legacy compatibility path; whether minimal ProcessingRun persistence is required; whether any durable Observation persistence is needed; exact asset schema.
- **Production minimum:** migrations where storage changes are introduced; deterministic tests; safe failure behavior; cleanup; logging; provenance; access-boundary assumptions; no secret leakage; compatibility/migration plan; documented limitations.
- **Principal risks:** over-designing schemas before application needs are proven; allowing Reader serialization to become durable content; under-specifying deletion or ownership; coupling provider-specific output to canonical content; making Observation persistence too heavy too early.

## 11. Proposed M5 — Reader MVP

- **Goal:** Deliver a stable Reader MVP over the M4 projection boundary without making Reader presentation the canonical content model.
- **Key scope:** general Reader behavior; basic Speed Reading; Reader projection/API; navigation; image/table behavior; Recovery Presentation; lexical search; reading, revisit, reopen, and delete state; compatibility behavior; optional Notes/highlights only if anchors, identity, ownership, and retention/deletion behavior are adequate.
- **Technical-demo bridge restrictions:** a temporary SPR-to-Reader bridge is permitted only as a noncanonical adapter, isolated behind a projection boundary, governed by a documented migration condition, and prohibited from becoming the durable content model.
- **Non-goals:** Flashcards; Mind Map; AI Tutor; RAG; semantic search; full Translation/TTS; Smart Archive; final AI/provider choices; external pilot unless the gate is explicitly satisfied.
- **Exit criteria:** Reader can consume projection/API output consistently; navigation is deterministic; image/table behavior is documented; Recovery Presentation is user-visible and traceable to recovery state; lexical search works over Reader-visible content; read/revisit/delete behavior is tested; compatibility path and migration condition are documented; optional Notes/highlights, if included, satisfy anchor and ownership requirements.
- **External-pilot gate:** M5 may be demonstrated internally without passing the external gate, but any external pilot or commercial use requires the separate gate in Section 14.
- **Deferred decisions:** exact Reader API shape, final projection serialization, complete notes/highlights product model, auth provider, final retention/privacy policy, and deployment target.

## 12. Proposed M6 — Smart Reading Intelligence

- **Goal:** Add a selected subset of evidence-backed Smart Reading intelligence after shared content and Reader MVP foundations are stable.
- **Candidate priority order:** 1. evidence-backed chapter summaries; 2. citation-backed document Q&A; 3. Flashcards; 4. Mind Map; 5. broader AI Tutor. This order does not make every item mandatory.
- **Key scope:** citations/evidence; generated-content provenance; provider/model/prompt/config versioning; semantic search; cost controls; privacy/security; safe no-answer/failure behavior; selected-feature tests and documentation.
- **Explicit non-goals:** completing every candidate; uncited RAG; broad AI Tutor without safety gates; final provider matrix; final vector store; final document-type matrix; Smart Archive ownership of content.
- **Selected-feature exit criteria:** each selected feature must cite source evidence where claims are made; record generated-content provenance; handle unavailable answers safely; enforce cost/usage bounds; document provider/model/prompt/config versions; avoid secret leakage; include deterministic or fixture-based tests where feasible.
- **Deferred decisions:** complete M6 feature set, AI provider, provider matrix, vector store, prompt/versioning policy details, semantic index implementation, privacy/security controls beyond milestone minimum, and document-type coverage.

## 13. Proposed M7 — Smart Archive

- **Goal:** Build Smart Archive as a peer application over shared Structured Content, provenance, metadata, lifecycle, retrieval, and evidence foundations.
- **Key scope:** collections/folders; archive metadata and lifecycle; retrieval; cross-document evidence; archive workflows; retention/deletion integration; optional future split into Archive Foundation and Archive Intelligence if scope warrants.
- **Explicit non-goals:** owning canonical content; duplicating Reader content models; consuming provider JSON as archive truth; creating uncited cross-document RAG; bypassing retention/deletion policy; deciding the later split now.
- **Exit criteria:** archive items can be organized and retrieved through documented metadata/lifecycle behavior; cross-document surfaces cite evidence; archive workflows respect ownership and retention/deletion; Smart Archive consumes shared content/provenance rather than redefining it; limitations and future split decision are documented.
- **Deferred decisions:** M7 split, exact archive schema, retrieval indexes, cross-document intelligence scope, retention/privacy policy, deployment target, and external release path.

## 14. Production and commercial readiness policy

This policy has two layers. Neither layer creates release status automatically.

### Horizontal milestone requirements

Each milestone that changes runtime or durable behavior should address migrations, deterministic tests, failure behavior, cleanup, logging, provenance, access boundaries, no secret leakage, compatibility/migration plan, and documented limitations.

### External pilot/commercial gate

External pilot or commercial release requires authentication, authorization, user or tenant ownership, durable status, retry/idempotency, secure storage/deployment, quotas, cost control, observability, backups, retention/deletion, security review, privacy expectations, and incident/failure recovery. Passing milestone exit criteria alone does not confer release authority.

## 15. Alternatives considered

- **Option A — minimal change:** Keep current M4 Smart Reading OS and M5 Smart Archive labels. This minimizes document churn and preserves familiar milestone names, but leaves M4 overloaded and keeps platform, Reader, and intelligence work mixed.
- **Option B — split platform/product:** Separate all platform work from all product work. This clarifies architecture dependencies, but may create too many abstract platform milestones and delay visible Reader progress.
- **Option C — delivery-stage decomposition:** Redefine M4 as Structured Content / Structured Document Foundation, define M5 Reader MVP, add M6 Smart Reading Intelligence, and move Smart Archive to M7. This is the owner-approved planning direction because it preserves history, keeps the project in M4, creates measurable delivery stages, and separates shared content from Reader, intelligence, and archive application work.

## 16. Consequences

### Positive consequences

- Reduces M4 overload while preserving the current milestone number.
- Makes M1–M3 historical status stable and understandable.
- Keeps old M4/M5 scope transfers visible.
- Establishes a clear boundary from SPR to Structured Content / Structured Document to projections.
- Prevents Reader streams, SPR, or archive-specific models from becoming canonical content by accident.
- Creates room for evidence-backed AI and external pilot/commercial gates.

### Negative consequences / trade-offs

- Requires a later decision record and roadmap update before repository authority changes.
- Adds M6 and M7 planning overhead.
- Defers final technical details such as schemas, APIs, provider, vector store, deployment, and retention policy.
- May delay some visible Smart Reading features in favor of shared foundations.
- Requires careful consistency audits to avoid stale references in product, architecture, and milestone documents.

## 17. Deferred decisions / non-decisions

Roadmap v3 does not decide final database schemas, final APIs, AI provider, vector database, deployment target, auth provider, final data-retention policy, or complete M6 feature set. Preserved non-decisions include SCV vs accepted snapshot; ProcessingRun model; Observation persistence; exact asset schema; exact Reader API; auth provider; deployment target; provider matrix; document-type matrix; vector store; final M6 feature set; M7 split; retention/privacy policy; exact archive schema; exact semantic index implementation; exact notes/highlights product model; full Translation/TTS scope; and external pilot timing.

## 18. Decision-readiness assessment

| Decision Area | Ready for Roadmap v3 Decision | Deferred Follow-up |
|---|---|---|
| M4–M7 structure | Yes: owner-approved delivery-stage decomposition is ready for formal decision. | Future roadmap/milestone edits after decision acceptance. |
| M4 redefinition | Yes: Structured Content / Structured Document Foundation is ready as proposed direction. | Exact schema, lifecycle, and ProcessingRun details. |
| M5 Reader separation | Yes: Reader MVP separation is ready as proposed direction. | Exact Reader API/projection and optional notes/highlights model. |
| M6/M7 creation | Yes: adding M6 Smart Reading Intelligence and M7 Smart Archive is ready as structure. | Complete M6 feature set and possible M7 split. |
| Smart Archive move | Yes: moving Smart Archive from current M5 to proposed M7 is ready as planning decision. | Archive schema, retrieval, and cross-document scope. |
| Production-gate policy | Yes: two-layer policy is ready as roadmap governance. | Exact security review process, auth provider, deployment target, quotas, backups, and retention/privacy policy. |
| Technical implementation details | No. | SCV vs snapshot, ProcessingRun, Observation, assets, APIs, provider matrix, document-type matrix, vector store. |

## 19. Proposed approval-to-update workflow

1. Merge this review/proposal record.
2. Create and approve Roadmap v3 decision record.
3. Update current roadmap and milestone index.
4. Redefine M4.
5. Rewrite M5.
6. Create M6 and M7.
7. Reconcile product/architecture references.
8. Run consistency audit.

Merging this review does not itself complete steps 2–8.

## 20. Validation and evidence basis

Primary sources inspected for this review include [roadmap.md](roadmap.md), [roadmap-v2-review.md](roadmap-v2-review.md), [roadmap-v2-decision.md](roadmap-v2-decision.md), [../milestones/README.md](../milestones/README.md), [../milestones/M3.md](../milestones/M3.md), [../milestones/M4.md](../milestones/M4.md), [../milestones/M5.md](../milestones/M5.md), [../project/document-governance.md](../project/document-governance.md), [../architecture/document-intelligence-platform.md](../architecture/document-intelligence-platform.md), [../architecture/document-core-information-model.md](../architecture/document-core-information-model.md), [../architecture/document-core-structured-content-architecture.md](../architecture/document-core-structured-content-architecture.md), [../architecture/recovery-presentation-architecture.md](../architecture/recovery-presentation-architecture.md), [../architecture/canonical-data-flow.md](../architecture/canonical-data-flow.md), [../contracts/structured-processing-result-v1.md](../contracts/structured-processing-result-v1.md), and [../contracts/reader-content-stream-v2.md](../contracts/reader-content-stream-v2.md).

Implementation inspection covered `app/models.py`, `app/processing/`, `app/routers/`, `app/book_service.py`, `alembic/`, and `tests/`. The inspected implementation supports a planning-evidence conclusion that `Document` and `SourceFile` foundations exist; Raw Processing Result retention exists; SPR runtime, normalization, and recovery support exist; durable Structured Content/SCV, canonical selection lifecycle, Smart Reading intelligence, and Smart Archive are not implemented; and Reader behavior currently uses legacy/compatibility paths. These observations are evidence for planning only, not automatic roadmap authority.

## 21. Review conclusion

Option C is ready for formal decision. Owner planning approval has been given for the Roadmap v3 proposal/review and decision-record workflow. The next repository authority step is a later accepted Roadmap v3 decision record, followed by authoritative roadmap and milestone updates. This review does not permit implementation work.
