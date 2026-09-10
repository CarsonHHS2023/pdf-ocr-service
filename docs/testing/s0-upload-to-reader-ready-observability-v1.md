# S0 upload-to-Reader-ready boundary proposal v1

| Field | Value |
|---|---|
| Document Type | Testing / Measurement boundary proposal |
| Approval Status | Proposed |
| Lifecycle Status | Active |
| Version | 1 |
| Date | 2026-09-09 |
| Scope | Canonical single-file PDF upload and its existing automatic first Reader open in one Staging Preview page |
| Backend source / runtime inspected | `a640cf07c0b3db8e0cade4950e4cc74af2ac0cfc` |
| Frontend source inspected | `a9d470c3609a94be45c525b47038d570c1855b01`, open frontend PR #86 |
| Current required metric | `upload_to_reader_ready_seconds = not_instrumented` |
| Related plan | [S0 closure plan](../plans/s0-observability-closure-plan-2026-08-25.md#61-next-decisions-and-remaining-instrumentation) |

## 1. Proposed decision

Define the first version as **client dispatch of one canonical upload through
successful initial core semantic rendering of that upload's exact candidate in
the same page**, measured by one browser monotonic clock. Proposed scope:
`canonical_single_upload_to_initial_semantic_render_v1`; proposed method:
`browser_same_context_elapsed_v1`.

This interpretation of the required metric needs review and explicit scope
acceptance before producer implementation or required-metric mapping. It does
not cover images finishing loading, asynchronous enhancement or browser paint.
If those are required for Reader-ready, retain the gap and design that separate
endpoint. No existing Reader acceptance is relabeled.

Single-file upload already opens its result automatically. Add observation and
identity proof to that path; do not change auto-open behavior, polling frequency,
selection, preloading, rendering or compute placement. This proposal installs no
runtime code. The companion [proposed wire contract](../contracts/s0-upload-reader-observation-v1.md)
now fixes headers, payloads, atomic admission and collector association; both
documents remain Proposed pending scope acceptance.

## 2. Inspected source and usable boundaries

Frontend [PR #86](https://github.com/CarsonHHS2023/speed-reading-trainer/pull/86)
is open and unmerged. Its SHA identifies inspected source, not a new Preview
deployment. Backend inspection includes its deployed durable-dispatch
composition, not only the uncomposed upload handler.

| Source boundary | What exists | Missing end-to-end proof |
|---|---|---|
| Backend upload observer / dispatch adapter | ASGI ingress through durable acceptance/task registration | Client dispatch precedes it; processing and Reader follow it |
| `BookShelf.handleFileUpload` | Canonical upload, status polling if needed, then automatic `selectBook` | No persisted shared upload/open root |
| Installed upload lifecycle poller | 5000 ms polling; distinct auth/network/failure outcomes | A completed poll is neither the precise processing terminal nor Reader-ready |
| `BookShelf.selectBook` | Invokes the Reader and catches errors | Its resolved promise alone cannot prove readiness |
| `ReaderV2Controller.openBook` / existing S0 settlement | Bounded data fetches, initial semantic render, synchronous final page notification | Its clock begins at open; binary/enhancement completion and paint are excluded |
| Backend Reader persistence | Resolves an exact candidate to its succeeded processing run | No upload-root binding or client upload-start clock |

Pinned source references:

- [Single/batch upload and selection](https://github.com/CarsonHHS2023/speed-reading-trainer/blob/a9d470c3609a94be45c525b47038d570c1855b01/bookshelf.js),
  [installed polling/cache lifecycle](https://github.com/CarsonHHS2023/speed-reading-trainer/blob/a9d470c3609a94be45c525b47038d570c1855b01/bookshelf-upload-lifecycle.js).
- [Reader controller](https://github.com/CarsonHHS2023/speed-reading-trainer/blob/a9d470c3609a94be45c525b47038d570c1855b01/reader-ui-v2.js),
  [Reader observer](https://github.com/CarsonHHS2023/speed-reading-trainer/blob/a9d470c3609a94be45c525b47038d570c1855b01/s0-reader-open.js),
  [accepted scope and exclusions](https://github.com/CarsonHHS2023/speed-reading-trainer/blob/a9d470c3609a94be45c525b47038d570c1855b01/docs/s0-reader-open-observability.md).
- [Upload observer](https://github.com/CarsonHHS2023/pdf-ocr-service/blob/a640cf07c0b3db8e0cade4950e4cc74af2ac0cfc/app/s0_upload_boundary_observability.py),
  [durable-dispatch adapter](https://github.com/CarsonHHS2023/pdf-ocr-service/blob/a640cf07c0b3db8e0cade4950e4cc74af2ac0cfc/app/s0_upload_durable_dispatch_compat.py),
  [Reader persistence](https://github.com/CarsonHHS2023/pdf-ocr-service/blob/a640cf07c0b3db8e0cade4950e4cc74af2ac0cfc/app/s0_reader_open_observability.py),
  [upload response schema](https://github.com/CarsonHHS2023/pdf-ocr-service/blob/a640cf07c0b3db8e0cade4950e4cc74af2ac0cfc/app/schemas.py).

The response supplies a document/book ID, not authoritative run/source identity.
Resolve that association from accepted dispatch and candidate state. Filename,
byte-size equality, the document's latest run or the latest Reader event is not
identity proof.

## 3. Clock, endpoint and eligibility

Start immediately before the existing canonical upload fetch, after FormData
preparation. Stop at successful core-open settlement, after initial content is
installed and synchronous final `emitPageChange` returns, with a still-matching
document/candidate and valid bounded first-open observation. Capture the endpoint
before telemetry publication. Do not time the outer upload/select promise: it
can swallow errors or include additional annotation/highlight work.

Subtract two `performance.now()` samples from the same Performance object.
Retain absolute samples locally; publish only a finite nonnegative duration,
bounded to 3600 seconds, with the method and scope. Timer resolution limits
remain applicable. The [W3C High Resolution Time draft, 2026-09-01](https://www.w3.org/TR/2026/WD-hr-time-3-20260901/)
distinguishes monotonic measurement from adjustable wall clocks and requires
common-clock endpoints. Do not subtract browser and Backend/Neon timestamps or
reconstruct a lost start with `Date.now()`.

Include the upload round trip, processing wait, existing polling/network delay,
normal selection work before core open, Reader requests and synchronous initial
rendering. Exclude file picking/FormData preparation, later interactions, binary
asset completion, asynchronous enhancements/annotations and paint. These are
elapsed-time boundaries, not CPU measurements.

Admit one active single-file operation in one page and its natural automatic
first open. The one-file delegation from `handleMultiFileUpload` is eligible;
an actual multi-file batch is not. Batch completion does not automatically open
every book, and a later manual selection must not consume a remembered last
upload.

Reload/navigation/page loss, hidden/frozen-page operation, overlap, a replaced
source/candidate, saved-position reopen, failed polling, failed/empty core open,
or invalid/expired clock evidence is unavailable for this v1 scope. Invalidate
the observation without cancelling business work. Keep only bounded scalar state,
never File objects/upload bodies or persisted clocks reused across pages.

## 4. Durable association and event ordering

Add a separate bounded `S0_UPLOAD_READER_*` protocol. Preserve the existing strict
Reader terminal and upload-acceptance field meanings.

1. The eligible Staging Preview creates a random opaque upload root immediately
   before dispatch. Dedicated allowlisted headers carry it and the exact frontend
   revision. They are correlation metadata, not credentials.
2. At the composed durable-acceptance seam, Backend resolves committed
   run/document/source identity and persists a proof containing the root, hashed
   source scope, canonical route and frontend/Backend revisions. Only successful
   proof persistence permits a matching acknowledgement header; existing business
   response bodies remain unchanged.
3. Validate that acknowledgement and the returned document ID, then bind the root
   to this automatic select/core-open invocation. Match its existing
   `open_scope_id`, candidate and Backend revision. Document identity alone does
   not allow manual or competing opens to acquire the root.
4. Successful local settlement sends one detached authenticated terminal POST
   with bounded root/open/candidate identity, revisions, method/scope and elapsed
   duration. Backend resolves the candidate's succeeded run and source and
   compares them with the acceptance proof. Duration is explicitly
   client-reported, not server-measured.
5. Final collection requires one acceptance and terminal root plus complete
   existing first-open Reader requests/terminal for the same open, candidate,
   run and revisions. It never selects the newest root.

Reader request/terminal rows may persist after the new terminal POST arrives.
Validate immutable association when accepting the new evidence; require the
complete durable join during final collection. Do not require network arrival
order or add repeated terminal POSTs/polls solely to wait for telemetry.

The [wire contract](../contracts/s0-upload-reader-observation-v1.md#4-durable-event-schema-and-atomic-admission)
fixes event names/field allowlists, headers, endpoint and duplicate/invalidation
handling for review before runtime code. Required limits: two normal root records (acceptance ordinal `0`, terminal
ordinal `1`) plus at most one exceptional invalidation record per run; each at
most 8192 UTF-8 bytes; terminal request body at most 2048 bytes. Enforce caps and
conflicting-root handling atomically. A count-then-insert race or unconditional
conflict-ignore must not conceal ambiguity.

Observation does not own ingestion tasks, leases or processing status. Do not
create fake Document/SourceFile/ProcessingRun rows for pre-acceptance failures.
No filename, title, content, source checksum, URL, token or raw storage reference
belongs in the payload. Keep existing authentication and Staging-only gating.
Observer failure never changes upload, polling, selection or Reader outcomes.

## 5. Collector admission

| Evidence | Proposed result |
|---|---|
| No new producer family | Required metric remains `not_instrumented` |
| Acceptance without matching terminal/Reader proof | `not_available`, no value |
| Conflicting/duplicate roots, ordinal gaps, invalidation or mixed identity/revision | `not_available`, no value |
| Malformed/oversized/unknown fields, truncated collection or invalid clock/scope | No complete `observed` result |
| Proposed endpoint not yet accepted, even if a prototype measures it | No required-metric promotion |
| Accepted scope, exact succeeded run, one complete eligible root and valid delta | Eligible for `observed` after exact-revision Staging acceptance |

Expose a method/scope/revision/eligibility breakdown alongside the duration.
Existing upload, lifecycle, canonicalization and Reader durations cannot be
summed into this metric: boundaries differ, gaps exist and intervals may contain
one another. Backend terminal-to-Reader time and full visible-page readiness need
separate scopes.

## 6. Next gate and verification

**2026-09-10 implementation follow-up:** the [candidate implementation](s0-upload-reader-implementation-2026-09-10.md)
now applies this semantic-ready boundary to the Backend and companion Preview.
Runtime acceptance and required-metric closure remain pending; the deployed
baseline is not changed by candidate tests.

Review the proposed semantic-ready scope together with the companion
[Backend/Preview protocol](../contracts/s0-upload-reader-observation-v1.md), then
prepare implementation against the accepted boundary. Keep frontend #86 unmerged:
its base is main and a merge would publish the Production Pages root. The
companion Preview must retain Staging-only backend/auth configuration and pin
both deployed revisions.

Future tests must cover the natural single-file flow, one-file delegation,
immediate-completed responses, valid first-open proof, swallowed Reader errors,
failed final notification, empty content and asynchronous assets/annotations
still pending at the declared endpoint. Also cover wrong identity/revision,
manual/overlapping opens, batches, hidden/page-loss/clock-expiry paths, observer
failures, atomic caps, duplicates, strict JSON/size/privacy checks and all
acceptance/Reader/terminal arrival orders. Composed off/on tests must preserve
business results, loading behavior and data-request counts without retaining
document buffers.

After implementation, exact-head CI, artifact verification and separately
authorized Staging/Preview deployment, use the cheapest fresh one-page PDF and
its existing automatic first open. This proposal requests no new upload.
The accepted visual run cannot retroactively acquire a missing upload clock.
Any medium follow-up needs an incremental coverage reason; TXT ingestion and
full visible readiness remain separate gates.

No producer, accepted scope revision, metric waiver, runtime acceptance or S1/S2
work is delivered by this proposal. All three required gaps remain open. S0 and
M5 remain In Progress; Production and 100-page/528-page runs are outside scope.
