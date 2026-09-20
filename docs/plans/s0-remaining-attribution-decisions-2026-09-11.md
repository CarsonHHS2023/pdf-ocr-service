# S0 remaining attribution decisions — 2026-09-11

Status: **Current handoff, updated 2026-09-20; attribution gaps retained without waiver**.

The [latest small acceptance](../reviews/s0-upload-reader-small-acceptance-2026-09-11.md)
has 17/19 required rows observed. Two are unimplemented attribution methods,
not missing events from that fixture. Additional uploads cannot create the
missing producers. Existing accepted auxiliary metrics retain their own scope.

| Required metric | Proven evidence available | Missing coverage |
|---|---|---|
| `backend_upload_peak_memory_mb` (MiB) | Upload receive/read byte counters and named read-buffer components | Complete simultaneous live allocations attributable to this upload, including multipart/spool, adapters and native page discovery under concurrency |
| `preprocessing_cpu_seconds` | Worker-thread CPU auxiliary; separate process CPU delta and wall duration | Disjoint ownership and complete coverage of native helper threads/processes for the agreed stage |

The [memory contract](../testing/s0-upload-memory-observability-v1.md) and
[CPU attribution contract](../testing/s0-preprocessing-cpu-attribution-v1.md)
already document these limits and their local counterexamples. Do not repeat
those probes or rename components merely to obtain 19 observed rows.

## Decision boundaries

1. **Current default: retain both gaps.** No collector mapping changes are
   justified. Continue independent S0 evidence and review work; do not close S0
   or start S1/S2. This preserves the existing requirement and authorizations.
2. **A complete method inside the current execution model:** before runtime
   implementation, review an ownership/coverage proof, bounded instrumentation
   cost, disjoint aggregation and cancellation/failure semantics. Memory must
   distinguish aliases from simultaneously live distinct allocations. CPU must
   account for helper work without unrelated overlapping execution. No such
   complete method is established by the current evidence.
3. **A narrower comparison scope or accepted limitation:** this requires an
   explicit decision identifying each changed requirement, excluded resource
   cost and the effect on later comparisons. Largest read bytes cannot establish
   lower upload peak memory; worker CPU cannot establish lower total CPU. Keep
   original metric keys/statuses honest and publish any approved scope under its
   own version. This document proposes no automatic limitation acceptance.

Moving computation to isolated processes, changing native threading or serializing
uploads could alter the baseline being measured. Such changes require a separate
architecture/baseline decision; they are not silently included in S0 observability.

## 2026-09-11 source-review follow-up

The [scoped upload/Reader review](../reviews/s0-3-7-upload-reader-contract-review-2026-09-11.md)
reproduced missing duration-containment validation. [PR #48](https://github.com/CarsonHHS2023/pdf-ocr-service/pull/48)
added the collector guard and regression cases; at that checkpoint exact-head
CI had passed and deployment was pending. The later rollout is recorded below.
The full S0.3.7 review remains open.

The [TXT lifecycle plan](s0-txt-lifecycle-timing-plan-2026-09-11.md) now records
PR #49's completed implementation, tested deployment and
[small live worker acceptance](../reviews/s0-txt-worker-small-acceptance-2026-09-19.md).
The 64,476-byte control measured **23.63936695 s**, and the user confirmed Reader
body and TOC. The read-only audit was not a native collector replay. Formal
registered TXT baseline and PDF-only browser admission remain separate gaps;
same late lifecycle timestamps are still unsuitable. This auxiliary containing
interval is not full preprocessing CPU or upload-memory attribution.

## 2026-09-19 collector review result

The [bounded collector review](../reviews/s0-3-7-collector-admission-review-2026-09-19.md)
reproduced two P2 defects: malformed Reader scope evidence is dropped before the
upload join, and upload envelope metadata is not validated by the collector.
Unknown Reader-family names are also ignored. A 16-case synthetic probe documents
the failures and rejection controls. Current-Staging focused tests passed
49/1 skipped; with PR #48, 53/1 skipped. PR #48 fixes duration containment and
does not fix these pre-existing admission gaps.

**2026-09-20 implementation:** PR #48 now fixes Reader family/scope admission
and bounded upload-envelope validation at `5ea0608a071218ed52e2dde69a13ec77c5e9d633`, with
composed regressions and valid-other-open controls. Local results are 152 passed,
two PostgreSQL-specific skips and 155 subtests passed. See the
[review follow-up](../reviews/s0-3-7-collector-admission-review-2026-09-19.md)
for exact-head CI and deployment evidence. PR #48 is now merged and deployed
as `593d65199c6e21571e0094014d41dc30269f9adc`; merge-triggered integration, artifact verification
and exact HF runtime revision checks passed in run 35508286188.
Next work is the remaining S0.3.7 contract review beyond the corrected
upload/Reader path. Existing audited live evidence retains its original
provenance; no repeated fixture upload is required merely for this fix.

## Provider numeric review — 2026-09-20

The [Provider download/compute review](../reviews/s0-3-7-provider-numeric-review-2026-09-20.md)
reproduced an unchecked huge-integer conversion and nonfinite duration sum in the
download collector. PR #50 fixes both failure modes at `2d89122050d61f54515f7e675fd30f4d6da44cb8`;
65 local focused/baseline tests passed. The review retains the explicit byte-size
multiset correlation boundary and the independent OCR/GPU status semantics.
The candidate is not deployed; exact-head CI is recorded in the review.
A follow-up reproduced payload-sized set allocation in storage and Backend
transport retrieval reconciliation. PR #50 now uses actual retained ordinal
count/maximum at `2fdaca282a5128a95e9f8362045bad36ae41a4f8`, including upgrade-safe composition.
The composed 122-test suite passed; current-head CI is recorded in the review.
SQL run/document filtering and exact source ownership were checked; complete
family-envelope and candidate-linkage review remains open.
Continue other S0.3.7 families without relabeling historical acceptance.

## Next work that does not require redefining these metrics

- Finish S0.3.7 review of the composed producer/persistence/collector contracts,
  including exact source identities, bounded payloads, privacy, late terminals,
  unknown/malformed events and duplicate/conflicting scopes. The new small
  acceptance proves its own path, not every negative or concurrent runtime case.
- Continue S0.3.7 beyond the completed upload/Reader pass at the composed collector's SQL projection and
  event-envelope boundary: map each event family to its exact validator, byte
  bound, cap-plus-one detection, run/document/revision joins and ambiguity
  handling. Inspect missing/extra envelope fields and unknown family names.
  Reproduce any candidate defect with a bounded synthetic case before a fix;
  publish source references and explicit unreviewed areas.
- Retain PR #48's merged/deployed provenance for duration containment and both
  admission fixes. The merge-triggered tested artifact and HF revision are pinned
  in the review follow-up; historical acceptance is not relabeled as a new run.
- Preserve the accepted TXT control. A formal registered baseline needs verified
  private fixture identity and a native collector report; medium execution needs
  a concrete additional window/outline coverage target. No repeat upload is
  needed merely to reconfirm the successful small control.
- Keep the cost/benefit decision for the large PDF explicitly deferred. Medium
  reruns are justified by new multi-page/sharding coverage, not by the number of
  rows left open in the collector.

These are review tasks within S0. They do not claim all S0 exit gates are met and
do not authorize Production changes, merges, deployment or fixture execution.

