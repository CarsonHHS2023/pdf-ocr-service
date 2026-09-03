# S0 preprocessing CPU — local feasibility review, 2026-09-03

## Outcome

**Local feasibility controls PASS; complete stage CPU attribution NOT proven.**
Thirteen synthetic checks passed separately on CPython 3.11.15 and 3.12.13.
The current-worker clock is a feasible component; unrelated process work and
owned helper work show why process and thread clocks have different limits.
Required `preprocessing_cpu_seconds` remains `not_instrumented`.

This is not a runtime producer, durable-persistence, collector-mapping or Staging
acceptance result. No application runtime or native PDF/OpenCV computation ran.
See the [proposed attribution contract](../testing/s0-preprocessing-cpu-attribution-v1.md).

## Provenance and inspected source

Fresh remote reads at this checkpoint found:

- Backend Staging: `300b1d4e83a44aa6723a6143a9d82176e800d50b`.
- Production/main: `8fd75117a3b4311c159e38f029a0cf78d9d4081f`, unchanged by this work.
- Upload-memory [PR #42](https://github.com/CarsonHHS2023/pdf-ocr-service/pull/42):
  Draft/open/unmerged at `0e026816e07dd393ac55d841790a60ffdc06fce2`.

The CPU proposal is independently based on Staging, not stacked on unmerged
PR #42. A separate disposable checkout was composed with all 15 overlay scripts
in the exact order listed by `.github/workflows/staging-integration-ci.yml` at
that Staging SHA, from `apply_durable_ingestion_dispatch.py` through
`apply_s0_v5_phase0_observability.py`. All returned successfully under local
CPython 3.12.13. Generated runtime changes are inspection-only and are not part
of this proposal. This local composition is not a downloaded byte-verified CI
artifact or proof of the currently running HF revision.

| Composed source | SHA-256 |
|---|---|
| `app/processing/pdf_ingestion.py` | `64d6b97e3e91f996fb11ce783e598799b89768ef8a48cf7825c822420ccb7eb1` |
| `app/processing/s0_phase2_stage_observability.py` | `49f678811271f5a556b6e740812ad040bc73b506c11912b7911865fa24cef8a2` |
| `app/processing/pdf_page_presentation_preprocess_compat.py` | `51f7552f61fd40dbbe6243f7d6c259e147da87db0b36a46390e1f1b98c24e41f` |

Source review traced the raw executor submission, synchronous storage/preparation
boundary, installed wrapper/alias order, deferred output writes, shielded await
and abandoned-worker cleanup. Current process CPU remains auxiliary in
`app/processing/s0_baseline.py`; this proposal makes no mapping changes.

## Reproducible local controls

Run from the repository root; standard library only:

```sh
python3.11 scripts/probes/s0_preprocessing_cpu_feasibility.py
python3.12 scripts/probes/s0_preprocessing_cpu_feasibility.py
```

Probe SHA-256:
`d1577c832a7a4086432e299e0c87602ba5b68dfe9ab50e64d915b6a8ad759542`.
The local `python3` executable supplied CPython 3.12.13; the separately installed
3.11 interpreter supplied 3.11.15. These are not asserted HF runtime versions.

| Controls | Count | What they establish locally |
|---|---:|---|
| Integer interval, explicit zero, invalid/missing/thread-mismatch evidence | 3 | Toy sample validation; invalid is not zero |
| End before publication, delegate exception, observer failures | 3 | Toy bracket ordering and preservation of application outcomes |
| Reused worker and explicit identity versus ContextVar | 2 | Fresh intervals and raw executor context boundary |
| Unrelated process-thread work and owned helper work | 2 | Process contamination and worker-clock coverage exclusion |
| Awaiting-thread versus worker clock | 1 | Sampling around await is not sampling the worker |
| Running cancellation and pre-entry queued cancellation | 2 | Awaiter terminal is not worker terminal; no-entry is not zero |
| **Total per interpreter** | **13** | **PASS on both versions** |

Real-clock controls use bounded 50 ms synthetic CPU loops and five-second
coordination watchdogs. Their generous half-target separation checks are local
smoke-test expectations, not production admission thresholds or performance
benchmarks. Deterministic fake-clock controls cover arithmetic/invalid evidence.
A Python helper is only a counterexample to complete ownership; it does not
measure OpenCV threading, HF CPU consumption or native execution overlap.

## Review limits and handoff

No blocking issue was found in the design/local-probe scope after checking the
actual composed boundary, cancellation semantics, metric separation and diff.
This is a local self-review, not independent review or approval of implementation.
The proposed auxiliary still needs a finalized bounded event schema, full
identity propagation, actual wrapper installation tests, late worker persistence,
atomic scope closure, duplicate/malformed/privacy checks and strict mapping tests.

The script has no app imports or installer calls, is not registered in named CI
test commands, and never calls a server, database, storage adapter or Provider.
Existing CI may compile it; that must not be reported as executing these 13
checks. CI results belong to the proposal's eventual exact head and are reported
on its PR, not inferred from this local result.

No PDFs, source contents or private fixture identifiers were added. No workflow,
runtime, dependency, database, Production or PR #42 change is included. There
was no merge, deployment or 100/528-page benchmark. All four required gaps remain;
S0/M5 are In Progress and S1/S2 are not started.
