# S0.3.1 upload-memory boundary and admission contract

| Field | Value |
| --- | --- |
| Document Type | Proposed observability contract / implementation gate |
| Approval Status | Proposed |
| Lifecycle Status | Active |
| Version | 0.1 |
| Date | 2026-09-03 |
| Authority Domain | Proposed canonical-upload memory semantics and evidence admission only |
| Implementation / acceptance | Not implemented; no new Staging fixture acceptance |
| Inspected Backend Staging revision | `300b1d4e83a44aa6723a6143a9d82176e800d50b` |
| Supersedes | None; preserves existing upload-duration and read-component meanings |

This design continues [S0.3.1 in the closure plan](../plans/s0-observability-closure-plan-2026-08-25.md#s031-upload-boundary-measurements).
It does not authorize runtime implementation, fixture execution, merge, deployment,
Production changes, or S1/S2 work. S0 and M5 remain **In Progress**.

## 1. Decision and present limitation

**Local feasibility follow-up (2026-09-03):** [15 synthetic probes on each of
CPython 3.11 and 3.12](../reviews/s0-3-1-upload-memory-feasibility-2026-09-03.md)
now demonstrate identical read counters for different live-buffer schedules,
missing plain-bytes weak-release hooks, and explicit context/worker limitations.
These are counterexamples and narrow positive controls, not a full producer,
durable acceptance or an approved waiver. Current read/receive counters and a
weak-reference-only release scheme are not eligible full-memory methods.

Keep `backend_upload_peak_memory_mb = not_instrumented`, with no value, in the
current collector. Its existing unit is **MiB**, despite the historical `_mb`
suffix; any eventual byte conversion must use `2**20` and retain byte evidence.

The existing probes cannot establish a complete, request-attributable upload
memory peak under concurrency. This is a **producer/attribution gap**, not a
missing collector alias or a failed PDF fixture. Durable persistence already
supports upload-duration and read-component evidence, but there is no full-memory
producer value to persist or promote. No additional upload can repair that gap.
This is a bounded feasibility conclusion about the inspected implementation,
not a claim that request-owned memory instrumentation is impossible in general.

The design distinguishes three outcomes:

| Evidence | Permitted interpretation | Required upload-memory row |
| --- | --- | --- |
| Existing largest `UploadFile.read` result | Logical payload bytes of one returned object; existing auxiliary only | Remains `not_instrumented` |
| Future explicitly tracked live-buffer subset | Peak logical payload of that named subset, if its lifecycle coverage is proved; separate auxiliary | Remains `not_instrumented` |
| Future complete upload-owned allocation evidence | Candidate for a reviewed full-memory method and versioned admission rules | No promotion until method, coverage and acceptance are approved |

Do not introduce another component metric merely to rename the current largest
read result. A subsequent implementation proposal must demonstrate incremental
coverage, such as simultaneous distinct buffers, and say which memory remains
unmeasured. If instrumentation-only work cannot establish the full boundary,
retain the gap and request an explicit scope/limitation decision. This document
is **not an accepted waiver**, and the four remaining required gaps do not become
three when this design is merged.

## 2. Inspected runtime path, not raw-source assumptions

The [Staging integration workflow](../../.github/workflows/staging-integration-ci.yml)
composes overlays before testing and packaging. Its durable-dispatch entrypoint
applies [the canonical-route replacement](../../scripts/apply_legacy_durable_ingestion_dispatch.py).
Inspect that replacement together with [the base upload helpers](../../app/routers/ocr.py),
not just the uncomposed handler's direct PDF/TXT task calls.

The composed canonical request follows this order:

1. Enter the FastAPI ASGI boundary for `POST /api/v1/upload`; parse multipart input.
2. The handler obtains `content = await file.read()` without a size argument.
3. `_retain_source_bytes` hashes that payload and calls `StorageProvider.put`.
4. For PDF, `fitz.open(stream=content, filetype="pdf")` reads the page count and
   closes the PDF handle. TXT does not enter this PDF operation.
5. `commit_retained_ingestion` commits Document, SourceFile and IngestionDispatch.
6. `BackgroundTasks.add_task(run_ingestion_dispatch, accepted.dispatch_id)`
   returns; the upload observer captures its acceptance boundary.

The [ASGI/read observer](../../app/s0_upload_boundary_observability.py) and
[durable-dispatch compatibility hook](../../app/s0_upload_durable_dispatch_compat.py)
capture elapsed time **before** telemetry-only identity/source lookups and writes.
Keep that boundary and the existing `S0_UPLOAD_ACCEPTANCE_MEASURED` contract intact.
The [collector overlay](../../scripts/apply_s0_upload_baseline_mapping.py) currently
maps upload duration and auxiliary byte evidence, not upload peak memory.

The inspected revision is a documentation-only descendant of the accepted
[S0.3.6 small](../reviews/s0-3-6-failure-retry-small-acceptance-2026-09-02.md) and
[medium](../reviews/s0-3-6-failure-retry-medium-acceptance-2026-09-02.md) runtime
`7435aa3fa7ba0766d8cc2584bcacfd735c5ce74c`. Their historical measurements retain
that original revision. Neither those runs nor the newer deployment constitutes
upload-memory acceptance.

## 3. Operation boundary and coverage inventory

Start at canonical FastAPI ASGI entry, before the application's multipart parsing;
end immediately after successful registration of the already-committed durable
dispatch, before telemetry work. This is an **acceptance-window** boundary, not
client upload time, first network byte, response delivery, complete request cleanup,
or a ProcessingRun/OCR lifecycle. Buffers still live at the end contribute within
the window; the end is not evidence that they were freed.
Successful acceptance is not proof of HTTP response delivery or later processing
success; a post-acceptance error does not retroactively redefine this boundary.

| Component | Inside this acceptance window? | Current memory coverage / requirement |
| --- | --- | --- |
| Application-visible ASGI body chunks | Yes, when delivered inside the window | Byte counts and maximum chunk length exist; simultaneous liveness and allocation capacity do not |
| Multipart parser and in-memory spool | Yes | No complete allocation/lifetime measurement; disk spool size is not RAM |
| Handler's returned source payload | Yes | Largest read-result length exists; object overhead and all simultaneous buffers are not covered |
| Hashing and source-retention operation | Yes | Payload passes into storage; sharing is not a second allocation; local/S3 implementation and SDK temporaries need their own coverage |
| PDF page-count parser | Yes, PDF only | Native/transient allocations are not measured by the existing read probe; TXT absence is explicit, not missing evidence |
| Acceptance metadata and database-client work | Yes | No request-owned allocation accounting; persistent/shared caches cannot be assigned from process deltas |
| HF proxy, TLS/kernel/network-server buffers before application entry | Outside defined application boundary | Not claimed as upload-owned application memory |
| Telemetry work, response serialization/cleanup after acceptance, background processing, OCR and Reader | Outside defined window | Must not extend the upload window or enter its peak |

This inventory describes what a **full** acceptance-window claim must address.
It does not say all entries can already be measured. A subset measure must list
its included components and known exclusions and cannot use the full-memory name.
Source retention size, HTTP ingress bytes, logical storage I/O, later Backend
source-transport bytes and Provider downloaded bytes remain independent of memory.

FastAPI documents spooled uploads and thread-pool execution of async file methods;
Starlette exposes a `SpooledTemporaryFile`. This supports inspecting parser/spool
and worker boundaries, not assuming a particular installed spool threshold or
number of copies. Pin resolved runtime dependencies before proposing version-
specific hooks. [FastAPI request files](https://fastapi.tiangolo.com/tutorial/request-files/),
[Starlette request files](https://starlette.dev/requests/#request-files).

## 4. Measurement methods and concurrency

| Method | Why it cannot currently fill the required row |
| --- | --- |
| Process RSS / `ru_maxrss`, or differences of process peaks | Process scope includes other requests/work and prior peaks; a smaller subsequent upload can produce no new high-water mark |
| Request-window RSS sampling or start/end RSS delta | A window does not provide ownership; endpoint deltas miss temporaries, periodic sampling can miss short peaks, and subtracting a baseline does not remove overlapping allocations |
| `tracemalloc` current/peak or snapshot differences | Traced Python allocations are not a request identity or guaranteed coverage of native-library allocations; snapshots do not reconstruct all transient peaks |
| Per-request `tracemalloc.reset_peak()` | Resets shared tracer peak state, not a per-request counter; overlapping requests can corrupt each other's comparison |
| `len(content)` / `sys.getsizeof(content)` | Payload length or directly attributed object size, not parser/SDK/native/metadata memory or a complete operation peak |
| Sum of independent component maxima | Maxima may occur at different times; shared backing buffers can be double-counted; this is not the peak of simultaneous distinct allocations |

Python defines resource counters by process/thread resource scope and describes
`ru_maxrss` as maximum resident set size; there is no request-attribution contract
in that API. The first two rejection decisions above follow from applying those
scopes to this shared Backend. [Python 3.11 resource](https://docs.python.org/3.11/library/resource.html#resource.getrusage).

`tracemalloc` reports traced blocks and resets its recorded peak. Native extensions
can participate explicitly; their complete participation cannot be assumed.
The concurrency rejection is this design's inference, not a claim that the API
provides per-request isolation. [Python 3.11 tracemalloc](https://docs.python.org/3.11/library/tracemalloc.html).
`sys.getsizeof` counts directly attributed object memory, not referred objects;
extension behavior is implementation-specific. [Python 3.11 sys.getsizeof](https://docs.python.org/3.11/library/sys.html#sys.getsizeof).

ContextVars can carry an upload observation through supported task boundaries;
they are not allocation ownership tags. A copied context is shallow, so an
inherited mutable observation is not an independent ledger. Thread propagation,
same-request child tasks and callbacks after finalization need explicit tests.
[Python 3.11 contextvars](https://docs.python.org/3.11/library/contextvars.html).

Do not change upload concurrency, introduce a global upload lock, move upload/PDF
work into another process, change streaming/spooling behavior, or move compute to
Modal just to obtain a cleaner number. Such execution changes exceed this S0
instrumentation-only design and would change the baseline being measured.

## 5. Gate for any future bounded component producer

A local feasibility proposal may evaluate a request-owned **logical live-payload**
ledger. It is not selected as a full-memory implementation by this document.
For explicitly supported buffer lifetimes, the proposed arithmetic is:

`tracked_payload_peak_bytes = max_t(sum(payload_bytes(b) for distinct live tracked buffers b at t))`

The result measures the declared subset's logical payload bytes, not allocated
capacity, object headers, resident pages, or full Backend memory. Admission needs:

- Explicit acquire/alias/release boundaries for every supported component. A
  call returning does not prove the caller has released its returned bytes; a
  subsequent ASGI `receive` does not prove the previous body is dead.
- One backing allocation counted once while shared. Distinct copies count
  separately. A sliced/non-byte `memoryview`, unknown alias, or escaped buffer
  needs a proved byte/backing-store rule or incomplete coverage, not `len` guessing.
- No copying, retaining an extra strong reference to a document buffer, forcing
  GC, reading a spool to measure it, or scanning process-wide object graphs.
- A fixed component allowlist and explicit small caps on tracking state and
  lifecycle operations, justified in the implementation proposal. No unbounded
  object registry or per-chunk event list. Overflow, unknown release and accounting
  underflow invalidate completeness instead of clamping the metric to zero.
- Per-request ownership and synchronization that handles worker callbacks; no
  global peak reset. Detach/freeze the observation at acceptance before telemetry
  or inherited background work can update it. Unresolved in-window accounting at
  freeze marks coverage incomplete; a late callback cannot repair a published
  summary or justify an earlier complete claim. Ignore post-window callbacks safely
  and test that no event can be republished after terminal closure.
- An on/off comparison preserving file reads/writes, retention, dispatch count,
  result/exception behavior, cancellation and object lifetimes. Instrumentation
  errors fail open for business processing and fail closed for metric admission.

The current single returned-source-buffer case may simply reproduce the existing
largest-read auxiliary. That alone is insufficient incremental value for a new
implementation PR. Parser/SDK/native coverage must not be claimed from a synthetic
ledger test or from the above formula without real integration hooks.

## 6. Future durable evidence and collector admission

This section specifies review requirements, **not an event schema installed by
this PR**. A follow-up producer must define its exact event name, method/version,
fixed field allowlist, caps and collector tests before implementation approval.
Preserve the existing upload event; do not silently reinterpret its fields.

For an accepted canonical upload, require one immutable memory summary linked to
the exact ProcessingRun, Document and SourceFile association. Payload correlation
uses opaque upload identity, hashed source scope and exact Backend revision;
raw database identity remains in existing association columns where applicable.
An equal source size is not sufficient proof of source identity. Scope is one
canonical upload operation, not one Provider shard or page.

The summary must declare route, acceptance-window scope, memory method/version,
component coverage, completeness, terminal outcome, value/unit or an allowlisted
unavailable reason. A memory measurement can be unavailable even when upload
acceptance and its duration succeeded. Never turn an absent measurement into zero.
All terminal fields are published together, with no separate partial component
writes presented as complete. Repeated callbacks produce no extra terminal;
duplicate retained summaries remain ambiguous to the collector, not silently
deduplicated by choosing the latest. No per-allocation database writes.

Before durable association exists, failed/rejected/cancelled uploads may only
produce bounded diagnostics through the current permitted path; do not create
fake Document/SourceFile/ProcessingRun rows to hold telemetry. Such diagnostics
are not run-associated acceptance evidence. A crash or failed summary write
leaves evidence missing, not a successful zero-memory observation.

Future mapping must retain these distinctions:

| Condition | Collector treatment |
| --- | --- |
| Current runtime has no full-memory producer | Required metric stays `not_instrumented`, value absent |
| Only a valid explicitly named subset producer exists | Subset may be auxiliary `observed`; full-memory required metric stays `not_instrumented` |
| Future implemented method has missing, failed, unsupported or ambiguous same-run evidence | Its metric is `not_available`, value absent; do not label a failed sample as unimplemented |
| Unrelated bounded event-window incompleteness | At most `partial`; no complete admission |
| Future approved full method and complete exact association/coverage | Eligible for required `observed` only after its separate acceptance gate |

Reject malformed or oversized same-name events before trusting their fields;
reject unknown fields, invalid scope/revision, conflicting source identities,
duplicate terminals, nonfinite/negative numbers, bool-as-number values and unit
mismatches. A sample maximum may only be named a sampled maximum, never an exact
peak. An exclusion cannot be hidden by `complete=true` on a subset.

Use the existing durable payload limit of **8192 encoded UTF-8 bytes**, validating
before persistence and on collection. Sanitization/truncation that changes the
claimed evidence invalidates it; it cannot preserve `complete=true`. Use fixed
allowlisted reason codes, not exception text. No filename, title, document bytes,
path, URL, token, raw storage reference, raw object address or allocation traceback
is published. This contract does not claim an audit or repair of older stderr logs.

## 7. Verification gates and next decision

These are required **future producer tests**, not a completed producer suite in
this PR. The [local feasibility checkpoint](../reviews/s0-3-1-upload-memory-feasibility-2026-09-03.md)
covers narrower counterexamples; it does not satisfy all gates below.

| Test case | Required result |
| --- | --- |
| One buffer, overlapping distinct buffers, non-overlapping maxima, aliases | Exact declared-subset peak; sharing counted once and non-overlapping maxima not summed |
| Two overlapping uploads plus unrelated allocator work | Independent ownership; no cross-request mutation or process-RSS promotion |
| Worker callbacks, inherited child context, nested hooks, callbacks after acceptance | Single frozen summary; no late OCR/telemetry bytes entering the window |
| In-memory spool / rollover, PDF page-count / TXT, local / S3 adapter | Supported boundaries proved on pinned dependencies; opaque internals explicitly excluded |
| Read/storage/DB failure, task-registration failure, cancellation and missing durable identity | Business behavior unchanged; no false successful summary or fabricated run |
| Missing/duplicate/conflicting/malformed/oversized evidence; cap overflow | Admission fails closed with bounded reason; no zero from absence |
| Runtime gate off and instrumented on/off comparisons | No Production hooks enabled; same upload/dispatch behavior and no added document-buffer retention |

Next, review this boundary/limitation proposal. Before writing runtime code, select
one explicit path: (a) a useful attributable component with documented residual
gap and no required promotion; (b) a proven complete method within the current
execution model; or (c) a separately approved limitation/scope revision. This
proposal selects none of those as an already approved implementation or waiver.

A later implementation uses focused contracts and exact-head PR CI first, with
PR deployment skipped and composed-artifact verification. Only after separately
authorized merge/deploy would a fresh small fixture be meaningful. Memory coverage
depends on upload routes, buffer lifetimes, spooling and concurrency, not Provider
page sharding; an 11-page rerun is not automatically required. TXT evidence remains
separately scoped. No 100-page or 528-page benchmark is authorized.

The [closure matrix](../plans/s0-observability-closure-plan-2026-08-25.md#6-s0-closure-matrix)
still has four required gaps: `backend_upload_peak_memory_mb`,
`preprocessing_cpu_seconds`, `visual_asset_generation_seconds`, and
`upload_to_reader_ready_seconds`. This proposal supplies no new numeric acceptance,
does not alter the existing small/medium reports, and does not close S0/M5.
