# M5 Entry & Implementation Planning Review — Reader MVP

| Field | Value |
|---|---|
| Document Type | Review / Planning Evidence |
| Approval Status | Accepted |
| Lifecycle Status | Active |
| Review Date | 2026-07-24 |
| Baseline Commit | `f583c82181eebec41cb15422dc2733868f63180d` |
| Corrective Review Baseline | `ff5185a29e350c78e423937e5c0290e872dda5c8` |
| Related Milestone | [M5 — Reader MVP](../milestones/M5.md) |
| Related Handoff | [M4 to M5 Handoff](../handoffs/m4-to-m5-handoff.md) |
| Related Plan | [M5 Reader MVP Implementation Plan](../plans/m5-reader-mvp-implementation-plan.md) |
| Backend Repository | `CarsonHHS2023/pdf-ocr-service` |
| Frontend Repository | `CarsonHHS2023/speed-reading-trainer` |

## Executive decision

**M5 ENTRY AND IMPLEMENTATION PLAN ACCEPTED — READY FOR MILESTONE START / STATUS RECONCILIATION WITH NONBLOCKING DEFERRED DECISIONS.**

M4 remains Complete. M5 remains Planned. Slice 1 is Not Started and may begin
only after a separate M5 Milestone Start / Status Reconciliation merges.

Acceptance makes the decisions and bounded cross-repository plan authoritative
implementation-entry planning. It does not implement code, mark M5 In Progress,
authorize Reader cutover, migration/backfill/deletion, or authorize an external
pilot, production deployment, or commercial release.

## Review basis and scope

The review read documentation governance, M4/M5 milestone records, the M4
completion review and M4→M5 handoff, ADR-002 through ADR-005, the accepted
service-boundary ADR, Reader Content Stream v2, Recovery Presentation, canonical
data-flow and Document Core architecture, backend implementation/tests, and the
recorded source-level frontend inventory in `current-state-review.md`.

Direct shell cloning of `CarsonHHS2023/speed-reading-trainer` was retried on
2026-07-24 and failed with `CONNECT tunnel failed, response 403`. Therefore this
corrective review does not pretend to have a fresh checkout: its client baseline
uses the repository's 2026-07-11 review, which records a public GitHub web/raw
inspection of `README.md`, `index.html`, `app.js`, `bookshelf.js`, `style.css`,
and `.github/workflows`. That accepted architecture evidence is sufficient to
identify ownership and plan client work, but Slice 5 must revalidate the client
head before implementation.

Scope is planning/governance documentation only. No backend or frontend source,
test, route, schema, migration, or milestone/roadmap status is changed.

## Review finding dispositions

### P1 — RESOLVED

Both this review and its implementation plan are promoted from Proposed to
Accepted. Resolved implementation-entry decisions now have accepted planning
authority. M5 nevertheless remains Planned and Slice 1 still requires the
separate start/status reconciliation.

### P2 — RESOLVED

The actual frontend repository is identified and its recorded source inspection
is incorporated. M5 is explicitly cross-repository; ownership, a client
integration slice, two-repository Speed Reading and find work, client-level
accessibility, and backend-plus-frontend evidence for all applicable exit
criteria are now planned.

## M4 completion and handoff acceptance

M4 is Complete. Its handoff is accepted: explicit selected candidate identity,
candidate reconstruction, StructuredDocument, deterministic reading order,
page/node/heading identity, Reader v2 projection, recovery facts, evidence
anchors, logical assets/table refs, ProcessingRun provenance, legacy rules,
bounded errors, and deterministic rebuild semantics are available.

| M4 handoff item | Available? | M5 usage | Limitation | Blocking? |
|---|---|---|---|---|
| Selected `StructuredContentCandidate` identity | Yes | Version-bound open/location | Selection must exist | No |
| Candidate reconstruction | Yes | Reader service input | Bounded corruption errors | No |
| StructuredDocument | Yes | Application-independent assembly | Derived; no persisted sections | No |
| Deterministic reading order | Yes | Delivery, navigation, segments | Candidate-version scoped | No |
| Page/node/heading identity | Yes | Locations, headings, find | No silent cross-version stability | No |
| Reader v2 projection | Yes | Compatibility/parity only | Lossy and noncanonical | No |
| Recovery facts/warnings | Yes | User-safe mapped states | Separate from processing | No |
| Evidence anchors/provenance | Yes | Stable context and later M6 | Raw diagnostics remain hidden | No |
| Logical assets/table refs | Yes | Stable refs and degradation | Renditions not independently resolvable | No for Slice 1 |
| Legacy rules and bounded errors | Yes | Compatibility/error translation | No cutover authority | No |
| Deterministic rebuild | Yes | Avoid second canonical store | Cost requires measurement | No |

Neither repository may make provider JSON, Raw Processing Result, SPR,
`MineruResult`, `ContentBlock`, `PdfPage`, `BookImage`, Reader Content Stream v2,
transient URLs, local paths, or provider IDs canonical Reader content.

## Current backend Reader inventory

| Surface | Current source/payload | Current consumer/dependency | M5 disposition |
|---|---|---|---|
| `/api/v1/books/{book_id}/content` | PDF `MineruResult.result_json` or TXT processed file; `{content}` plain stream with image markers | Actual frontend `selectBook`; legacy `Document`, `MineruResult`, file path | RETAIN_TEMPORARILY |
| `/api/pdf/book-text/{book_id}` | `ContentBlock` page/block dictionaries | Legacy/inactive router tests; not found in actual client dependency map | DEPRECATE_LATER |
| `/api/pdf/book-images/{book_id}` | `BookImage` metadata dictionaries | Legacy/inactive router tests; not found in actual client dependency map | DEPRECATE_LATER |
| `/api/pdf/image/{image_id}` | `BookImage` metadata | Legacy/inactive router; client instead calls `/api/v1/images/{image_id}` | REPLACE_LATER |
| `/api/v1/images/{image_id}` | Stored image bytes by opaque legacy image ID | Actual frontend marker/image overlay | ADAPT |
| PDF path | Plain stream assembled from `MineruResult`; `$%$%$%id$%$%$%` assets | Actual frontend tokenizer | REPLACE_LATER |
| TXT path | `Document.processed_file_path` raw text | Actual frontend same content endpoint | VERSION |

The `/api/pdf/*` routes are not mounted by the default app according to the
reviewed backend evidence. They must not be mistaken for client-used target APIs.

## Current frontend inspection and inventory

The inspected client is static native JavaScript deployed without a package
manifest or npm build step. `index.html` is the single-page entry; `app.js` owns
reader/tokenization/display/timing/state; `bookshelf.js` owns `fetch` calls,
upload, listing, polling, selection, and deletion; `style.css` owns presentation.
There was no package-based frontend unit/e2e suite in the inspected listing.

| Client surface | Current implementation and dependency | Reuse potential | M5 disposition |
|---|---|---|---|
| Shelf/open | `BookShelf`; `/api/v1/books`, upload, detail polling, content, delete | REUSE shell | ADAPT to versioned open/content |
| General Reader | Focus and locally generated page modes over tokenized `result.content` | REUSE presentation ideas | ADAPT to ordered nodes/pages |
| API client/config | Direct `fetch`; hard-coded `https://carsonhhs-pdf-ocr-service.hf.space` | Limited | REPLACE with contract-aware/configurable boundary |
| Navigation | In-memory unit/page indexes and ratio progress; no backend location | Limited | ADAPT to `ReaderLocation` |
| Speed Reading | Focus/page loops; toggle, panel pause/resume, stop; speed timing | REUSE controls/timing ideas | ADAPT to deterministic segments/identity |
| Images/tables | Marker parsing, `/api/v1/images/{id}`, blocking overlay, rotate/flip | REUSE overlay | ADAPT to stable assets/captions/degradation |
| Loading/errors | Upload/poll status and terminal completed/failed handling | REUSE shell | ADAPT to all Reader states/errors |
| Recovery warnings | No M4 recovery-state presentation recorded | None | NOT PRESENT |
| Lexical find | No in-document find recorded | None | NOT PRESENT |
| Reopen/position | Reader state memory only; only theme persists | Limited | ADAPT for local versioned location |
| Keyboard/accessibility | No sufficient tested M5 keyboard/focus evidence recorded | None proven | ADAPT and prove in client tests |
| Frontend tests | No `package.json`, test script, or package-based suite recorded | None | NOT PRESENT; add in future frontend PR |
| Notes/highlights | Not implemented | None | DEFER |

### Exact current backend dependencies

The inspected client calls `GET /api/v1/books`, `POST /api/v1/upload`,
`GET /api/v1/books/{book_id}`, `GET /api/v1/books/{book_id}/content`,
`DELETE /api/v1/books/{book_id}`, and `GET /api/v1/images/{image_id}`. It does
not call the reviewed `/api/pdf/book-text`, `/api/pdf/book-images`, or
`/api/pdf/image` routes. It expects `result.content` as a string and the exact
`$%$%$%{image_id}$%$%$%` grammar. Book IDs drive polling, selection, and delete;
opaque marker IDs drive image fetch. These are compatibility facts, not target
canonical architecture.

### Existing Speed Reading behavior and gap

`selectBook` wraps legacy `result.content` in a browser `File`; tokenization is
deferred until start. `tokenizeContent` splits marker-delimited text into local
units. Focus mode batches units; page mode creates local pages; timing derives
from configured speed and effective character/page counts. Play/pause state,
indexes, slider progress, and elapsed time live in memory. Existing behavior has
start, pause, resume, stop, speed adjustment, and seek-like progress, but the
inspection did not prove distinct previous/next-segment keyboard controls.

It has no selected-candidate version, backend page/node identity,
`ReaderLocation`, stable segment identity, versioned return position, durable
reopen state, or frontend test evidence. Slice 6 must replace the permanent
legacy text bypass with versioned contract segments while preserving usable UI
ideas, synchronizing return-to-reader location, and handling loading/end/error
and keyboard behavior deterministically.

## Cross-repository target and responsibility

```text
pdf-ocr-service: Document → selected StructuredContentCandidate
→ StructuredDocument → derived Reader application view → versioned Reader API
                                               |
                                               v
speed-reading-trainer: Reader client → reading/navigation/recovery/assets
→ Basic Speed Reading → lexical find → reopen/revisit
```

The backend owns contract/content semantics, stable identities, bounded
delivery, status/recovery source mapping, assets, segments, find, errors,
location semantics, compatibility, and measurements. The frontend owns actual
rendering and interaction, recovery/asset/error presentation, navigation,
Speed Reading controls and synchronization, lexical-find UI, local revisit,
keyboard/focus/accessibility, integration, and internal demo evidence. Client
state remains noncanonical.

## Reader decisions

The application contract is the cross-repository boundary. It contains explicit
contract, document, and selected-candidate versions; `ReaderLocation` with page,
node, and optional segment; bounded content/navigation; recovery/processing
states; assets; find results; and bounded errors. Reader Content Stream v2 stays
a separately named compatibility serialization.

Pages are delivery containers, nodes stable units, headings derived navigation,
and segments deterministic sub-node views. Reopen is exact for unchanged
versions and stale for changed candidate/contract versions—never silently
migrated. Position is client-local/caller-provided initially. Search is
deterministic over supported headings/text/captions/formula/table text only.
Images/tables use stable asset refs, caption/context, and safe placeholders;
full semantic tables/renditions remain evidence-driven.

PDF targets the selected-content path and requires client integration proof.
TXT currently bypasses M4 and is transitional until it reaches the candidate
path or an explicit adapter; it is not yet claimed fully M5-conformant. Delivery
uses metadata/navigation plus bounded range/chunk/cursor content and lazy assets.
The client must support incremental/partial delivery rather than assume a full,
small document. No production SLA or Slice 1 projection cache is selected.

## Decision register

| ID | Decision | Status | Disposition |
|---|---|---|---|
| M5-DEC-001 | Thin application view from StructuredDocument and selected candidate | ACCEPTED FOR M5 IMPLEMENTATION | v2 stream compatibility-only |
| M5-DEC-002 | Metadata/navigation plus bounded content delivery | ACCEPTED FOR M5 IMPLEMENTATION | No monolithic-only API |
| M5-DEC-003 | Pages, stable nodes, derived segments | ACCEPTED FOR M5 IMPLEMENTATION | No persisted sections |
| M5-DEC-004 | Candidate/version-bound `ReaderLocation` | ACCEPTED FOR M5 IMPLEMENTATION | Optional segment identity |
| M5-DEC-005 | Heading-derived navigation/optional derived sections | ACCEPTED FOR M5 IMPLEMENTATION | Noncanonical |
| M5-DEC-006 | Deterministic, non-AI Speed Reading segments | ACCEPTED FOR M5 IMPLEMENTATION | Backend + client Slice 6 |
| M5-DEC-007 | User-safe recovery mapping separate from processing | ACCEPTED FOR M5 IMPLEMENTATION | No raw diagnostics |
| M5-DEC-008 | Stable asset refs/captions/safe degradation | ACCEPTED FOR M5 IMPLEMENTATION | Rich tables unresolved |
| M5-DEC-009 | Deterministic lexical find with locations | ACCEPTED FOR M5 IMPLEMENTATION | No embeddings/RAG |
| M5-DEC-010 | Version-bound reopen and explicit stale locations | ACCEPTED FOR M5 IMPLEMENTATION | No silent migration |
| M5-DEC-011 | Client-local/caller-provided position initially | ACCEPTED FOR M5 IMPLEMENTATION | Durable server state deferred |
| M5-DEC-012 | Notes/highlights | DEFERRED | Anchors retained |
| M5-DEC-013 | PDF selected path; TXT candidate path/transitional adapter | ACCEPTED FOR M5 IMPLEMENTATION | Claims require evidence |
| M5-DEC-014 | Bounded delivery and lazy assets | ACCEPTED FOR M5 IMPLEMENTATION | No SLA yet |
| M5-DEC-015 | No projection cache in Slice 1 | ACCEPTED FOR M5 IMPLEMENTATION | Measure first |
| M5-DEC-016 | Staged compatibility; no cutover authorization | ACCEPTED FOR M5 IMPLEMENTATION | DEC-019 gate preserved |
| M5-DEC-017 | Separate Reader cleanup, selection, canonical/source deletion | ACCEPTED FOR M5 IMPLEMENTATION | Destructive work deferred |
| M5-DEC-018 | Full semantic table/rendition policy | OPEN / REQUIRES EVIDENCE | Later asset evidence |
| M5-DEC-019 | Client repository and cross-repository ownership | ACCEPTED FOR M5 IMPLEMENTATION | Backend `pdf-ocr-service`; frontend `speed-reading-trainer`; combined completion evidence |

## Implementation slices and dependency graph

| Slice | Purpose / repositories | Depends on | Exit contribution |
|---|---|---|---|
| 1 | Backend contracts/application view | M4 handoff and M5 start reconciliation | 1,2,4,5,8,14,15,18,21 |
| 2 | Backend selected-content service | 1 | 1–4,8,10,15 |
| 3 | Backend bounded/versioned API | 1–2 | 1–5,12–15 |
| 4 | Backend navigation/recovery/assets | 1–3 | 4,5,7,8,15 |
| 5 | Frontend Reader integration | 1,3,4 | 1–5,7,8,13–15,17 |
| 6 | Both: deterministic segments and controls | 1–5 | 6,10,17 |
| 7 | Both: lexical find and result navigation | 1–5 | 9,17 |
| 8 | Both: reopen/lifecycle/local state | 1–7 | 3,10,11,15,16 |
| 9 | Both: legacy parity/readiness | 2–8 | 2,12,13,17,18 |
| 10 | Both: integration/scale/accessibility/demo | 1–9 | 3–10,13–21 |
| 11 | Cross-repository completion review/handoff | 1–10 | 18,20–22 |

A logical slice may have coordinated PRs in each repository tied to one contract
version. No PR is required to modify two repositories.

## M5 exit-criteria mapping

| # | Planned proving slices | Required reviewed evidence |
|---|---|---|
| 1 | 1–5 | Backend contract/service plus frontend API consumption |
| 2 | 1,2,5,9 | Backend forbidden-dependency tests plus frontend dependency inspection/tests |
| 3 | 2,3,5,8,10 | Backend API and frontend repeat-open/read user flows |
| 4 | 1,2,4,5,10 | Backend deterministic order plus frontend render order |
| 5 | 1,3–5,10 | Backend location/navigation plus frontend navigation behavior |
| 6 | 6,10 | Backend deterministic segments plus frontend minimum-control tests |
| 7 | 4,5,10 | Backend asset contract plus frontend render/degrade tests |
| 8 | 1,2,4,5,10 | Backend mapping plus frontend state presentation tests |
| 9 | 7,10 | Backend deterministic matches plus frontend result navigation |
| 10 | 2,6,8,10 | Backend stale/version behavior plus frontend revisit/return behavior |
| 11 | 8,10 | Backend lifecycle tests plus client-visible removal behavior where applicable |
| 12 | 9,11 | Backend/client compatibility matrix and parity evidence |
| 13 | 3,5,9,10 | Backend and frontend PDF/TXT support evidence, limitations explicit |
| 14 | 3,5,10 | Bounded API, client incremental/lazy behavior, measurements |
| 15 | 1,3–5,8,10 | Backend error contract plus frontend loading/error/state integration tests |
| 16 | 8,11 | Accepted deferral record (or later safe implementation evidence) |
| 17 | 5–10 | Required product tests in both repositories |
| 18 | 1,9,11 | Plan, compatibility review, and completion limitations |
| 19 | 10,11 | Controlled integrated backend/frontend demo; no release inference |
| 20 | 10,11 | Completion-review external-claim gate wording |
| 21 | 1,5,10,11 | Stable contract/location, integrated consumption, M5→M6 handoff |
| 22 | 11 | Reviewed completion evidence before completion status change |

Product-facing criteria cannot be proven by backend tests alone. In particular,
general reading, navigation, Speed Reading controls, assets, recovery, find,
revisit, errors/loading, and accessibility require frontend evidence.

## Accessibility and client evidence

Slice 10 must verify semantic headings, keyboard navigation, visible focus,
keyboard-operable Speed Reading controls, meaningful labels, image alt/caption
behavior, non-color-only recovery/warnings, loading/error focus behavior, and
readable degraded messaging in the actual client. Backend API tests are
insufficient. The integrated technical demo is evidence only and cannot imply
external, production, or commercial readiness.

## Compatibility, lifecycle, and gates

Compatibility proceeds through additive backend delivery, opt-in client
integration, parity comparison, and product evidence. Cutover requires separate
authorization. Migration/deprecation requires DEC-019 and separate
authorization. Reader-visible removal, derived cache cleanup, selection removal,
canonical candidate deletion, and source evidence deletion remain distinct.

DEC-019 is not an additive implementation blocker but remains the destructive
execution gate. DEC-020 remains open/evidence-driven: bounded behavior and
measurements are M5 work, while Slice 1 has no production SLA. Frontend caches
must be version-aware and noncanonical just as any later backend projection
cache must be rebuildable and version/policy keyed.

## Blocking, nonblocking, and deferred findings

No blocker prevents accepted planning or future backend Slice 1 **after** M5
status reconciliation. The frontend repository is known; client integration is
not a Slice 1 blocker, but it is mandatory before product-facing criteria and
M5 completion.

Nonblocking findings are the need to revalidate the frontend head, adapt its
hard-coded backend/legacy grammar, establish frontend tests, prove assets,
migrate TXT, and measure large documents. Deferred/open items are
Notes/highlights, durable server position, rich semantic tables/renditions,
projection caching, final cutover/deprecation, destructive migration/backfill,
and final production performance policy.

## Milestone status and next task

M4: Complete

M5: Planned

The required next governance task is **M5 Milestone Start / Status
Reconciliation**. That separate task may change M5 from Planned to In Progress.
Only after it merges may Slice 1 begin.
