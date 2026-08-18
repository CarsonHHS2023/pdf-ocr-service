# M5 Reader MVP Implementation Plan

| Field | Value |
|---|---|
| Document Type | Implementation Plan |
| Approval Status | Accepted |
| Lifecycle Status | Active |
| Date | 2026-07-24 |
| Current Progress Overlay | 2026-08-15 — [M5 Progress Reconciliation](../reviews/m5-progress-reconciliation-2026-08-15.md) |
| Current Milestone Status | **In Progress** |
| Related Review | [M5 Entry & Implementation Planning Review](../reviews/m5-entry-planning-review.md) |
| Related Milestone | [M5 — Reader MVP](../milestones/M5.md) |
| Backend Repository | `CarsonHHS2023/pdf-ocr-service` |
| Frontend Repository | `CarsonHHS2023/speed-reading-trainer` |

> **Current-status notice (2026-08-15):** This plan remains the accepted authority for the M5 slice definitions, dependencies, decisions, non-goals, and evidence model. Its original 2026-07-24 entry-state statements that M5 was Planned and Slice 1 had not started are historical planning context, not current progress. A later Milestone Start / Status Reconciliation occurred, M5 is now **In Progress**, and implementation has advanced through multiple slices. Before starting new M5 work, read the [current M5 milestone record](../milestones/M5.md) and [2026-08-15 progress reconciliation](../reviews/m5-progress-reconciliation-2026-08-15.md). Do not restart completed slices merely because this plan records their original pre-implementation dependencies.

## Objective and authority boundary

This accepted plan defines bounded, cross-repository implementation slices for
M5 Reader MVP. `pdf-ocr-service` owns Reader content, service, and API behavior;
`speed-reading-trainer` owns the product/client reading experience. M5
completion evidence must aggregate reviewed evidence from both repositories. A
successful backend implementation alone cannot complete Reader MVP.

Acceptance approved the implementation-entry decisions, cross-repository
architecture, application-contract direction, and slice sequence. At the time
this plan was accepted, separately scoped implementation PRs were gated on a
later M5 Milestone Start / Status Reconciliation, and M5 was still Planned.
That entry gate has since been crossed. The historical acceptance boundary still
does not approve Reader cutover, migration/backfill/deletion, an external pilot,
production deployment, or commercial release. Current implementation progress
is governed by the linked M5 milestone record and progress reconciliation.

## Architecture and ownership

```text
CarsonHHS2023/pdf-ocr-service

Document
→ explicit selected StructuredContentCandidate       (canonical durable content)
→ StructuredDocument                                 (derived, deterministic)
→ Reader application view / projection               (derived, noncanonical)
→ versioned Reader API DTO                           (transport)
          |
          v
CarsonHHS2023/speed-reading-trainer

→ Reader client state                                (presentation, noncanonical)
→ general reading / navigation / Recovery Presentation
→ images and tables / Basic Speed Reading / lexical find / revisit
```

Neither product layer may treat provider JSON, Raw Processing Result, SPR,
`MineruResult`, `ContentBlock`, `PdfPage`, `BookImage`, Reader Content Stream v2
serialization, transient signed URLs, local filesystem paths, or provider block
IDs as canonical Reader content. Legacy routes are transitional compatibility
surfaces only.

### Backend responsibilities

The backend owns the application-view and `ReaderLocation` contracts and their
version; explicit selection, candidate reconstruction, StructuredDocument
assembly, and deterministic Reader service; metadata/open and bounded
page-range/chunk/cursor delivery; navigation metadata; recovery, processing,
and content-state source semantics; stable asset identity and image/table
delivery boundary; bounded product errors; deterministic Speed Reading segments
and lexical find with locations; stale-location behavior; compatibility/shadow
support; and backend scale measurements. It must not make client presentation
state canonical.

### Frontend responsibilities

The client owns document open/read flow; ordered heading/paragraph rendering;
page/heading and previous/next navigation; `ReaderLocation` consumption;
complete/partial/degraded Recovery Presentation; processing, unavailable,
failed, and loading states; image/table caption and safe degradation; lexical
find and result navigation; revisit and stale-location UX; local reading
position; Basic Speed Reading start, pause, resume, stop, speed, previous/next,
and return controls; keyboard interaction, visible focus, labels, and accessible
presentation; API integration; and internal Reader demonstration evidence. It
consumes the approved transport contract, never backend ORM/domain objects.

## Accepted decisions

- Use a thin Reader application view derived from selected M4 content and
  StructuredDocument. Reader Content Stream v2 remains compatibility-only.
- Give the new structured application contract its own explicit version; do not
  call it “Reader v2.” Coordinate version changes across both repositories.
- Deliver metadata/navigation separately from bounded page-range or
  cursor/chunk content, with lazy assets and explicit states.
- Address content by candidate-version-bound pages and nodes. Derive heading
  navigation and deterministic Speed Reading segments.
- Use `ReaderLocation` with document, candidate/version, schema/contract,
  page/node, and optional segment identity.
- Use user-safe recovery states separate from processing state; start assets and
  tables with stable references, captions/context, and safe degradation.
- Use deterministic lexical find only; use local/client reading position; defer
  Notes/highlights and durable user position.
- Target PDF through selected Structured Content. TXT must reach the same path;
  any adapter remains explicit and transitional.
- Use no projection cache in Slice 1. Legacy routes remain unchanged until
  parity evidence and separate authorization.

## Reader application contract

The cross-repository contract exposes its version, document and selected
candidate/version identity, `ReaderLocation`, metadata/navigation, bounded
content pages/chunks, Recovery Presentation and processing states, stable asset
identity, lexical-find results, cursors, and bounded error/loading categories.
The client must tolerate incremental content and assets and stale versioned
locations. Reader Content Stream v2 is a separately named compatibility
serialization, not this structured contract.

## Slice sequence

| Slice | Repository / Repositories | Implementation boundary | Dependencies | Non-goals |
|---|---|---|---|---|
| 1 — Reader Delivery Contracts and Application View | `pdf-ocr-service` | Immutable application contracts; `ReaderLocation`; document/page/chunk/node, recovery, navigation types; validation; contract version. | Accepted M4 handoff; M5 start/status reconciliation | No routes, DB, frontend change, cache, or cutover. |
| 2 — Reader Service over Selected M4 Content | `pdf-ocr-service` | Explicit selection, candidate reconstruction, StructuredDocument, application view, deterministic service. | Slice 1 | No legacy route replacement. |
| 3 — Reader API / Bounded Delivery | `pdf-ocr-service` | Opt-in/versioned API; metadata/open; navigation; bounded page-range/chunk/cursor content; errors/loading. | Slices 1–2 | No cutover or unbounded-only response. |
| 4 — Navigation + Recovery + Asset Backend | `pdf-ocr-service` | Page/heading navigation delivery; recovery mapping; stable asset refs; image/table boundary and degradation. | Slices 1–3 | No semantic-table promise without evidence. |
| 5 — Reader Client Integration | `speed-reading-trainer` | Consume new contract; open and render headings/paragraphs; navigation and locations; recovery/loading/errors; assets; keyboard/accessibility foundation. | Slices 1, 3, 4 | No cutover requirement or AI feature. |
| 6 — Basic Speed Reading | Both repositories | Backend deterministic segment identity/order/bounds and `ReaderLocation`; client start/pause/resume/stop, speed, previous/next, return, keyboard, loading/end behavior. | Slices 1–5 | No AI/adaptive coach or persisted generated segments. |
| 7 — Lexical Find | Both repositories | Backend deterministic supported-field matches/ranges/locations; client search, feedback/list, location navigation, safe no-match. | Slices 1–5 | No embeddings, semantic search, RAG, or durable index initially. |
| 8 — Reopen / Lifecycle / Delete Policy | Both as applicable | Reopen selected content; selected-candidate and stale-location behavior; Reader-visible removal; client-local position. | Slices 1–7 | No source deletion, migration, or backfill. |
| 9 — Legacy Shadow / Parity / Cutover Readiness | Both as applicable | Compare legacy/new behavior; compatibility matrix; remaining client dependencies; opt-in/versioned evidence; readiness assessment. | Slices 2–8 | No cutover, legacy deletion, or DEC-019 execution. |
| 10 — Integrated Reader Verification / Scale / Accessibility | Both repositories | Integrated general reading, navigation, recovery, assets, Speed Reading, find, reopen, errors, formats, bounded-delivery measurements, accessibility, controlled internal demo. | Slices 1–9 | No external-pilot, production, or commercial readiness claim. |
| 11 — M5 Completion Review and M5→M6 Handoff | Documentation/evidence across both repositories | Map final evidence to all 22 criteria, limitations, M6 handoff, later status reconciliation. | Slices 1–10 | No status change before completion evidence. |

Slice dependencies are intentionally acyclic. Slice 5 waits for the API and
navigation/recovery/asset contract. Slices 6 and 7 require the location contract
and client integration. Slice 8 requires backend API plus client state; Slice 9
requires implemented product behavior; Slice 10 integrates all prior work; and
Slice 11 reviews it.

## Cross-repository PR discipline

A logical slice may use coordinated, separately reviewed PRs rather than one PR
touching both repositories. For example, Slice 6 may have one backend PR and one
frontend PR tied to the same accepted contract version and evidence checklist.
Cross-repository dependency links and compatible contract fixtures are required.
The completion review aggregates commit, PR, test, and demo evidence from both.

## Client adaptation and compatibility

The inspected static client can reuse its document shelf/upload/polling shell,
focus/page presentation ideas, timing controls, image overlay, theme, and basic
play state. It must adapt the hard-coded `fetch` client, legacy plain-content and
marker parser, locally invented pages, in-memory indexes, control model, errors,
and asset handling to the new versioned contract and `ReaderLocation`.
Recovery UI, lexical find, stable-location navigation, durable headings, stale
location behavior, contract tests, and adequate accessibility evidence were not
present at the time this plan was written and required implementation. Their
current implementation/evidence status must be read from the 2026-08-15
reconciliation rather than inferred from this historical entry assessment.
Notes/highlights remain deferred unless a later accepted decision changes scope.

Migration phases are: (1) additive backend contract/service/API; (2) frontend
opt-in integration; (3) legacy/new comparison; (4) integrated product evidence;
(5) separately authorized cutover; (6) DEC-019-gated, separately authorized
legacy migration/deprecation. This plan approves none of phases 5–6.

## Large-document and cache behavior

The frontend must not assume a one-response document, immediate loading of all
pages, eager assets, or small node counts. It must support page-range/chunk/
cursor delivery, incremental loading, lazy assets, processing, and partial/
degraded content. M5 collects measurements without defining a production SLA.

No projection cache is required for Slice 1. A later backend cache must be
derived, version- and policy-keyed, invalidatable, rebuildable, tested, and
noncanonical. Any frontend cache must likewise be contract/candidate-version
aware and noncanonical.

## Test and evidence strategy

Backend slices require contract validation, forbidden-dependency, selected
content, bounded API, ordering/navigation/recovery, asset-degrade, segment,
find, location/reopen, compatibility, and scale tests. Frontend slices require
API contract/integration and user-flow tests for rendering, navigation,
recovery, assets, Speed Reading controls, find, revisit, loading/error, and
incremental delivery. Accessibility evidence must include semantic headings,
keyboard navigation, visible focus, keyboard-operable Speed Reading, meaningful
labels, image alt/caption handling, non-color-only warnings, loading/error focus,
and readable degraded messaging. Backend API tests alone are insufficient.

General-reading completion requires actual `speed-reading-trainer` evidence.
Backend API success alone cannot prove rendered reading, navigation UX, recovery
or asset presentation, keyboard/accessibility behavior, or Speed Reading
controls. Slice 10 supplies an integrated controlled demonstration plus tests;
a screenshot or one-time demo alone is insufficient.

Every PR runs repository-appropriate tests and lint/compile checks. Required CI
must pass in each affected repository. Slice evidence records exact contract
versions and commits.

## Dependencies and gates

- M4 selected-candidate, reconstruction, StructuredDocument, and projection
  services are the backend foundation.
- DEC-019 does not block additive M5 work but gates destructive migration,
  backfill, legacy deletion/deprecation, and canonical/source cleanup.
- DEC-020 remains evidence-driven. Slice 1 needs no production SLA; later slices
  measure bounded behavior without inventing size or throughput guarantees.
- Full semantic tables/renditions require later evidence. Notes/highlights,
  durable server position, projection cache, cutover, destructive migration,
  and final production performance policy remain deferred/open as recorded.

## Completion review sequence

After the implementation/evidence work represented by Slices 1–10, Slice 11
maps reviewed evidence from both repositories to all 22 milestone criteria,
records limitations and M5→M6 inputs, and prepares a separate completion-status
reconciliation. The current 2026-08-15 progress reconciliation is an
intermediate status overlay, not the final Slice 11 completion review. External
claims remain separately gated.
