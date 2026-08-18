# Roadmap v3 Decision — Delivery-Stage Decomposition for M4–M7

Structured Content, Reader MVP, Smart Reading Intelligence, and Smart Archive

> **Accepted decision notice:** This document records the accepted Roadmap v3 decision for Atlas. It establishes the approved M4–M7 milestone sequence, redefines current M4, records scope transfers from the former M4/M5 plan, and authorizes subsequent roadmap and milestone-document updates. It does not itself update those files, authorize implementation, approve release, or declare production readiness.
>
> The current roadmap and milestone files may remain temporarily stale until staged follow-up reconciliation is merged. That temporary lag does not invalidate this accepted decision. This accepted decision is authoritative for Roadmap v3 sequencing and scope decomposition, while the current files remain useful as historical/current pre-update records.

| Field | Value |
|---|---|
| Document Type | Roadmap Decision Record |
| Approval Status | Accepted |
| Lifecycle Status | Active |
| Effective Date | 2026-07-20 |
| Decision Outcome | Accepted |
| Authority Domain | Roadmap v3 milestone sequencing, M4–M7 scope decomposition, scope transfers, and forward delivery policy |
| Applies To | Atlas roadmap after completed M1–M3 |
| Related Roadmap v3 Review | [roadmap-v3-review.md](roadmap-v3-review.md) |
| Related Current Roadmap | [roadmap.md](roadmap.md) |
| Related Roadmap v2 Review | [roadmap-v2-review.md](roadmap-v2-review.md) |
| Related Roadmap v2 Decision | [roadmap-v2-decision.md](roadmap-v2-decision.md) |
| Related Milestone Index | [../milestones/README.md](../milestones/README.md) |
| Related Governance | [../project/document-governance.md](../project/document-governance.md) |

## 1. Decision

Roadmap v3 Option C is Accepted. Atlas adopts delivery-stage decomposition for M4–M7:

- M4 — Structured Content / Structured Document Foundation;
- M5 — Reader MVP;
- M6 — Smart Reading Intelligence;
- M7 — Smart Archive.

This decision preserves the reconciled historical status of M1, M2, and M3; keeps the project in M4; redefines M4 rather than closing or cancelling it; moves Reader product scope to M5; moves selected Smart Reading intelligence scope to M6; and moves full Smart Archive scope from old M5 to M7.

## 2. Authority and effect

This decision governs Roadmap v3 milestone sequencing, M4–M7 scope decomposition, scope transfers from the former M4/M5 plan, horizontal milestone-quality expectations, and the forward policy for external pilot or commercial-readiness claims.

This decision authorizes subsequent documentation work needed to reconcile the current roadmap, milestone index, milestone files, and related references with Roadmap v3. It does not itself edit those files, declare that they already reflect Roadmap v3, or convert current temporarily stale wording into implementation authority.

This decision does not authorize code, schema, migration, API, deployment, provider, AI, security, privacy, release, external pilot, commercial, or production implementation. It also does not accept final architecture details outside this decision's declared roadmap domain.

Until follow-up reconciliation is merged, [roadmap.md](roadmap.md), [../milestones/README.md](../milestones/README.md), [../milestones/M4.md](../milestones/M4.md), and [../milestones/M5.md](../milestones/M5.md) may remain temporarily stale. They remain useful as current pre-update and historical records, while this decision is authoritative for accepted Roadmap v3 sequencing and scope decomposition.

## 3. Context

M1 remains the completed foundation milestone. M2 remains complete for the revised Raw Processing Result boundary, meaning it retained provider-specific Raw Processing Result evidence and moved provider-independent interpretation forward. M3 remains complete for revised scope, ending at Structured Processing Result v1, provider-independent normalization, deterministic validation, recovery semantics, diagnostics, fixture evidence, and provider-conformance support rather than durable Structured Content.

The current M4 plan became overloaded because the former Smart Reading OS milestone combined post-M3 platform work, Structured Content, Structured Document assembly, Reader projection, Recovery Presentation, Speed Reading, Notes, Flashcards, Mind Map, AI Tutor, RAG, semantic search, and production concerns. The current M5 Smart Archive timing was premature because a full archive application should depend on shared Structured Content, provenance, evidence, ownership, lifecycle, retrieval, and deletion foundations rather than owning or duplicating content truth.

The project owner approved the Roadmap v3 planning direction recorded in [roadmap-v3-review.md](roadmap-v3-review.md). That review remains proposed planning evidence and did not replace the current roadmap or authorize implementation. This decision converts the approved planning direction into an accepted roadmap decision within the limited authority domain stated above.

## 4. Accepted milestone sequence

| Milestone | Accepted Name | Decision Status | Qualification |
|---|---|---|---|
| M1 | Preserve current historical name/status | Complete | Historical record remains unchanged; no retroactive rename or rescope. |
| M2 | Preserve current historical name/status | Complete | Complete for the revised Raw Processing Result boundary. |
| M3 | Preserve official historical name/status | Complete for revised scope | Completed SPR v1 and related revised-scope processing foundation; durable Structured Content and Reader-facing work remain downstream. |
| M4 | Structured Content / Structured Document Foundation | In Progress | Current milestone is prospectively redefined; milestone files may not yet be reconciled. |
| M5 | Reader MVP | Planned | Future Reader product milestone over the M4 content/projection boundary. |
| M6 | Smart Reading Intelligence | Planned | Future selected evidence-backed intelligence milestone; not every candidate is mandatory. |
| M7 | Smart Archive | Planned | Future archive peer application over shared Structured Content, provenance, and evidence foundations. |

Milestone statuses in this table are accepted roadmap sequencing decisions only. This table does not claim that existing milestone files have already been reconciled.

## 5. M4 redefinition

The project remains in M4. Roadmap v3 redefines M4 from the former overloaded Smart Reading OS milestone into the Structured Content / Structured Document Foundation milestone. This is a prospective scope redefinition of the current milestone, not a declaration that the former M4 was completed, failed, cancelled, or obsolete.

M4 is narrowed to the actual post-M3 platform frontier: converting Structured Processing Result evidence into shared Structured Content / Structured Document foundations and defining the projection boundary needed by later applications. Reader product behavior and product intelligence move later. No M3.5 is created.

## 6. Accepted scope-transfer ledger

| Scope | Previous Roadmap Location | Accepted Roadmap v3 Location | Decision Rationale | Historical Treatment |
|---|---|---|---|---|
| Structured Content | Old/current M4 inherited from M3 | M4 | Shared content foundation must precede Reader, intelligence, and archive applications. | Old descriptions remain historical evidence. |
| SCV/versioning or accepted snapshot | Old/current M4 platform frontier | M4 decision | Minimal lifecycle must be resolved before durable downstream use. | Prior SCV language remains historical, not final schema authority. |
| canonicalization | Old/current M4 platform frontier | M4 decision | Accepted/selected content policy must precede canonical consumers. | Historical canonicalization plans are not silently accepted as final. |
| Structured Document | Old/current M4 platform frontier | M4 | Application-independent assembled document boundary is required. | Prior placement remains traceable. |
| ProcessingRun decision | Old/current M4 open platform concern | M4 decision | M4 must decide whether minimal durable ProcessingRun persistence is required. | Not predetermined by this decision. |
| Observation decision | Old/current M4/SPR evidence concern | M4 deferred or minimal decision | Durable Observation persistence is not automatically required. | Runtime SPR observations remain distinct from durable rows. |
| evidence/assets | M3 runtime evidence and old/current M4 durable frontier | M4 | Anchors and provenance support projections and later AI. | M3 evidence completion remains preserved. |
| projection boundary | Old/current M4 | M4 | Separates canonical/selected content from Reader presentation and compatibility. | Bridge constraints remain visible. |
| Reader API | Old/current M4 Smart Reading OS | M5 | Reader API is product delivery over the projection boundary. | Old M4 combined scope remains historical evidence. |
| Reader serialization | Old/current M4 compatibility | M5 | Reader stream formats are projection/presentation formats, not canonical content. | Historical compatibility remains useful. |
| Recovery Presentation | Old/current M4 | M5, with M4 recovery propagation | User-facing recovery belongs in Reader; source recovery facts propagate from M4. | Prior M4 recovery work remains contextual. |
| navigation | Old/current M4 Reader scope | M5 | Navigation is Reader MVP behavior. | Transfer recorded without retroactive rewrite. |
| image/table behavior | Old/current M4 content and Reader scope | M4 anchors plus M5 presentation | Foundation owns anchors; Reader owns display behavior. | Split preserves historical combined scope. |
| lexical search | Old/current M4 broad Smart Reading | M5 | Lexical search is basic Reader utility. | Not treated as semantic AI scope. |
| speed reading | Old/current M4 Smart Reading OS | M5 basic Speed Reading | Basic speed reading belongs in Reader MVP; fuller product expansion is later. | Old scope is narrowed, not erased. |
| notes/highlights | Old/current M4 Smart Reading OS | Optional M5 | Optional only with anchors, identity, ownership, and retention/deletion behavior. | Not mandatory M5 scope. |
| Translation | Old/current M4 broad Smart Reading | Deferred beyond required M5, possible M6/later | Full Translation is not required for M5. | Non-decision preserved. |
| TTS | Old/current M4 broad Smart Reading | Deferred beyond required M5, possible M6/later | Full TTS is not required for M5. | Non-decision preserved. |
| chapter summaries | Old/current M4 broad Smart Reading | M6 candidate | Evidence-backed generated intelligence should follow shared content and Reader. | Candidate, not mandatory. |
| citation-backed Q&A | Old/current M4 broad Smart Reading | M6 candidate | Requires evidence, retrieval, safe no-answer behavior, and provenance. | Candidate, not mandatory. |
| Flashcards | Old/current M4 Smart Reading OS | M6 candidate | Learning intelligence depends on evidence-backed content foundations. | Candidate, not mandatory. |
| Mind Map | Old/current M4 Smart Reading OS | M6 candidate | Concept surfaces belong after content, evidence, and Reader foundations. | Candidate, not mandatory. |
| AI Tutor | Old/current M4 Smart Reading OS | M6 candidate or later | Broader tutoring requires provider, safety, provenance, and cost decisions. | Candidate, not mandatory. |
| RAG | Old/current M4 broad intelligence | M6/later decision | Retrieval-augmented intelligence requires indexing, evidence, and privacy policy. | Details deferred. |
| semantic search | Old/current M4/M5 broad retrieval | M6 | Semantic search belongs with intelligence and retrieval infrastructure. | Distinguished from M5 lexical search. |
| Smart Archive | Old/current M5 | M7 | Archive should be a peer application after shared foundations and Reader MVP. | Old M5 remains historical evidence. |
| production foundation | Cross-cutting old/current M4/M5 concern | Horizontal quality requirements plus external pilot/commercial gate | Quality expectations apply across milestones without creating release authority. | No production-readiness claim is created. |

## 7. Accepted M4 boundary

M4 establishes the high-level Structured Content / Structured Document Foundation boundary between SPR and application projections. Accepted M4 scope includes:

- minimal Structured Content model;
- minimal content-version or accepted-snapshot lifecycle;
- canonical/selected-content distinction;
- SPR-to-content assembly;
- Structured Document assembly;
- evidence and asset anchors;
- provenance traceability;
- recovery propagation;
- projection boundary;
- compatibility path;
- legacy migration/deprecation decision;
- deterministic tests for success, partial, degraded, and compatibility behavior;
- ProcessingRun decision.

Exact database schemas, APIs, content-node shapes, canonicalization algorithms, projection representations, asset schemas, ProcessingRun schemas, and Observation persistence choices remain deferred.

## 8. Accepted M4 non-goals

M4 does not include full Reader UI, full Speed Reading product, durable Notes product, Flashcards, Mind Map, AI Tutor, RAG, semantic search, Translation/TTS completion, Smart Archive, or general external/commercial release.

## 9. Accepted M5 boundary

M5 is Reader MVP. Accepted M5 scope includes general reading, basic speed reading, stable Reader projection/API behavior, navigation, image/table behavior, Recovery Presentation, lexical search, reopen/revisit/delete behavior, and compatibility behavior over the M4 projection boundary.

Notes/highlights remain optional M5 scope and require adequate anchors, identity, ownership, and retention/deletion behavior. M5 excludes the full M6 intelligence suite, including Flashcards, Mind Map, AI Tutor, RAG, semantic search, full Translation, and full TTS.

## 10. Accepted temporary bridge policy

A temporary SPR-to-Reader bridge is permitted only if it is explicitly noncanonical, isolated behind a projection boundary, governed by a documented migration condition, prohibited from becoming canonical persistence or the durable content model, and removed or migrated after the M4 content boundary is available.

## 11. Accepted M6 boundary

M6 contains selected evidence-backed Smart Reading intelligence only. Semantic search belongs in M6, with exact implementation deferred.

The accepted candidate priority order for later M6 scope selection is:

1. evidence-backed chapter summaries;
2. citation-backed document Q&A;
3. Flashcards;
4. Mind Map;
5. broader AI Tutor.

This is a candidate priority order. It does not authorize or require all five features, and final selected features require later M6 planning.

Future M6 scope decisions must address evidence/citations, generated-content provenance, model/prompt/config versions, retrieval/indexing, cost controls, privacy/security, and safe no-answer/failure behavior.

## 12. Accepted M7 boundary

Smart Archive moves from old M5 to M7. M7 is a peer application over shared Structured Content, provenance, evidence, metadata, lifecycle, retrieval, and deletion foundations. It may later be split into Smart Archive Foundation and Smart Archive Intelligence, but that split is not decided now.

Smart Archive must not own canonical content, duplicate Reader models, or consume provider JSON or Reader serialization as archive truth.

## 13. Production and commercial-readiness policy

### Horizontal milestone quality requirements

Each milestone must address migrations where applicable, deterministic tests, failure behavior, cleanup, logging, provenance, access-boundary awareness, no secret leakage, compatibility/migration plan, and documented limitations.

### External pilot/commercial gate

External pilot or commercial use requires, at minimum, authentication, authorization, user or tenant ownership, durable/reliable processing status, retry/idempotency appropriate to the supported workflow, secure storage/deployment, provider quotas, cost controls, observability, backup/restore, retention/deletion policy, security review, privacy expectations, and incident/failure recovery expectations.

This gate is not a release-state label. Satisfying it does not automatically create release approval. Failure to satisfy it prohibits external pilot/commercial claims. Internal technical demos may precede it under controlled conditions.

## 14. Consequences

Positive consequences:

- M4 becomes a focused platform foundation instead of an overloaded platform/product/intelligence milestone.
- Reader behavior moves to a clearer M5 product milestone.
- Smart Reading intelligence moves to a later evidence-backed M6 milestone.
- Smart Archive moves to M7 as a peer application over shared foundations.
- Production and commercial claims are governed by explicit quality and gate requirements.
- Deferred architecture and provider decisions remain visible rather than being silently decided.

Negative consequences:

- Existing roadmap and milestone documents require follow-up reconciliation.
- Some previously expected M4 product features move later.
- Temporary compatibility bridges may be needed while M4 foundation work is completed.
- More explicit decision points are required before implementation can proceed.

## 15. Alternatives considered

- **Option A — minimal change:** Keep the current M4/M5 structure and clarify internal sequencing. This was not selected because it leaves M4 overloaded and keeps Reader, intelligence, platform, and production concerns entangled.
- **Option B — platform/product split:** Split platform foundation from product behavior but keep fewer milestones. This was not selected because it improves the foundation/product boundary but does not clearly separate Reader MVP, Smart Reading intelligence, and Smart Archive sequencing.
- **Option C — delivery-stage decomposition:** Split M4–M7 into Structured Content / Structured Document Foundation, Reader MVP, Smart Reading Intelligence, and Smart Archive. Option C is Accepted because it best reflects dependency order while preserving historical roadmap evidence.

## 16. Deferred decisions and non-decisions

Roadmap v3 does not decide final database schemas, exact APIs, final SCV versus accepted snapshot approach, final canonicalization model, final content-node schema, ProcessingRun schema, durable Observation persistence, asset schema, final Reader API, exact Reader serialization, auth provider/model, deployment target, processing provider matrix, supported document types, AI provider, vector/index implementation, complete M6 feature set, exact M7 split, final retention/privacy policy, or final external-release plan.

## 17. Historical continuity

Roadmap v2 remains historical evidence through [roadmap-v2-review.md](roadmap-v2-review.md) and [roadmap-v2-decision.md](roadmap-v2-decision.md). [roadmap-v3-review.md](roadmap-v3-review.md) remains review/proposal evidence. Old M4/M5 definitions in [roadmap.md](roadmap.md), [../milestones/M4.md](../milestones/M4.md), and [../milestones/M5.md](../milestones/M5.md) remain historical pre-decision records until reconciled. M1, M2, and M3 are not retroactively renamed or re-scoped. Scope-transfer tables preserve the roadmap's evolution rather than rewriting Roadmap v2 as if Option C always existed.

## 18. Authorized follow-up documentation work

After this decision is merged, separately scoped documentation batches may:

1. update [docs/roadmap/roadmap.md](roadmap.md);
2. update [docs/milestones/README.md](../milestones/README.md);
3. redefine [docs/milestones/M4.md](../milestones/M4.md);
4. rewrite [docs/milestones/M5.md](../milestones/M5.md);
5. create `docs/milestones/M6.md`;
6. create `docs/milestones/M7.md`;
7. reconcile product/architecture references where required;
8. run a cross-document consistency audit.

These are documentation authorizations only. Each remains subject to exact-scope review. Implementation work is not authorized by this list.

## 19. Implementation authorization boundary

This decision establishes future delivery sequencing and milestone scope. It does not authorize code, schema, migration, API, deployment, provider, AI, or production implementation. Implementation begins only through separately reviewed milestone planning and implementation tasks.

## 20. Decision conclusion

Roadmap v3 Option C is Accepted. M4 is the current redefined Structured Content / Structured Document Foundation milestone. M5 Reader MVP, M6 Smart Reading Intelligence, and M7 Smart Archive are planned. The next action is current roadmap and milestone-index reconciliation. Implementation remains unauthorized.

## References

- [Roadmap v3 Review](roadmap-v3-review.md)
- [Current Roadmap](roadmap.md)
- [Roadmap v2 Review](roadmap-v2-review.md)
- [Roadmap v2 Decision](roadmap-v2-decision.md)
- [Milestone Index](../milestones/README.md)
- [M1](../milestones/M1.md)
- [M2](../milestones/M2.md)
- [M3](../milestones/M3.md)
- [M4](../milestones/M4.md)
- [M5](../milestones/M5.md)
- [Documentation Governance](../project/document-governance.md)
- [Document Intelligence Platform](../architecture/document-intelligence-platform.md)
- [Document Core Information Model](../architecture/document-core-information-model.md)
- [Document Core & Structured Content Architecture](../architecture/document-core-structured-content-architecture.md)
- [Recovery Presentation Architecture](../architecture/recovery-presentation-architecture.md)
- [Canonical Data Flow](../architecture/canonical-data-flow.md)
- [Structured Processing Result v1 Contract](../contracts/structured-processing-result-v1.md)
- [Reader Content Stream v2](../contracts/reader-content-stream-v2.md)
