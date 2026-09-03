# S0 worker-thread CPU — proposed event and persistence protocol v1

Status: **Staging-only implementation candidate in Draft PR #43**, 2026-09-03.
See the [implementation evidence and limits](../reviews/s0-preprocessing-worker-cpu-implementation-2026-09-03.md).
Supplements the [CPU attribution boundary](s0-preprocessing-cpu-attribution-v1.md);
it is not deployed/accepted and does not close `preprocessing_cpu_seconds`.
The proposed auxiliary name is `preprocessing_worker_thread_cpu_seconds`.

## 1. Source review findings resolved by this design

Reviewed at PR #43 head `519f7068d8a00ee1b2d85e72d94a74f8b3bbde0d`, based on
Staging `300b1d4e83a44aa6723a6143a9d82176e800d50b`:

| Existing behavior | Required design response |
|---|---|
| Generic sanitizer truncates lists at 12, strings at 256 characters and top-level fields at 32 | Flat exact-field payloads; require sanitizer output equal input and UTF-8 size at most 8,192 bytes |
| Generic sanitizer permits some filename/path-shaped keys and values | Equality is insufficient: exact field names, types and value grammars must be validated first |
| Generic `record_processing_event` commits one row and may resolve only document existence | Dedicated bounded batch writer with exact run/document/source relationship checks |
| Event model has a UUID primary key but no scope/ordinal unique constraint | Deterministic per-slot primary keys plus independent collector duplicate rejection; no schema migration proposed |
| Source-read/verification can fail before the timed delegate is entered | Registered operation may terminate `not_started`; no CPU zero is fabricated |
| Awaiter cancellation leaves shielded work running | Separate dispatch seal and actual scope settlement; do not publish a complete terminal on cancellation alone |

Reference code: `app/processing/processing_events.py`,
`app/processing/processing_event_model.py`,
`app/s0_failure_retry_observability.py`, `app/processing/pdf_ingestion.py` and
the bounded event loader in `app/processing/s0_baseline.py`. The S0.3.6 private
writer provides an existing batch/relationship-check pattern, not a ready-made
CPU lifecycle implementation.

## 2. Fixed bounds and exact payload shapes

For v1, allow at most **8 registered preprocessing requests per logical PDF
invocation**, independent of page count or Provider shard count. The inspected
normal path registers one. Eight is a conservative telemetry storage cap, not a
new processing, retry or concurrency limit. On the ninth request, set sticky
`scope_overflow`, retain only eight metadata slots and continue processing with
no CPU measurement claim for the omitted request. Never clip a count into a
complete manifest. A closed overflow report has `complete=false`.

Normally at most **18 events**: one run start, up to eight registrations, up to eight
scope terminals and one run terminal. No arrays or nested objects are needed.
The root terminal's count, all registered scope IDs and matching terminal rows
together form the manifest. An ordinal is a **logical slot**, not commit-time or
wall-clock order; terminals are written in a later batch.

Implementation refinement: reserve **one additional invalidation event**, ordinal
18, for a post-closure protocol violation. The absolute per-root ceiling is 19
events, while any invalidation prevents observation. This provides a bounded
way to reject an earlier complete snapshot if a closed root is unexpectedly
reused; repeated violations do not emit unbounded events.

Every payload has exactly these six common fields, plus the fields in the next
table (unknown/missing fields are rejected):

| Common field | Exact value / grammar |
|---|---|
| `contract_version` | `atlas.s0.preprocessing-worker-cpu.v1` |
| `measurement_scope` | `worker_thread_only` |
| `method` | `sync_preprocessing_worker_thread_cpu_v1` |
| `run_scope_id` | `cpu_` plus 32 lowercase hexadecimal digits, freshly generated per invocation |
| `source_scope_id` | `source_` plus full 64-digit lowercase SHA-256 of the verified `SourceFile.id` UTF-8 string; not a PDF checksum or storage reference |
| `backend_revision` | Exact 40-digit lowercase Staging artifact SHA |

The 64-digit source scope is deliberately versioned here; do not confuse it with
S0.3.6's shorter source scope. Verify the actual relational source identity before
hashing; hashing arbitrary caller text does not make it a valid source identity.

| Event name | Additional fields | Ordinal |
|---|---|---:|
| `S0_PREPROCESS_CPU_RUN_STARTED` | `ordinal` | 0 |
| `S0_PREPROCESS_CPU_SCOPE_REGISTERED` | `ordinal`, `scope_index`, `scope_id` | `2*i-1` |
| `S0_PREPROCESS_CPU_SCOPE_TERMINAL` | Registration fields plus `operation_outcome`, `clock_status`, `cpu_delta_ns`, `clock_resolution_ns`, `reason` | `2*i` |
| `S0_PREPROCESS_CPU_RUN_TERMINAL` | `ordinal`, `scope_count`, `complete`, `logical_outcome`, `issue` | `2*N+1` |
| `S0_PREPROCESS_CPU_RUN_INVALIDATED` | `ordinal`, `issue=protocol_violation` | 18, optional and always invalidating |

`i` is an integer 1..8; `N` is an integer 0..8. Booleans are never integers for
validation. `scope_id` is `pcpu_` plus 32 lowercase hex digits; it is unique per
registered request and identical in that request's two rows. Root ordinal range
is 0..17; require the complete, duplicate-free logical range 0..`2*N+1`.

The normal relational envelope remains `atlas.processing.event.v1`, with exact
processing-run/document columns, no page number, severity `info` (a CPU report,
not a replacement error log), and database event timestamps. Do not infer CPU
or cancellation ordering from those timestamps. Use generated processing IDs,
never a private name as correlation input. A proposed deterministic event ID is:

```python
uuid.uuid5(uuid.NAMESPACE_OID,
    f"atlas.s0.preprocessing-worker-cpu.v1:{run_scope_id}:{ordinal}")
```

This reuses the existing primary-key constraint to block duplicate insertion of
the same slot; it is not proof of exactly-once delivery. A duplicate/conflicting
write must not overwrite existing rows. The collector independently rejects
duplicate logical slots even if an incompatible writer used different row IDs.

### Scope terminal values

- `operation_outcome`: `completed`, `failed`, `not_started`. This describes the
  timed delegate, not the outer worker's entire source-read/cleanup job.
- `clock_status`: `measured`, `unavailable`, `not_started`.
- `cpu_delta_ns`: exact integer 0..`2**53-1` only when measured, otherwise null.
- `clock_resolution_ns`: integer 1..1,000,000,000 when measured, otherwise null;
  derive conservatively by rounding the positive finite reported resolution up
  to nanoseconds. Unsupported/coarser clocks are unavailable, not clamped.
- `reason`: `none` for measured; `clock_unavailable` or `invalid_clock` for an
  entered delegate without valid clock evidence; `admission_rejected`,
  `submit_failed`, `pre_delegate_failure` or `cancelled_before_entry` for an
  unentered delegate. No exception messages or arbitrary exception-class strings.

Valid combinations: completed/failed plus measured/none; completed/failed plus
unavailable and its clock reason; or not_started/not_started with an explicit
pre-entry reason and two null numeric values. Awaiter cancellation alone never
establishes `cancelled_before_entry`: the future must positively confirm no entry
and terminal cancellation, or cancellation must occur before any submission.
Missing observation from a completed worker is a protocol failure unless the
pre-entry branch is positively known; absence of a clock is not proof of no entry.

### Run terminal values

`logical_outcome` is `completed`, `failed`, `cancelled` or `unknown`, distinct from
each worker outcome. `complete` is a boolean for registered-scope coverage, not
full native CPU coverage. `issue` is `none`, `scope_overflow`, `persistence_loss`,
`identity_mismatch`, `protocol_violation` or `logical_terminal_unknown`.
`complete=true` requires `issue=none` and a known logical outcome; unavailable
clock data can still have complete lifecycle coverage, but cannot yield an
observed CPU metric. When multiple issues occur, use the first detected issue
and keep incompleteness sticky; this bounded reason is not a complete error log.

## 3. Lifecycle and publication ownership

Create a small metadata-only root at the logical PDF invocation; store only
opaque IDs, revision, counters, flags and bounded scope records. Do not retain
PDF bytes, storage adapters, ORM entities, filenames or descriptor objects in
the observer. Pass its reference explicitly to submitted work; do not rely on
event-loop ContextVars crossing raw executor submission.

Register each intended `_prepare_geometry_provider_input_async` call **before**
entering its size/capacity acquisition path. Persist the registration before
dispatch when possible; no new observation await may occur between semaphore
acquisition and the existing submission/cleanup protection. Registration means
intent, not executor acceptance or stage entry. This distinction refines the
boundary document's operation-scope rule without changing its CPU interval.

Run-start/registration failure must not reject processing. Record a sticky
incomplete flag; never backfill an apparently successful start after the work.
If cancellation interrupts publication, the commit may still happen: treat the
acknowledgement as unknown/incomplete, not as proof the row was rolled back.
No additional processing retries or semaphore/callback changes are allowed.

The actual Phase 2 synchronous delegate captures its start/end clocks on the
worker. End capture precedes new publication and preserves the original return
or exception. Capture stores metadata only: **do not publish from inside the
existing Phase 2 timed wrapper before its wall/process fields have been captured**.
Otherwise the new SQL/publication overhead would contaminate those old metrics.
Defer settlement/finalization to the outer storage/preparation worker's `finally`,
after the existing Phase 2 measurement path has returned or raised; the captured
CPU end remains at the original delegate boundary. Settlement is recorded once;
confirmed pre-entry
rejection, submission failure or source-read failure records a null-clock
`not_started` settlement instead. Keep the current worker cleanup unchanged.

Use one root lock for bounded metadata transitions only, never around compute,
database work or an await. Dispatch closure and scope settlement can arrive in
either order. A final snapshot can be claimed exactly once only when:

1. the invocation can dispatch no more preprocessing requests (dispatch sealed);
2. all registered requests have positively settled;
3. the snapshot has not already been claimed.

Worker completion first waits for dispatch seal; cancellation/seal first waits
for actual worker settlement. A failed/cancelled root stays failed/cancelled even
if its worker later completes. Do not wait for the worker in the cancelled
request merely to obtain telemetry or change the ProcessingRun status.
Overflow can close only an incomplete retained-prefix report; it is not coverage
of the untracked requests. No automatic timeout creates a zero/complete terminal.

The implementation must prove no registration is possible after seal at the
actual call graph. Post-seal registration is a protocol defect, not an accepted
extra operation: before terminal claim it makes the root incomplete; afterwards
it claims the single invalidation event. The original work still runs, but the
collector must not trust the earlier complete terminal. An observer write loss
still cannot be repaired into a guaranteed complete history by this mechanism.

## 4. Dedicated bounded writer, not one-row generic publication

Persist all retained scope terminals and the run terminal **in one transaction**
from the claimed immutable snapshot. Earlier run-start/registration rows remain
separate durable evidence. No rows from a failed final transaction count as a
complete terminal; do not retry a partially acknowledged transaction blindly.
At most one publication attempt per logical event/batch is proposed for v1.

The publication worker owns a fresh session; never share the request/processing
Session across threads. This follows the
[SQLAlchemy session concurrency contract](https://docs.sqlalchemy.org/en/20/orm/session_basics.html#is-the-session-thread-safe-is-asyncsession-safe-to-share-in-concurrent-tasks).
Validate exact field/type/value allowlists, sanitizer equality and encoded byte
size before opening the transaction. Within it, verify `SourceFile.id` belongs
to the intended document and, when present, ProcessingRun maps to that exact
document/source. Early events may precede ProcessingRun initialization, as the
existing event model permits; collector admission still needs the real run and
source rows. Reject a changed runtime revision or identity mismatch.

Late worker publication must not depend on the cancelled event-loop ContextVar
or require a live event loop: the worker may publish synchronously after clock
capture **and the existing Phase 2 measurement**, outside the metadata lock.
The root readiness flag is scope settlement, not merely availability of a clock
sample, so a racing dispatch seal cannot publish in the middle of Phase 2.
If the event-loop side claims the snapshot,
use the existing thread-offload publication pattern with explicit completion
ownership and retained task references. `shield` does not suppress cancellation
of its caller; see [Python task cancellation](https://docs.python.org/3.11/library/asyncio-task.html#asyncio.shield).
The exact scheduling/cleanup integration must be tested before shipping; the
local model proves only the claim gate. Process loss or publisher loss leaves
evidence incomplete. No observer retry daemon or unbounded task queue is proposed.

Document deletion can cascade events and invalidate late source/document checks.
Do not resurrect records or block deletion for telemetry; missing retained
identity/evidence makes collection unavailable. No database migration, online
schema modification or live Neon test is part of this design review.

## 5. Strict auxiliary admission and implementation gates

The future collector must require one root, one exact revision/source/run/doc,
the complete registered/terminal scope set, matching scope IDs and contiguous
logical ordinals. Reject extra/missing fields, duplicate/mixed roots, invalid
combinations, malformed/oversized named events and truncated evidence windows.
Preserve SQL-side payload byte guards; never materialize an oversized raw Text
value to perform the check. Do not select the newest apparently valid root and
discard conflicting evidence.

An observed auxiliary requires a real ProcessingRun with canonical status
`succeeded`, a `completed` logical
outcome, `complete=true`, at least one scope, and every registered scope completed
with a valid measured clock. Sum disjoint per-invocation integer deltas, reject
total overflow above `2**53-1`, then divide by 1e9 for seconds. Zero is admissible
only from actual valid entered intervals at their recorded resolution. Zero
scopes, failed/cancelled runs, unavailable clocks, non-entry or incomplete evidence
yield no observed aggregate; individual diagnostic rows may remain inspectable.
Neither the process delta nor nested classification CPU is added to this sum.

Missing producer events remain `not_instrumented`; present but invalid/incomplete
protocol evidence is `not_available`, not zero or an observed partial sum. The
required full-stage `preprocessing_cpu_seconds` remains `not_instrumented` in all
cases under this worker-only protocol. Existing required metrics are unchanged.

The candidate now includes the strict dependency-light auxiliary validator,
composed worker/root hooks, dedicated writer and named CI tests. CPU JSON decoding
also rejects duplicate keys and non-finite constants, without changing decoding
for existing event families. Regression gates include lifecycle interleavings, source-read failure before
entry, publication after existing Phase 2 capture on success/error, cancellation
during publication, post-seal impossibility, same-ID duplicate
rollback, final-batch atomicity, source/run mismatch, document deletion, sanitizer
rejection, evidence-window truncation and no new processing/cleanup behavior.
Local/fake inputs and disposable test databases are used first. See the evidence
report for executed versus pending checks. Exact-head review, runtime rollout,
merge, new PDF runs and Staging acceptance require their own later gates.
