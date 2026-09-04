# S0 preprocessing CPU attribution — proposed boundary v1

| Field | Value |
|---|---|
| Status | Worker-thread auxiliary accepted in Staging; required full-stage metric remains open |
| Date | 2026-09-03 |
| Inspected Backend Staging source | `300b1d4e83a44aa6723a6143a9d82176e800d50b` |
| Parent | [S0 closure plan](../plans/s0-observability-closure-plan-2026-08-25.md) |
| Local evidence | [CPU feasibility review](../reviews/s0-preprocessing-cpu-feasibility-2026-09-03.md) |
| Staging evidence | [One-page worker-CPU acceptance — 2026-09-04](../reviews/s0-preprocessing-worker-cpu-small-acceptance-2026-09-04.md) |

## 1. Decision and non-goals

The current synchronous preprocessing worker can measure its **own thread CPU
interval**, without changing compute placement. That is a useful component, not
proof of complete stage-owned CPU: native libraries may use helper threads or
processes whose CPU is absent from the caller's clock. The inspected source does
not prove exclusive ownership of those helpers. A one-worker Python executor does
not make the process or native libraries single-threaded.

Keep required `preprocessing_cpu_seconds = not_instrumented`. Do not rename the
current process-wide delta or the proposed worker component to fill it. This
initial proposal granted no accepted limitation or waiver. The
[implementation follow-up](../reviews/s0-preprocessing-worker-cpu-implementation-2026-09-03.md)
now adds Staging-only worker-component producer/persistence/auxiliary mapping;
it does not promote the required complete-stage metric.
S0 and M5 remain In Progress; S1/S2 are not started.

The separate upload-memory proposal remains open in
[PR #42](https://github.com/CarsonHHS2023/pdf-ocr-service/pull/42), at inspected head
`0e026816e07dd393ac55d841790a60ffdc06fce2`. Its local counterexamples do not establish
upload-owned peak memory. Proceeding with CPU design neither merges that PR nor
waives `backend_upload_peak_memory_mb`.

No changes to executor concurrency, native threading configuration, processing
behavior, retry policy, compute placement, storage, Production or dependencies
are included. No PDF upload or benchmark was needed for this implementation slice.

## 2. Distinct measurements

| Measurement | Scope | Current disposition |
|---|---|---|
| `preprocessing_wall_seconds` | Existing synchronous delegate wall duration, including waits inside it | Existing metric; unchanged |
| `preprocessing_process_cpu_delta_seconds` | Process CPU during that interval, including unrelated overlapping work | Existing auxiliary; unchanged |
| `preprocessing_worker_thread_cpu_seconds` | Current-worker CPU interval, excluding other threads/processes | Staging auxiliary accepted on `ee2f48d83972bfd978060b40b3729b4b6b8405d4` |
| `preprocessing_cpu_seconds` | Attributable CPU for the complete agreed preprocessing operation | Required gap remains `not_instrumented` |
| Classification CPU | Nested classification operation | Component of preprocessing, never added to its parent as independent work |

Python documents `process_time` as process user/system CPU and `thread_time` as
current-thread user/system CPU; both exclude sleep. Use two samples on the same
thread and subtract them. Integer nanoseconds avoid float conversion loss but do
not guarantee nanosecond clock resolution. See the
[Python 3.11 time reference](https://docs.python.org/3.11/library/time.html#time.thread_time).

OpenCV can use different parallel backends; a configured thread count is not a
per-operation CPU ownership ledger. This is a coverage risk inferred from the
source and documented library capability, **not a measurement of HF's build or
actual helper activity**. See the
[OpenCV parallel framework tutorial](https://docs.opencv.org/4.10.0/dc/ddf/tutorial_how_to_use_OpenCV_parallel_for_new.html)
and [threading API](https://docs.opencv.org/4.11.0/db/de0/group__core__utils.html).

## 3. Inspected execution boundary

At the pinned source plus the Staging integration overlay sequence:

1. `_prepare_geometry_provider_input_async` validates size and acquires the
   bounded admission semaphore, then submits work to `_PDF_PREPROCESSING_EXECUTOR`
   (`max_workers=1`, maximum inflight count 2).
2. `_prepare_geometry_provider_input_from_storage` runs on that worker. It reads
   and verifies the retained source and may discover page count before invoking
   `prepare_geometry_provider_input`.
3. The captured geometry delegate has already been composed with presentation,
   shared-analysis and Phase 2 wrappers. The existing Phase 2 `_wrap_preprocessing`
   calls its synchronous `delegate` and emits its own measurement afterwards.
4. The concurrent future completes after the worker returns/raises. Done callbacks
   and abandoned-output cleanup are separate from the preparation delegate.

The proposed worker-clock seam is **inside the existing Phase 2 preprocessing
wrapper, immediately around its synchronous `delegate` call**. Start and end
samples must execute in the same worker, including the exception path. Preserve
existing wall/process event semantics; do not wrap the asynchronous await or add
a later module monkeypatch that misses the already-imported ingestion alias.
Installer ordering, captured aliases and idempotence need implementation tests.

Included: CPU on that worker for delegated classification, ordinary-page v4
processing, full-render construction, manifest/hash work and storage calls that
actually occur inside the delegate. Existing nested diagnostics/observers also
consume CPU inside this scope; this is not "pure OpenCV CPU". A storage wait adds
wall time, but only CPU executed by this thread appears in its CPU clock.

Excluded: admission/queue time, earlier retained-source read/checksum and optional
page discovery, event-loop waiting, helper-thread/process CPU, Provider/OCR,
canonicalization, subsequent deferred subset writes, future done callbacks and
abandoned-output cleanup. Capture the end before the new observer's publication;
do not claim that all existing instrumentation overhead has been removed.

The source can defer Provider-subset persistence through a storage proxy. Do not
assume every eventual artifact write is inside this interval. Classification is
nested, and Provider sharding happens at another layer: neither page count nor
shard count determines how many preprocessing invocations occurred.

## 4. Identity, cancellation and terminal ownership

Raw `ThreadPoolExecutor.submit` at this seam does not copy the event-loop
`ContextVar` context. Future instrumentation must explicitly carry validated
processing-run, document, source-file and operation identity into the worker;
the retained descriptor and processing-attempt argument are available upstream.
Do not assume the current Phase 2 event, which records a run ID but no document
ID at this seam, already meets the proposed full identity contract.

Cancellation of the shielded await marks the job abandoned but does not necessarily
stop submitted work. A running future cannot be cancelled by `Future.cancel()`;
see [Python futures](https://docs.python.org/3.11/library/concurrent.futures.html#concurrent.futures.Future.cancel).

| State | Worker CPU evidence |
|---|---|
| Admission rejected / no stage entry | No observed interval; never fabricate zero |
| Submitted but not entered | No worker interval yet; queue and stage are different |
| Awaiter cancelled while worker continues | Awaiter cancellation is not a worker terminal; interval remains open |
| Delegate returns or raises | Capture worker end once, before callbacks/cleanup; retain completed/failed outcome |
| Worker exit unavailable (e.g. process lost) | Incomplete/unavailable evidence, not an observed zero |

A cancelled queued-future synthetic control illustrates Python's possible
pre-entry cancellation; it does not assert that the current application cancels
its queued concurrent future. Current `shield`/abandon behavior stays unchanged.
Worker completion after logical run cancellation must not rewrite the run's
terminal status. A future persistence design must support that ordering or mark
coverage incomplete, without silently dropping late worker evidence.

## 5. Admission gates and accepted auxiliary scope

The [event/persistence protocol follow-up](s0-preprocessing-worker-cpu-events-v1.md)
fixes the v1 field shapes, eight-request/eighteen-normal-event cap, null-clock
pre-entry evidence, exact sanitizer checks and cancellation-safe finalization
gate. It refines registration versus actual stage entry. The requirements below
remain applicable. The implementation adds one bounded post-closure invalidation
event (nineteen absolute maximum). These gates remain normative after the
worker-thread auxiliary acceptance; that acceptance does not extend coverage to
complete stage CPU.

The auxiliary implementation must maintain these requirements:

- Use allowlisted method/scope identifiers, e.g.
  `sync_preprocessing_worker_thread_cpu_v1` / `worker_thread_only`. Require valid
  integer nonnegative start/end clock values, matching worker execution and
  nondecreasing clocks. Unsupported clocks, read failures, mismatched threads or
  negative deltas mean unavailable, not clamped zero. Equal readings mean zero
  at the clock's resolution, not proof that no CPU instructions executed.
- Keep raw thread IDs and lifetime clock readings local; persist a validated
  nonnegative delta with method, coverage and clock-resolution metadata. Do not
  leak filenames, titles, paths, URLs, tokens, content, exception messages,
  checksums or raw storage references. Use validated opaque relational IDs.
- Allocate a fresh opaque operation scope per actual invocation; executor-thread
  reuse must not reuse the scope or a thread-lifetime counter. Use bounded
  start/terminal evidence with contiguous ordinals and a complete run-level scope
  manifest. Uniqueness, duplicate rejection and late/cancelled terminal handling
  need actual durable transaction tests, not only in-memory callbacks.
- Cap each serialized event at 8,192 UTF-8 bytes and bound run-level scope count
  before producer admission. The follow-up proposes eight registered requests,
  at most eighteen normal events, one exceptional invalidation and sticky incomplete overflow; never silently truncate a
  manifest. Overflow, malformed payloads or missing closure block aggregation.
- Preserve processing return values and original exceptions if the observer
  fails. Fail-open runtime behavior does not mean fail-open collector admission.
  Failed-operation CPU may be useful diagnostic data but must not be silently
  presented as a complete successful-run baseline.
- Keep process-wide deltas and nested stage components separate. Do not infer
  full-stage CPU by subtracting unrelated baselines, sampling all `/proc` threads,
  adding parent and child clocks, or assuming CPU cannot exceed wall time for a
  multithreaded operation. Only disjoint, validated ownership could justify sums.

The toy probe does **not** implement these durable gates or justify changing the
required collector row. A complete stage CPU method additionally needs proven
ownership/coverage of all helper work, including shared or exited workers and any
child processes. Changing native thread settings or moving work to an isolated
process solely to obtain a number would change this baseline and is out of scope.

## 6. Review decision and next gate

Recommended: retain the required gap and review the explicitly named
worker-thread auxiliary component and its [bounded protocol](s0-preprocessing-worker-cpu-events-v1.md).
Field shapes, composed producer, atomic writer and strict auxiliary collector
are now present in the accepted auxiliary implementation; see the
[implementation evidence](../reviews/s0-preprocessing-worker-cpu-implementation-2026-09-03.md)
and [Staging acceptance](../reviews/s0-preprocessing-worker-cpu-small-acceptance-2026-09-04.md).
Any future
claim of complete `preprocessing_cpu_seconds` needs new coverage evidence or an
explicitly approved scope revision; neither is granted by this proposal.

The [local feasibility review](../reviews/s0-preprocessing-cpu-feasibility-2026-09-03.md)
is a source-boundary review plus synthetic Python controls, not native OpenCV,
HF runtime, durable persistence, collector or Staging acceptance. The four
required gaps remain unchanged. Existing small/medium acceptance keeps its
original run IDs and runtime revision; no rerun or relabeling is requested.
