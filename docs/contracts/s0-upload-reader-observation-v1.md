# S0 upload-to-Reader observation protocol v1

| Field | Value |
|---|---|
| Document Type | Contract |
| Approval Status | Proposed |
| Lifecycle Status | Active |
| Version | 1 |
| Date | 2026-09-09 |
| Authority Domain | Proposed Staging observation wire format and collector admission |
| Scope | One canonical PDF upload and its automatic initial core semantic render in one Preview page |
| Supersedes | None |
| Related Milestones | S0 / M5, both In Progress |
| Related boundary | [Measurement boundary proposal](../testing/s0-upload-to-reader-ready-observability-v1.md) |

This fixes the proposed wire format for review; it installs no producer, endpoint
or collector mapping. The semantic-ready interpretation still needs explicit
acceptance. `upload_to_reader_ready_seconds` remains `not_instrumented`; the
current baseline remains 16/19 required metrics observed. Strong requirements
below describe proposed conformance, not an accepted or deployed contract.

## 1. Constants and identity

| Name | Exact value / validation |
|---|---|
| `protocol_version` | `s0_upload_reader_v1` |
| `measurement_scope` | `canonical_single_upload_to_initial_semantic_render_v1` |
| `measurement_method` | `browser_same_context_elapsed_v1` |
| `upload_scope_id` | `upr_` followed by 32 lowercase hexadecimal digits, generated from browser cryptographic randomness |
| `open_scope_id` | Existing Reader ID: `reader_` followed by 32 lowercase hexadecimal digits |
| `frontend_revision`, `backend_revision` | Exactly 40 lowercase hexadecimal digits; deployed source revisions, not branch names |
| `source_scope_id` | `source_` + full lowercase SHA-256 of the UTF-8 source-file ID, using the existing visual-observer convention |
| `candidate_scope_id` | Existing Reader convention: `candidate_` + first 16 lowercase SHA-256 hexadecimal digits of the UTF-8 candidate ID |
| `candidate_id` in request only | ASCII `[A-Za-z0-9_-]{1,255}`; must resolve to the exact candidate, document and run |
| `duration_seconds` | JSON number, finite, in `[0, 3600]`; booleans and numeric strings rejected |

Raw run/document/source identities belong in existing relational associations,
not free-text payloads. A root is keyed by **run plus upload scope**, not by its
random string alone. Hash equality is a correlation check, not authorization or
a replacement for relational identity. Source-ID hashing is not source-content
hashing; do not persist a source checksum.

The Backend revision comes from the deployed Staging revision marker. The
frontend revision comes from the existing exact Preview source marker. The
duration and frontend eligibility are client-reported observations; matching
headers do not cryptographically attest to a browser's code or clock.

## 2. Upload request and acknowledgement

Only the existing authenticated `POST /api/v1/upload` for an eligible single PDF
may carry these headers. Header names are case-insensitive; require exactly one
value of each, rejecting duplicate/comma-joined values for observation.

| Direction | Header | Value |
|---|---|---|
| Request | `X-Atlas-S0-Upload` | `upload_scope_id` |
| Request | `X-Atlas-S0-Upload-Frontend` | `frontend_revision` |
| Response | `X-Atlas-S0-Upload-Accepted` | The same `upload_scope_id`, only after acceptance proof commits |
| Response | `X-Atlas-S0-Upload-Revision` | The Backend revision in that proof |

Prepare FormData, eligibility state and headers before taking the start sample;
sample immediately before the existing upload fetch. Do not retain the File,
FormData or body in observer state. Do not change the upload body or response
schema. Invalid/missing observation metadata or a failed observer leaves the
business request intact and produces no acknowledgement.

At the installed durable-dispatch acceptance seam, resolve the already committed
document, source and exact processing-attempt/run reference. Persist ordinal 0
before adding acknowledgement headers to the normal successful response. A
ProcessingRun row need not exist yet; validate the committed dispatch and source
association, without creating placeholder rows. This proof is separate from
`S0_UPLOAD_ACCEPTANCE_MEASURED`; do not alter or retime that existing event.

Expose the two acknowledgement headers through the existing Staging CORS policy,
preserving its allowed origin and other exposed headers. Permit the request
headers in that policy without widening origins or weakening authentication.
An acknowledgement is correlation metadata, never a capability or access token.

The browser requires a successful normal upload response, matching root, valid
Backend revision and the response's document ID. Missing or mismatched proof
ends only observation. Neither immediate-completed responses nor polling may
substitute a guessed run, latest source, filename or size match.

## 3. Local handoff and terminal request

Keep one scalar observation in the same page. Its lifecycle is: started,
acknowledged, bound to the actual automatic core-open invocation, then settled
or invalidated. Each transition checks the same operation identity. Only the
automatic selection called by that upload may hand off the root. A manual open,
batch, remembered last upload or another call for the same document cannot
acquire it. One-file batch delegation remains eligible; multi-file batches do
not. An overlap before settlement invalidates the active measurement and does
not admit the competing operation.

Bind the handoff to the exact existing Reader observation and candidate. A
resolved `selectBook` promise is insufficient: that method catches Reader
errors. Stop inside successful core-open settlement, after initial nonempty
semantic content is installed and synchronous final `emitPageChange` returns.
Capture the shared settlement sample before publishing either Reader or upload
telemetry; separating validation from publication must preserve the existing
Reader schema and behavior. A thrown final notification cannot produce success.
Outer annotation/highlight wrappers and asynchronous assets remain excluded.

Require the existing observer's valid `first_open`, three completed bounded core
requests, no pending request, and matching document/candidate/revisions. Saved
position, empty/failed open, replacement, overlap, hidden/page-loss/freeze events
before settlement, or invalid/expired clock samples suppress the new terminal.
After settlement, later navigation does not retroactively invalidate the elapsed
interval. Use the same Performance object for both samples and round the delta
to at most six decimal seconds. Do not reconstruct a start after reload or claim
that this detects every OS sleep; elapsed time is not active CPU time.

Send at most one detached authenticated POST, with no telemetry retry or extra
polling, to:

`/api/reader/v2/documents/{document_id}/s0-upload-ready`

Require `Content-Type: application/json` (optional UTF-8 charset). The request
object has **exactly** these nine keys:

```text
protocol_version, measurement_scope, measurement_method,
upload_scope_id, open_scope_id, candidate_id,
frontend_revision, backend_revision, duration_seconds
```

Read at most 2048 body bytes before parsing; reject excess even without a valid
Content-Length. Reject invalid UTF-8, duplicate object keys, non-object JSON,
unknown/missing fields, nonfinite numbers and invalid types. Do not log the raw
body or invalid values. Client state contains no credential copy; use existing
authenticated fetch and its normal authentication-expiry behavior. Publication
failure must not show an upload/Reader failure or retry the business action.

Resolve the supplied candidate and path document to their exact succeeded run
and source. Require that run's ordinal-0 proof, matching root, hashed source,
frontend revision and current Backend revision. Do not require existing Reader
events to have arrived yet. Their complete proof is a collector gate.

| Terminal outcome | HTTP response |
|---|---|
| New terminal committed, or identical terminal already present and no invalidation | `204`, no body |
| Strict payload/header validation failure | `422`, bounded generic error |
| Body too large | `413` |
| Valid shape but unavailable/mismatched association, conflicting evidence or invalidated run | `409`, bounded generic error |
| Persistence/lock failure, including failed invalidation persistence | `503`, bounded generic error |
| Staging observation gate off | `404` |
| Authentication failure | Existing authentication response, unchanged |

## 4. Durable event schema and atomic admission

Use the existing ProcessingEvent envelope and schema version. All records carry
the resolved `processing_run_id`, `document_id`, `page_number = null`; normal
events have severity `info`, invalidation has severity `warning`. Each encoded
payload is at most 8192 UTF-8 bytes and must survive the existing sanitizer
unchanged. Reject unknown fields; never truncate a payload into validity.

The common payload keys are exactly:

```text
protocol_version, measurement_scope, measurement_method,
upload_scope_id, source_scope_id, frontend_revision, backend_revision,
ordinal, succeeded
```

| Event name | Ordinal | Additional exact keys | Constraints |
|---|---|---|---|
| `S0_UPLOAD_READER_ACCEPTED` | `0` | `upload_route` | `succeeded = true`; route is literal `POST /api/v1/upload` |
| `S0_UPLOAD_READER_TERMINAL` | `1` | `open_scope_id`, `candidate_scope_id`, `duration_seconds` | `succeeded = true` |
| `S0_UPLOAD_READER_INVALIDATED` | `2` | `reason` | `succeeded = false`; reason is `conflicting_acceptance` or `conflicting_terminal` |

Ordinals are integers, not booleans. Invalidation copies common identity from
the stored acceptance proof, never from conflicting input. There are at most
three records in this family **per run**, not three per submitted root. A valid
measurement has exactly ordinals `0,1`. Reserved invalidation slot `2` may follow
`0` without `1`; it is explicit rejection, never a complete contiguous success.
Local ineligibility needs no invalidation POST: absence of terminal keeps that
root unavailable.

Proposed PostgreSQL serialization uses the existing document row, which exists
before the run, in a short observer-owned transaction. Every writer in this
family locks that row with `SELECT ... FOR NO KEY UPDATE`, then reads all family
rows for the exact run, validates association and admits at most one new slot.
Use a new READ COMMITTED transaction, local `lock_timeout = '250ms'` and
`statement_timeout = '1000ms'`; timeout means observation failure with no retry.
Do not hold the lock while awaiting network, processing or Reader work. These
timeouts bound database statements, not total connection acquisition time.
Implementation must also use a bounded connection checkout and ensure detached
writers retain their transaction cleanup ownership.

This choice serializes cooperating writers without requiring a not-yet-created
run row. PostgreSQL documents that this row-lock mode conflicts with itself but
does not block key-share locks; it still can contend with business updates, so
off/on validation must measure that limitation. See [PostgreSQL row locks](https://www.postgresql.org/docs/18/explicit-locking.html#LOCKING-ROWS).

Use the deterministic ProcessingEvent ID:
`UUIDv5(NAMESPACE_OID, "s0_upload_reader_v1:" + run_id + ":" + ordinal)`.
The ordinal is its decimal string. This supplies a per-run slot constraint in
addition to serialization. Compare complete typed payload and envelope identity
when a slot exists; JSON key order and created timestamps are not evidence
differences. Booleans and numbers are never treated as interchangeable.

| Under-lock state | Admission |
|---|---|
| Empty run, valid committed PDF dispatch | Insert acceptance in slot 0 |
| Identical existing acceptance/terminal, no invalidation | Idempotent acknowledgement; append nothing |
| Different valid acceptance for the same run | Keep original proof; append slot 2 once; no acknowledgement |
| Valid acceptance, first matching terminal | Insert slot 1 |
| Same accepted root but a different valid terminal | Keep first terminal; append slot 2 once; return conflict |
| Missing proof, unrelated root or unresolvable association | Reject; do not poison another root |
| Existing invalidation | Never admit new success; append nothing |

A database unique-conflict is not unconditional success: roll back and report
observation failure unless an under-lock read has established identical evidence.
Never overwrite an event, count outside the lock, create fake business rows, or
depend on a process-local lock. Malformed existing family rows fail admission.
Final collection also rejects out-of-contract duplicates even if created by a
writer that bypassed this protocol.

Persisting invalidation can itself fail. Return failure and retain a bounded
local diagnostic, without logging payloads or inventing a durable receipt. A
collector cannot prove the absence of an unpersisted conflicting request; this
is an explicit evidence-loss limit, not a claim of lossless delivery.

## 5. Collector join and outcome

Collect one exact succeeded run with its authoritative document/source and a
complete, non-truncated durable snapshot. Do not infer ingestion completion from
event timestamps. For this family, require exactly one acceptance and one
terminal, no invalidation, matching common fields, expected source hash, valid
schema, finite duration and no duplicate scope/ordinal or extra family records.

Resolve the terminal's **exact** `open_scope_id` against the existing strict
Reader evidence for that run/document. Require one `first_open` terminal and
request ordinals `1,2,3`: metadata, navigation, initial content (`window_start = 0`,
`node_limit = 150`). All must match the candidate hash and Backend revision; the
Reader terminal must match the frontend revision and report three requests.
Use the existing Reader validator's field/type rules on this selected open.
Preserve the existing aggregate Reader metric; do not select its mean, newest
open, or another successful scope to fill a missing join. Keep unrelated Reader
opens out of this specific join; malformed global evidence still fails the
overall durable-evidence audit.

Acceptance necessarily precedes its browser acknowledgement, but Reader request
rows, the Reader terminal and the new terminal can commit in any order. Collection
with missing rows is unavailable at that snapshot; later complete collection
may qualify. Do not compare cross-host timestamps, add telemetry polling, sum
component durations, or claim that a `204` response proves the entire join.

| Evidence / release state | Required-metric result |
|---|---|
| Current deployment, no new producer | `not_instrumented` |
| Only acceptance, missing Reader proof, invalidation, identity conflict or incomplete snapshot | `not_available`, no numeric value |
| Prototype data before scope approval and runtime acceptance | Diagnostic only; no required-metric promotion |
| Accepted scope and exact-revision accepted implementation, complete valid join | Eligible for `observed` |

Malformed/oversized evidence must remain visible in collector audit flags; never
silently discard it to obtain `observed`. The breakdown reports method, scope,
root/open IDs, source/candidate hashes, revisions and `client_reported = true`.
Do not persist or emit filename, title, content, URL, raw storage reference,
credential, raw candidate ID, checksum or absolute browser clock samples.

## 6. Implementation and verification gate

This contract and its companion boundary remain Proposed. The review has fixed
the correlation and error boundaries, but does not approve semantic-ready as
full visible-page readiness. Keep current upload/Reader schemas, polling cadence,
selection, rendering, task ownership and processing statuses unchanged. A future
Preview must retain its exact Staging origin, separate access token and source
revision gates; the Backend requires its Staging revision/event gates. TXT and
the Production Pages root remain outside this first implementation.

Before runtime acceptance, verify the following against the composed app and
companion Preview, including real PostgreSQL transactions for concurrency:

- Natural single upload, immediate-completed response and one-file delegation;
  manual/batch/overlapping opens cannot acquire the root.
- Swallowed Reader errors, throwing final notification and empty content never
  publish success; pending asynchronous assets remain outside the stated stop.
- Hidden/page-loss/reload, expiry, mismatched identity/revision and observer
  exceptions preserve business behavior and do not reuse a start clock.
- Strict duplicate-key/type/size validation, privacy-safe rejection, identical
  redelivery, conflicting slots and simultaneous acceptance/terminal writers.
- All Reader/new-terminal commit orders, including delayed or lost persistence;
  exact-open collection never substitutes another scope.
- Off/on business outcomes, data-request counts, memory retention, connection
  and lock cleanup, and bounded observer contention; SQLite alone cannot prove
  PostgreSQL locking behavior.

Then require exact-head CI, artifact verification and separately authorized
Staging/Preview deployment before a fresh one-page upload and automatic open.
No existing fixture can acquire a missing browser clock retroactively. This
docs-only change requests no upload, benchmark, merge or deployment.
