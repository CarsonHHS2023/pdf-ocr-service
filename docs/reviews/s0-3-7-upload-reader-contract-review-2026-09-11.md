# S0.3.7 upload/Reader contract review — 2026-09-11

Status: **Scoped review with one reproduced collector defect; full S0.3.7 remains open**.

## Source and scope

Reviewed Backend runtime source `f3b7af8122d5e5fe946614c6e1ddd0047877d504`
through documentation head `20e19d4f86f99df2af0ec65ea512977a393389b3`,
plus frontend Preview `086cda854c24680ea4ce1c414844f10af2c14dcf`.
The [upload/Reader contract](../contracts/s0-upload-reader-observation-v1.md)
and [small acceptance](s0-upload-reader-small-acceptance-2026-09-11.md) remain
the baseline records.

This pass inspects upload acknowledgement, terminal persistence, Reader
association, decoder/mapping composition and same-clock duration consistency.
It does not claim a complete re-review of transport, compute, worker CPU,
visual-generation and failure/retry protocols, or fresh concurrent Staging
execution.

## Reproduced finding: contradictory containing duration

`app/s0_upload_reader_metrics.py::measure_upload_reader` validates each duration
but does not compare the joined durations at the reviewed runtime revision.

A local, dependency-light six-event control with a 10-second upload duration and
4-second Reader duration is `observed`. Changing only the upload duration to
1 second is also admitted as `observed`. Missing Reader terminal and duplicate
upload acceptance controls are correctly `not_available`; duplicate JSON keys
are rejected by the strict decoder.

The frontend samples `stopped` once in `s0-reader-open.js::finish` and passes
that sample into `s0-upload-reader.js::finish`. Upload begins before its
automatic Reader open. Thus the upload interval must be greater than or equal
to the exact joined Reader interval. Equal values remain admissible at the
shared microsecond rounding precision.

[Backend PR #48](https://github.com/CarsonHHS2023/pdf-ocr-service/pull/48)
implements a fail-closed comparison and four direct boundary cases, and extends
the composed collector regression. Candidate:
`5ee14ed5d106a8aff86ecc190475de017a701a3e`.
This document does not claim the fix is deployed.

The accepted small values, 170.5072 seconds and 4.6543 seconds, satisfy the new
invariant. This finding does not invalidate that record or explain the earlier
missing-terminal attempt.

## Reviewed safeguards and limits

| Area | Source evidence | Limit retained |
|---|---|---|
| Upload acknowledgement | `s0_upload_reader_observability.py` waits for `persistence.accept` to commit before adding acknowledgement headers | A missing acknowledgement remains ineligible; HTTP success alone is not evidence |
| Bounded publication | Two owned writer slots; independent database checkout/connect/statement bounds; at most three durable upload slots | These are component bounds, not an end-to-end network deadline |
| Durable identity | `s0_upload_reader_persistence.py` checks dispatch/source/document/run identity, PDF kind, candidate/run success, exact root/revisions and existing slot consistency | The later collector still requires the exact Reader-open join |
| Duplicate/conflict | Deterministic slots, document lock, identical replay handling and append-only invalidation | Concurrency/transaction evidence is supplied by existing CI tests; not freshly exercised against Staging here |
| Payload decode | Upload overlay applies duplicate-key/nonfinite/byte-bounded decoder to upload and Reader event families | Unknown event names are not automatically valid evidence; new protocol families need explicit admission review |
| Bounded collection | `s0_baseline.py` filters exact run/document, uses SQL-side byte bounds and a max-events-plus-one truncation probe | Outer event-envelope details are not all projected into the metric helper; acceptance envelope audit remains separate |
| Exact open | Matching open/candidate/backend/frontend identity, three contiguous metadata/navigation/content requests, first-open mode | Another complete open cannot replace missing evidence for this upload |
| Late evidence | Collector joins by identity rather than insertion order | An earlier incomplete snapshot stays unavailable; later rows do not retroactively prove its missing data |
| Privacy | Fixed payload fields and hashed source/candidate scope identities; bounded in-memory diagnostic steps | This is the observer evidence contract, not a blanket assertion about legacy application logs |
| Clock semantics | One browser context and end sample; elapsed bounds; PR #48 adds containment | Client-reported measurement, excluding binary completion and browser paint |

## Validation performed in this pass

The counterexample and controls executed directly against the pinned
dependency-light modules on CPython 3.12.14. The fix then passed 20
dependency-light checks using existing test function bodies through an AST
harness, including the four new duration cases. Syntax and trailing whitespace
checks passed. This environment had no pytest/application dependencies; no local
database, middleware, PostgreSQL or fully composed collector suite was run.
For fix head `5ee14ed5d106a8aff86ecc190475de017a701a3e`, all five triggered
workflows passed: [S0 Baseline](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/34597278365),
[Provider 20 MiB](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/34597278451),
[Transport Sharding](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/34597278441),
[Durable Events](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/34597278492)
and [Staging Integration](https://github.com/CarsonHHS2023/pdf-ocr-service/actions/runs/34597278478).
Integration job `103255872695` and artifact verification `103256273057` passed;
deploy job `103256314930` was skipped. These are CI results, not new Staging
runtime acceptance. Scoped self-review confirmed the guard uses the exact joined
open, preserves equal-duration admission and changes no other metric mapping.

For the documentation changes, verify repository-relative links, pinned-source
paths, whitespace, private-fixture leakage and the changed-file scope. Do not
present documentation CI as a new runtime deployment or acceptance run.

## Remaining work

- PR #48 exact-head CI and scoped self-review are complete; a merge/rollout
  remains a separate step.
- Continue the remaining event-family and outer-envelope S0.3.7 review. This
  scoped pass does not close it.
- Follow the [TXT lifecycle/timing plan](../plans/s0-txt-lifecycle-timing-plan-2026-09-11.md)
  before any TXT timing fixture.
- Retain full upload peak memory and full preprocessing CPU as unimplemented;
  preserve the earlier missing-terminal result and all original acceptance
  revisions.

S0/M5 remain **In Progress**, with the accepted small snapshot at **17/19**.

