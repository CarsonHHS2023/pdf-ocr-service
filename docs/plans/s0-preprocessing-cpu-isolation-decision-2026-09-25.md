# S0 full preprocessing CPU — architecture decision draft

Status: **Feasibility experiment approved; local capability gate blocked**.
Date: 2026-09-25. Milestone: M5 / S0. Task: S0 CPU ownership decision.
Source revision: `8110784a5061641fd6229045a6f51b2fb89db7dd` (Backend Staging).
S0 remains **17/19**; `preprocessing_cpu_seconds` remains `not_instrumented`.

## Problem and recommendation

The accepted worker-thread clock already measures its declared component.
The missing requirement is exclusive, complete ownership of helper CPU.
Adding another timer around the existing shared process cannot establish that
ownership. See the [current CPU contract](../testing/s0-preprocessing-cpu-attribution-v1.md).

**Approved direction (2026-09-25):** investigate an isolated-worker feasibility
implementation as a separate architecture experiment, after verifying that the
intended runner can provide a delegated per-operation CPU accounting domain. Keep the current
Staging route as the default. Do not map the experiment to the required metric
until coverage, behavior equivalence, and the new execution baseline are approved.

The user approved the proposed experiment at 18:43 America/Chicago on 2026-09-25,
without deployment. The read-only capability implementation and local result are
recorded in the [preflight review](../reviews/s0-cpu-isolation-preflight-2026-09-25.md).
This is authorization to investigate changed compute placement, not acceptance
of a measured baseline or a narrower metric scope. The
[development workflow](../engineering/development-workflow.md) keeps unresolved
scope decisions pending.

## Source inventory and ownership boundaries

The following repository paths and symbols were read at the pinned revision.
Staging changes these modules through its integration overlay sequence; raw
source alone is not the deployed call graph. The Phase 0 installer orders shared
analysis before Phase 2 capture; the CPU installer inserts the worker timer
inside that captured delegate call. This is source inspection, not a new runtime
trace or a measurement of the hosting platform's native helper activity.

| Boundary | Source / symbol | Consequence for isolation |
|---|---|---|
| Admission, source load, completion | [pdf_ingestion.py](../../app/processing/pdf_ingestion.py), `_prepare_geometry_provider_input_async`, `_prepare_geometry_provider_input_from_storage`, `_PreprocessingJobState` | One preprocessing worker, two admitted/inflight slots; shielded await cancellation leaves worker completion/cleanup ownership alive. Source loading precedes the geometry delegate. |
| Existing measurement seam | [s0_phase2_stage_observability.py](../../app/processing/s0_phase2_stage_observability.py), `_wrap_preprocessing`; [CPU installer](../../scripts/apply_s0_preprocessing_cpu_observability.py) | Time only the captured synchronous delegate; submission/queue time is not CPU. Do not wrap the async await or miss the imported alias. |
| Native and nested operations | [presentation preprocessing](../../app/processing/pdf_page_presentation_preprocess_compat.py), `prepare_presentation_provider_input_v2`; [shared analysis installer](../../app/processing/s0_v5_phase1_shared_analysis_compat.py) | Classification, ordinary-page processing, render construction and manifest work are nested. Their clocks cannot be added to a containing total. Native helper ownership is unproven. |
| Deferred result state | [presentation lifecycle](../../app/processing/pdf_page_presentation_lifecycle_compat.py), `DeferredPresentationProviderInput`, `_DeferredProviderStorage`, `_store_deferred_subset` | Mixed-page subset bytes return in memory and are written later at grant creation. A worker IPC design must preserve that timing and bounded-memory behavior. |
| Process-local provenance | [presentation bridge](../../app/processing/pdf_page_presentation_bridge.py), `_register_manifest` | Registration updates a process-local manifest map. A child process return cannot implicitly update its parent's map. Inventory all later consumers before defining IPC. |
| Composed entry point | [Phase 0 installer](../../scripts/apply_s0_v5_phase0_observability.py); [Staging workflow](../../.github/workflows/staging-integration-ci.yml) | Reconstruct and test the exact installer order in a fresh worker. Do not publish generated/composed modules as raw-source changes. |

### Boundary to preserve

The target remains the existing synchronous delegate interval: classification,
ordinary-page processing, full render, and CPU for manifest/hash/storage work
executed inside it, including existing in-scope observers.

Exclude earlier retained-source read/checksum/page discovery, queue/admission,
Provider execution, canonicalization, deferred subset writes, and subsequent
abandoned-output cleanup. New launcher, IPC and initialization costs must be
reported separately. They still affect end-to-end performance and memory.

If all stage-owned helper work cannot finish at the existing seam, the experiment
must explicitly propose a new drain-inclusive boundary. It may not silently call
that broader interval the existing required metric. TXT worker wall timing is a
different metric and is outside this PDF execution design.

## Alternatives

| Option | What it establishes | Disposition |
|---|---|---|
| Existing thread clock | Calling-thread CPU only | Keep accepted auxiliary. |
| Shared process CPU delta | CPU from overlapping work in the process | Keep diagnostic; ownership remains missing. |
| Force native libraries to one thread | Changes execution; does not prove every library or child is covered | Not proposed. |
| Dedicated process plus process/children counters | Requires complete descendant lifecycle accounting and exclusive ownership | No complete proof established here. |
| Dedicated worker and per-operation cgroup v2 accounting | Candidate containment for worker threads and descendants | Recommended feasibility direction, subject to host and lifecycle gates. |

The Linux [cgroup v2 reference](https://docs.kernel.org/admin-guide/cgroup-v2.html)
documents hierarchical `cpu.stat` usage in microseconds, child membership
inheritance, and delegation permissions. Moving a process does not move existing
descendants; a launcher must contain it before it starts helper work.
`cgroup.events` exposes whether a subtree remains populated. These facilities
support the proposed experiment; they do not prove ownership in this application.

Python's [resource reference](https://docs.python.org/3.11/library/resource.html)
limits `RUSAGE_CHILDREN` to children that terminated and were waited for.
A process/children counter pair alone therefore does not establish complete
descendant accounting. This is an inference for this design, not a benchmark.

## Proposed architecture experiment

1. **Capability gate.** Establish cgroup v2 visibility, counter readability,
   authorized subtree creation/membership, and a cleanup owner on the intended
   runner. Merely reading the hosting container's aggregate counter is
   insufficient. HF delegation is **unknown**, not assumed available. Do not
   change mounts, privileges, host quotas or native thread settings. If no
   delegation is available, stop this route and retain the gap.
2. **Exclusive worker.** Use a fresh spawned process for one operation; never
   fork a running multithreaded application or reuse a warm worker across
   documents for this first experiment. Place the child into its dedicated
   domain before imports can start helpers. Keep supervisor/publisher outside.
   Deny helper migration out and unrelated work entering. Delegation alone is
   not proof against escapes within a delegated hierarchy.
3. **Ready/entry handshake.** Reproduce the composed configuration, construct
   child-local clients, load/verify the source and finish setup before entry.
   Quiesce setup helpers. At a bounded barrier the supervisor reads the start
   counter, then releases exactly one delegate invocation. Include any handshake
   overhead that remains inside the interval in the method disclosure.
4. **Delegate/exit handshake.** Capture the logical outcome without replacing the
   original return/failure semantics. Establish that stage-owned helpers have
   completed and cannot perform later stage work before taking the end counter.
   A marker from the calling thread alone is insufficient. A reused idle helper
   must have a proven quiescence protocol; otherwise the exact-boundary method
   is unsupported. Report a separate whole-job experimental scope if needed.
5. **Result transfer.** Define a versioned bounded protocol for returned artifacts,
   page maps and provenance. Do not pickle live storage/DB clients, callbacks,
   locks or native PDF handles. Inventory in-memory bytes and manifest consumers.
   Choose a reviewed, bounded transfer mechanism before coding the worker; do
   not add an unbounded PDF copy or force an early deferred upload.
6. **Completion owner.** Preserve cancellation as an abandoned waiter, not a
   fabricated worker terminal. A supervisor owns child completion, cleanup,
   capacity release and evidence even if the event loop closes. Process loss,
   timeout, unreadable counters, or unproven helper completion produce incomplete
   evidence. Do not retry computation automatically to repair measurement loss.
7. **Publication.** Give each invocation opaque run/document/source/revision and
   method identities. Reuse the existing protocol's bounded-scope, exact-type,
   durable start/terminal, post-close invalidation and strict admission principles.
   Review a separate event schema before implementation; do not overload the
   accepted worker-thread family or replace its historical evidence.

For an admitted disjoint scope, the candidate conversion is
`(end_usage_usec - start_usage_usec) / 1_000_000`. Reject missing, malformed,
boolean, negative, decreasing or overflowing samples. Zero is valid only with
valid samples and complete coverage. Never infer an upper bound from wall time,
subtract unrelated background estimates, or add child counters to a containing
cgroup counter. Sum scopes only after the run manifest proves disjoint, complete
ownership and successful outcomes; partial/failed evidence stays diagnostic.

## Acceptance criteria before a runtime PR

| Gate | Required evidence |
|---|---|
| Runner capability | Actual intended-host delegation/accounting evidence; a local container is not HF proof. |
| Ownership | Native helper threads, exited descendants, overlapping unrelated work, and helper escape controls; a Python busy-loop alone does not prove application coverage. |
| Boundary | Setup/entry/exit/drain ordering and explicit in/out costs; scope disagreement remains pending. |
| Semantics | Same classification/page maps, render/provenance, deferred writes and fail-open behavior on bounded generated fixtures with deterministic service doubles. |
| Cancellation | Queued cancellation, running cancellation, late completion, worker failure and supervisor shutdown; one cleanup/capacity owner, no success fabricated from missing evidence. |
| Bounded cost | Limits for IPC, artifact bytes, process admission and events; measure startup, IPC, extra memory and changed cache behavior separately. Numeric acceptance thresholds require review before any live comparison. |
| Durable evidence | Transaction loss, duplicate/conflicting terminals, mixed identities/revisions, scope overflow and late invalidation rejected by the composed collector. |
| Composition | Exact Staging installer order and idempotence; parent/child aliases and manifest consumers verified. |
| Baseline | Separate execution/method version and approved comparison policy. No historical fixture relabeling and no automatic 18/19 claim. |

These gates are not completed by this document. Existing counterexample probes
need not be repeated. A later bounded synthetic implementation can exercise new
ownership/lifecycle behavior; live uploads and Provider calls remain separate
acceptance work.

## Compatibility, rollout and rollback

This PR adds the design, a standalone read-only preflight, its tests and a review
record. It adds no dependencies, application runtime flag, collector mapping,
workflow, deployment, or storage schema. Production and main are outside scope.
PR #47 remains the existing acceptance/handoff record.

A subsequent approved experimental implementation must default off, preserve
current admission limits, and remain separate from normal Staging processing
until reviewed. Do not silently fall back to the old route while claiming the
new measurement method. Disabling a future experiment stops new admissions;
already-running jobs retain their completion owner until drained. Retain the
existing worker-thread auxiliary and original acceptance provenance.

## Decision recorded and remaining gates

**The isolated-worker feasibility experiment with a separate execution baseline
is approved, conditional on the capability gate above.** The local read-only
cgroup mount blocks worker execution here; intended-host delegation is unknown.
Do not repeat the approval request for work within this experiment. Upload peak
memory remains open.

Approval of the experiment is not approval to deploy it, to run private fixtures,
to narrow the existing required CPU scope, or to close S0. If the exact boundary
cannot be preserved, present the measured difference and a scope decision first.

## Validation

- Re-read pinned source and owning composition scripts; no AGENTS.md was present
  in the pinned repository tree.
- Checked repository-relative links and the four-file change allowlist.
- Preflight/parser tests: 29 passed; actual local CLI: exit 2, readonly_mount.
- No application pipeline tests, native CPU ownership probes, live database
  queries, fixture uploads, Provider requests or deployment were performed.
- Intended-host capability and full CPU ownership remain unverified. See the
  review for exact evidence and the capability gate's limits.
