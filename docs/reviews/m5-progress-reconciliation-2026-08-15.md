# M5 Progress Reconciliation — 2026-08-15

| Field | Value |
|---|---|
| Document Type | Progress Review / Reconciliation |
| Review Date | 2026-08-15 |
| Milestone | [M5 — Reader MVP](../milestones/M5.md) |
| Review Status | Accepted point-in-time reconciliation |
| Milestone Decision | **M5 remains In Progress** |
| Purpose | Correct stale “Slice 1 Not Started” status, map implementation evidence to the accepted M5 plan, identify remaining completion evidence, and connect M5 to the horizontal scalability track |
| Related Plan | [M5 Reader MVP Implementation Plan](../plans/m5-reader-mvp-implementation-plan.md) |
| Related Scalability Plan | [Scalable Processing Migration Plan](../plans/scalable-processing-migration-plan.md) |

## 1. Executive conclusion

The M5 milestone documentation is materially behind the implementation state.

The current milestone record still says Slice 1 is the next authorized task and remains Not Started. Repository history shows that the original backend Slice 1–4 sequence was implemented through PRs #153–#156, and subsequent backend/frontend work has advanced Reader v2, source-unit convergence, PDF/TXT canonical ingestion, semantic full-page presentation, visual assets, bounded client loading, Speed Reading, authentication/upload lifecycle, and PostgreSQL Reader performance.

However, this progress does **not** justify declaring M5 Complete today. The accepted plan requires a final evidence mapping across both repositories, including lifecycle/delete semantics, compatibility/cutover posture, supported-format claims, accessibility/integrated verification, and the separate external-pilot/commercial gate.

Decision:

> **M5 remains In Progress. Implementation has advanced far beyond Slice 1. The next governance task is no longer “start Slice 1”; it is to complete a formal M5 completion-evidence pass while continuing separately scoped product fixes and the horizontal scalability/reliability track.**

## 2. Evidence basis

This reconciliation uses the current repository state and merged PR history as of the review date. Important implementation evidence includes, but is not limited to:

### Backend

- PR #153 — M5 Slice 1 Reader application contracts and `ReaderLocation`.
- PR #154 — M5 Slice 2 Reader service over selected Structured Content.
- PR #155 — M5 Slice 3 bounded Reader API.
- PR #156 — M5 Slice 4 navigation/recovery/asset backend.
- PR #157 — durable asset rendition foundation.
- PR #163 and subsequent v2 work — source-unit/source-anchor convergence.
- PR #199 — Production PDF canonical ingestion through Modal -> raw result -> SPR -> Structured Content v2 -> selection.
- PRs #209/#211/#212 and follow-ups — PDF structure recovery, page presentation, and durable visual assets.
- PR #247 and later refinement work — candidate promotion/selection lifecycle improvements.
- PR #292 family and later merged state — TXT canonical ingestion convergence and real acceptance work.
- PRs #308/#314/#317 — PostgreSQL runtime/migration/replay readiness and integrated stabilization; Reader reconstruction was also optimized to avoid remote-database N+1 behavior.

### Frontend

- Reader v2 integration and semantic full-page PDF presentation are merged and have been iteratively tested on real documents.
- Basic Speed Reading has advanced through Line/Block/Page layout, deterministic playback controls, responsive measurement, paragraph presentation, and navigation fixes.
- Large-document client behavior includes bounded/incremental loading rather than a one-response whole-document assumption.
- Temporary authenticated access, authenticated Reader asset delivery, upload lifecycle hardening, polling bounds, and bookshelf fallback behavior are implemented.
- Lexical-find implementation/test evidence exists in the frontend, including `tests/reader-find.test.js`; the final M5 review still must verify that current behavior satisfies the original cross-repository location/contract requirement rather than treating the existence of a client test as automatic Slice 7 completion.

PR titles/bodies and individual tests are implementation evidence, not by themselves Milestone-completion proof. Final M5 completion still requires an explicit criterion-by-criterion review.

## 3. Original slice status reconciliation

| Slice | Accepted plan scope | 2026-08-15 reconciliation | Remaining work before completion claim |
|---|---|---|---|
| 1 — Reader Delivery Contracts / Application View | Versioned contracts, ReaderLocation, validation | **Implemented**; original implementation PR #153 merged and later v2 evolution exists | Confirm current v2 contract/version evidence in final review |
| 2 — Reader Service | Selected canonical content -> deterministic Reader view | **Implemented and evolved**; original PR #154 plus v2 source-unit work | Final forbidden-dependency/parity evidence |
| 3 — Reader API / Bounded Delivery | Metadata/navigation separate from bounded content | **Implemented and evolved**; original PR #155 plus Reader v2 bounded endpoints/client chunking | Record current endpoint/limit measurements in completion review |
| 4 — Navigation + Recovery + Asset Backend | Navigation, recovery, stable assets/tables | **Implemented and substantially evolved**; PRs #156/#157 and PDF presentation/visual work | Final supported image/table behavior and degraded-state matrix |
| 5 — Reader Client Integration | General reading, navigation, recovery, assets | **Substantially implemented** across frontend Reader v2/full-page work | Consolidated integrated user-flow/accessibility evidence |
| 6 — Basic Speed Reading | Deterministic segments and controls | **Substantially implemented**; extensive frontend Line/Block/Page/control work | Map current semantics to original exit criteria; integrated edge-case evidence |
| 7 — Lexical Find | Deterministic in-document find | **Implementation/test evidence exists; completion verification remains open** | Verify current backend/client scope, stable-location mapping, and accepted contract; frontend `tests/reader-find.test.js` is evidence but not sufficient alone |
| 8 — Reopen / Lifecycle / Delete Policy | Reopen, stale location, local position, Reader-visible removal | **Partial** | Reconcile delete semantics, shared-source retention, ownership, stale/reprocessed content behavior |
| 9 — Legacy Shadow / Parity / Cutover Readiness | Compatibility and cutover assessment | **Partial / heavily evolved** | Record current legacy dependencies, explicit cutover/deprecation posture, DEC-019 implications |
| 10 — Integrated Verification / Scale / Accessibility | Cross-repo product evidence and measurements | **Partial** | Formal integrated suite, accessibility evidence, large-doc/scale baseline, failure-state evidence |
| 11 — Completion Review / M5->M6 Handoff | Map all 22 criteria and record limitations | **Not complete** | This is now the primary governance/completion task |

## 4. M5 exit-criterion reconciliation

The following table is intentionally conservative. `Evidence exists` means implementation/review evidence is present but must still be assembled into the formal M5 completion package. `Partial/Open` means a material gap remains or current evidence has not been verified in this reconciliation.

| # | Criterion | Current assessment |
|---|---|---|
| 1 | Reader consumes approved Structured Content/Structured Document boundary | Evidence exists |
| 2 | Reader does not use provider JSON/Raw Result/SPR/legacy tables as canonical truth | Evidence exists; final dependency scan required |
| 3 | Supported document opens/reads repeatedly through stable behavior | Evidence exists on real PDF/TXT workflows |
| 4 | Ordering/hierarchy deterministic | Evidence exists |
| 5 | Navigation works for approved scope | Evidence exists; active bounded-TOC fixes show edge work continues |
| 6 | Basic Speed Reading uses stable content with minimum controls | Evidence exists; final criterion mapping required |
| 7 | Images/tables render or degrade safely | Evidence exists; supported-policy matrix still needs finalization |
| 8 | Recovery Presentation distinguishes relevant states | Evidence exists; final integrated mapping required |
| 9 | Lexical find deterministic and location-linked | Frontend implementation/test evidence exists; cross-repository contract/location verification remains open |
| 10 | Reopen/revisit deterministic for selected/current identity | Partial/evidence exists; final lifecycle review required |
| 11 | Delete/cleanup documented/tested without violating source retention | **Open/partial**; especially important with shared-content dedupe target |
| 12 | Legacy compatibility has retain/version/migrate/deprecate rule | Partial; current state must be documented |
| 13 | Supported document-type claims explicit/tested | PDF/TXT evidence exists; formal support declaration still required |
| 14 | Large docs avoid unbounded response assumption | Evidence exists in bounded backend/client loading; production scale values remain open |
| 15 | Failure/loading/unavailable states deterministic/user-safe | Evidence exists; integrated cross-repo evidence required |
| 16 | Notes/highlights deferred or safely implemented | Expected deferral must be explicitly reconfirmed |
| 17 | Tests cover selected Reader behaviors | Extensive evidence exists; final cross-repo inventory required |
| 18 | M5 limitations/non-goals documented | Evidence exists; update with current architecture limitations |
| 19 | Internal demo not confused with external readiness | Preserved; temporary access gate is not full multi-user readiness |
| 20 | External pilot/commercial claims remain gated | **Still gated** |
| 21 | M6 can consume stable foundations without changing canonical assumptions | Architecture direction supports this; final handoff review required |
| 22 | Completion evidence recorded before status -> Complete | **Not satisfied yet**; therefore M5 remains In Progress |

## 5. Material changes since the original M5 plan

The product has evolved in ways the July plan did not yet encode in detail:

1. **Source-unit architecture became real.** Reader/content processing is no longer accurately described as only a page-centric M5 implementation sequence.
2. **PDF canonical ingestion and visual presentation matured significantly.** Presentation-page routing, source rendering, visual assets, refinement, and Reader semantic full-page behavior now form a substantial production path.
3. **TXT canonical ingestion was added.** PDF/TXT now converge toward the same SPR/SCv2/Reader architecture rather than a permanent legacy TXT side path.
4. **Storage/database operational assumptions changed.** PostgreSQL-capable runtime and migration/replay tooling are now merged; remote-database query behavior has been optimized.
5. **Multi-user scalability is now an explicit architecture concern.** The next platform work cannot be described only as Reader UI polish; durable attempt state, object/artifact identity, compute scaling, network transfer, duplicate-document reuse, and ownership boundaries require a horizontal implementation track.

## 6. New horizontal scalability track

The accepted target direction is documented in:

- [Scalable Storage and Processing Architecture](../architecture/scalable-storage-and-processing-architecture.md)
- [Content-Addressed Artifacts and Duplicate Document Reuse](../storage/content-addressed-artifacts-and-document-reuse.md)
- [Processing Attempt and Artifact Manifest Contract v1](../contracts/processing-attempt-and-artifact-manifest-v1.md)
- [Scalable Processing Migration Plan](../plans/scalable-processing-migration-plan.md)

This work is **not M6 Smart Reading Intelligence scope**. It is horizontal infrastructure that supports reliable M5 completion, future M6/M7 load, and the external-pilot/commercial gate.

Future PRs should record both:

```text
Product Milestone: M5 / M6 / M7 / horizontal-only
Scalability Phase: S0..S9 / not applicable
```

This prevents roadmap drift while allowing infrastructure to progress when product milestones depend on it.

## 7. Immediate M5 actions

Before considering M5 Complete:

1. verify the existing lexical-find implementation/test evidence against the accepted cross-repository contract and stable-location requirement;
2. finish/reconcile Reader lifecycle/delete semantics, including future shared-source/artifact retention behavior;
3. produce a current legacy/parity/cutover inventory;
4. declare the supported PDF/TXT MVP matrix and known limitations;
5. collect integrated cross-repository Reader/Speed Reading/recovery/asset/loading/error evidence;
6. add an accessibility evidence pass;
7. record baseline large-document/Reader performance measurements (also S0 input);
8. explicitly defer Notes/highlights and durable user reading position if still out of scope;
9. map final evidence to all 22 criteria;
10. only then prepare a separate M5 completion-status reconciliation and M5->M6 handoff.

## 8. External-pilot gate remains separate

M5 product completion does not automatically mean multi-user/public/commercial readiness. The existing gate remains applicable, including authentication, authorization, user/tenant ownership, durable processing status, retry/idempotency, secure storage, quotas/cost controls, observability, backup/restore, retention/deletion, privacy/security review, and incident recovery.

The scalability plan directly advances several of these items but does not silently satisfy the gate.

## 9. Decision

**Accepted reconciliation:**

- M4 remains Complete.
- M5 remains **In Progress**.
- The statement “Slice 1 remains Not Started” is obsolete and must be removed from current milestone navigation/status text.
- Slices 1–6 have substantial implementation evidence; Slice 7 has implementation/test evidence but remains open for formal cross-repository completion verification; Slices 8–10 remain partial/open as recorded above.
- Slice 11-style completion evidence is now the primary milestone-governance task.
- Horizontal scalability work proceeds under a separate S0–S9 track and does not redefine M6/M7 product scope.
- No Reader cutover, destructive migration, external-pilot authorization, or Production infrastructure mutation is authorized merely by this documentation reconciliation.
