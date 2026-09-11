# S0 remaining attribution decisions — 2026-09-11

Status: **Proposed decision record; no waiver, runtime change or S0 closure**.

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

## Next work that does not require redefining these metrics

- Finish S0.3.7 review of the composed producer/persistence/collector contracts,
  including exact source identities, bounded payloads, privacy, late terminals,
  unknown/malformed events and duplicate/conflicting scopes. The new small
  acceptance proves its own path, not every negative or concurrent runtime case.
- Inspect current TXT ingestion lifecycle/timing boundaries against the existing
  meaningful-timestamp gate. Produce a source-pinned plan before asking for TXT
  fixtures; PDF evidence does not substitute for TXT ingestion timing.
- Keep the cost/benefit decision for the large PDF explicitly deferred. Medium
  reruns are justified by new multi-page/sharding coverage, not by the number of
  rows left open in the collector.

These are review tasks within S0. They do not claim all S0 exit gates are met and
do not authorize Production changes, merges, deployment or fixture execution.
