# S0.3.7 Provider download/compute review — 2026-09-20

Status: **Duration and retrieval-count numeric defects reproduced and corrected in PR #50; candidate not deployed. Full S0.3.7 remains open.**

## Source and reviewed boundary

Inspected Staging `593d65199c6e21571e0094014d41dc30269f9adc`.
The local download/compute modules were compared with exact-ref repository
contents; tests used the current Staging workflow composition and synthetic
in-memory SQLite. No live database, Provider request, document upload or retained
source content was used.

The scope is Provider download numeric admission and its aggregate, downstream
OCR/batch/page/GPU reconciliation, and existing source-size correlation.
This is not an exhaustive audit of every event envelope or cross-family snapshot.

## P2 — Guard conversion and aggregation before admitting download duration

Source: [Provider source-download observer/collector](https://github.com/CarsonHHS2023/pdf-ocr-service/blob/593d65199c6e21571e0094014d41dc30269f9adc/app/s0_provider_source_download_observability.py).

Two bounded synthetic inputs expose the same missing numeric-safety boundary:

1. An event with integer `download_duration_seconds = 10**400` fits the payload
   byte cap and parses as JSON, but `float(duration)` raises `OverflowError`.
   The composed `collect_s0_run_snapshot` fails instead of returning an
   unavailable measurement. Producer-side projection has the same unchecked
   conversion before its persistence try/except. This is not a demonstrated
   ingestion failure: orchestration has additional observer error handling.
2. Two otherwise valid download scopes, each with finite duration `1e308`,
   overflow their accumulated duration to infinity. The composed snapshot marks
   `modal_download_seconds` observed with a nonfinite value and cannot be
   serialized with `allow_nan=False`.

These are malformed/extreme synthetic controls, not a claim that such durations
occurred in accepted live runs.

## Fix and controls

[PR #50](https://github.com/CarsonHHS2023/pdf-ocr-service/pull/50), head `2d89122050d61f54515f7e675fd30f4d6da44cb8`,
adds shared checked duration conversion and a finite aggregate check.
Invalid evidence returns `not_available` with no numeric value; producer
projection returns false without publishing. Independent Backend transport
evidence remains usable. Only the observer/collector module and its test file
change; no event schema, retry behavior, Provider work or new duration cap changes.

| Synthetic control | Before fix | Fixed candidate |
|---|---|---|
| Two normal durations 0.2 and 0.3 | observed, finite, JSON-safe | same |
| Huge signed integer | OverflowError from collector / producer projection | unavailable / no publication |
| Two finite 1e308 durations | observed infinity; strict JSON fails | unavailable; full snapshot serializes |
| Boolean / negative duration | unavailable | same |
| Nonfinite JSON exponent | unavailable | same |
| Zero duration | valid | preserved |
| Single large but finite duration | valid under existing v1 numeric contract | preserved |

Thirteen new parameterized cases exercise the public producer and the composed
collector, including full snapshot serialization, preservation of the independent
Backend transport result, and a successful zero-duration publication control.
The six-case review probe was run before and after the fix. Local suites:
**49 Provider download/compute tests plus 16 generic baseline tests passed**.
The two focused files initially lacked one imported test-support module in the
local partial snapshot; fetching that exact-ref test module allowed the complete
suites to run. No runtime code was changed to work around test setup.

Exact-head CI for `2d89122050d61f54515f7e675fd30f4d6da44cb8` passed all five workflows:

- [Provider 20 MiB Staging CI](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/35535986174): success.
- [S0 Baseline CI](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/35535986194): success.
- [Provider Transport Sharding CI](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/35535986129): success.
- [Durable Processing Events CI](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/35535986189): success.
- [Staging Backend Integration CI](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/35535986125): success.

The integration workflow's integration and artifact_verification jobs succeeded;
the deploy job was skipped for this pull request. This candidate remains unmerged
and undeployed.

## Retrieval-count reconciliation follow-up — 2026-09-20

The continuing event/linkage review found a second numeric resource-bound defect
in the same transport evidence path. On deployed Staging
`593d65199c6e21571e0094014d41dc30269f9adc`, both the
[storage collector composition](https://github.com/CarsonHHS2023/pdf-ocr-service/blob/593d65199c6e21571e0094014d41dc30269f9adc/scripts/apply_s0_transport_terminal_collector.py)
and [Backend source-body collector](https://github.com/CarsonHHS2023/pdf-ocr-service/blob/593d65199c6e21571e0094014d41dc30269f9adc/app/s0_transport_download_observability.py)
construct `set(range(1, terminal_count + 1))` from a retained JSON integer.
The SQL row cap and payload-byte cap do not bound that integer's magnitude.

A safe synthetic probe used only five events and a count of 1,000,000 per
path. Both returned unavailable but first allocated about 67 MiB of Python
objects. Larger counts could exhaust collector memory; no live exhaustion was
attempted or observed.

| Path | Before: peak traced bytes | After: peak traced bytes | Result |
|---|---:|---:|---|
| Storage I/O | 70,683,554 | 241,464 | unavailable |
| Backend source-body transmission | 70,582,314 | 138,881 | unavailable |

These are local `tracemalloc` diagnostics for this synthetic collector call,
not process RSS, upload peak memory, or new fixture acceptance. The values are
environment-specific; the fix's bound comes from the algorithm.

The correction is included in existing [PR #50](https://github.com/CarsonHHS2023/pdf-ocr-service/pull/50),
now at `2fdaca282a5128a95e9f8362045bad36ae41a4f8`. Previously validated ordinals are unique positive
integers; their actual count and maximum establish the exact sequence 1..N
(including the empty zero case). Work is bounded by retained evidence instead
of the declared count. No new counter cap or retrieval policy is introduced.

The source correction changes the composition script that owns the storage
helper, not the generated baseline file. Applying the overlay also refreshes
an installed legacy helper; a second application is unchanged. Backend
transport uses the same bounded comparison. The previous two-file description
and CI above are the duration-only checkpoint; the current PR changes six files.

Twenty new parameterized cases exercise both paths through the composed public
collector: zero, one and reordered complete sequences; missing, shifted and
duplicate ordinals; zero-count conflicts; a huge ordinal; over-window and
`10**400` terminal counts. A test-only range guard prevents the former
implementation from exhausting regression-runner memory. Invalid evidence
has no metric value; independent source bytes and strict snapshot JSON survive.
An additional test covers installed-helper upgrade and idempotence.
**122 local tests passed** across storage, transport, Provider download/compute
and generic baseline suites. No skips.

Exact-head CI for `2fdaca282a5128a95e9f8362045bad36ae41a4f8` is successful:

- [Provider 20 MiB Staging CI](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/35536953829): success (attempt 1).
- [Provider Transport Sharding CI](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/35536953899): success (attempt 1).
- [Durable Processing Events CI](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/35536953743): success (attempt 1).
- [S0 Baseline CI](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/35536953717): success (attempt 1).
- [Staging Backend Integration CI](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/35536953807): success (attempt 2).

Integration and artifact verification passed on attempt 2; deployment was skipped.
The candidate remains unmerged and undeployed.

Integration attempt 1 failed in
`test_postgresql_concurrent_slots_and_lock_timeout`: concurrent conflicting
terminals returned [409, 409, 409, 503], while the test expects four 409s.
The PostgreSQL log contains a second document-row lock timeout, beyond the
deliberate timeout control. The failing persistence module and test are
byte-identical between Staging and this head; this call path does not invoke
the modified collectors. This is consistent with lock-contention timing, not
proof of a general concurrency fix. One failed-job retry was requested on the
same head. No assertion, timeout or production code was changed to suppress it.
The first attempt's [failure log](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/35536953807/job/106147578730)
remains part of the evidence; any future recurrence needs separate diagnosis.

### SQL and identity boundaries checked in this pass

| Boundary | Verified behavior | Limit retained |
|---|---|---|
| Run/document | Run's exact document ID selects the document; event SQL filters both run ID and document ID | This does not prove every payload-level identity |
| Retained source | Exact run source ID is selected and its document ID must match; no fallback to another source | Candidate/selection identity across all families remains unreviewed |
| Event window | SQL requests cap plus one and reports truncation; payload byte count is checked before materializing oversized text | Numeric magnitude is independent of byte length |
| Event envelope | Upload/Reader-specific envelope validation remains active | Schema/revision policy for every other event family is not signed off |
| Ordinal closure | Count and maximum now reconcile unique positive retained ordinals without declared-count allocation | Full snapshot and per-object provenance remain outside this fix |

The existing generic baseline tests cover cross-document event exclusion,
bounded SQL projection, payload limits and truncation. Source ownership was
also checked in the source-file lookup. No live database queries, fixture
uploads, Provider requests, merges or deployments were performed in this pass.

## Subsequent schema/identity pass

PR #50 was subsequently extended at `d9f608b5223b0d600b33c23e3042a7788e077664` with
generic event-schema admission. See the [schema/identity review](s0-3-7-schema-identity-review-2026-09-20.md)
for the separate reproduction, candidate-association boundaries and current-head
CI. Numeric results and CI above remain historical checkpoints, not claims
about a different revision. The current PR changes seven files.

## Reviewed safeguards and retained limits

- Existing compute tests cover missing/duplicate terminals and batches,
  contiguous ordinals, shard-local page coverage, total Provider-selected page
  count, finite batch times and positive raw-result byte counts.
- Missing/invalid GPU evidence leaves GPU unavailable while preserving otherwise
  valid OCR/raw-result metrics. Publication rollback, privacy projection and
  event-loop responsiveness tests passed.
- Download scope IDs must be unique; sizes are compared with Atlas transport
  sizes as a **multiset**, deliberately permitting reverse scope order.
  This is the existing documented contract, not a per-object provenance join.
  Same-sized objects cannot be distinguished by this check alone; this review
  does not silently upgrade that limitation or declare it a newly introduced bug.
- Unknown-family/envelope behavior outside the corrected upload/Reader path,
  revision trust, relational source/candidate linkage and cross-family snapshot
  consistency remain outside this scoped sign-off.
- Historical [transport/download acceptance](s0-3-3-transport-download-acceptance-2026-09-01.md)
  and [compute contract](s0-3-4-compute-observability-contract-2026-09-01.md) retain
  their measured boundaries and revisions. The earlier
  [upload/Reader hardening](s0-3-7-collector-admission-review-2026-09-19.md)
  is already deployed and is not reopened by this candidate.

S0/M5 remain In Progress at **17/19**. Complete upload peak memory and full
preprocessing CPU remain unimplemented; no additional fixture is requested.
