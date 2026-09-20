# S0.3.7 Provider download/compute review — 2026-09-20

Status: **Numeric-safety defect reproduced and corrected in PR #50; candidate not deployed. Full S0.3.7 remains open.**

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
