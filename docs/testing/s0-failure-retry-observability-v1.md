# S0.3.6 backend-owned failure/retry observability

Status: implemented via PR #41; **small single-scope and medium sequential
multi-scope success-path Staging acceptance PASS (2026-09-02)** on
`7435aa3fa7ba0766d8cc2584bcacfd735c5ce74c`. See the
[small checkpoint](../reviews/s0-3-6-failure-retry-small-acceptance-2026-09-02.md) and
[medium follow-up and limits](../reviews/s0-3-6-failure-retry-medium-acceptance-2026-09-02.md).
Concurrent runtime scopes and real nonzero failure/retry observations are not claimed.
S0/M5 remain In Progress. This record neither closes S0 nor authorizes deployment,
Production changes, real fault injection, or additional fixture runs.

## Scope and independent meanings

The `failure_retry_counts` required metric is a structured reading of one complete
backend PDF processing invocation, not a scalar sum across execution layers.

| Component | Meaning |
| --- | --- |
| `backend_provider_calls.attempts` | Actual entries into the orchestrator's Provider submit/status/result/artifact methods; not planned retries, wire packets, or Provider executions. |
| `backend_provider_calls.failed` | Calls that raised an exception, excluding cancellation and result availability waits. |
| `backend_provider_calls.retries` | Status/result calls actually entered after a retryable timeout/unavailable failure in the same orchestration scope. |
| `backend_provider_calls.retryable_failures` | Failed calls marked retryable; eligibility alone does not prove a retry occurred. |
| `backend_provider_calls.not_ready` | `RESULT_NOT_READY` result-fetch waits; these are neither failures nor processing retries. |
| `backend_provider_calls.cancelled` | Calls entered and then cancelled; separate from failures. |
| `orchestration_invocations` | Completed/failed/cancelled orchestration calls, independently grouped by Provider job (including shards). |
| `provider_terminal_observations` | Observed Provider terminal statuses; `unknown` is explicit when no terminal was observed. Not a claim about eventual remote execution. |
| `logical_pdf_invocation` | One backend processing entrypoint outcome. It can fail without any failed Provider RPC (for example canonicalization failure). |

Do **not** add the failure counts from different layers. A failed Provider job can
be returned by a successful status request. Normal successful status polling is
not retrying processing. Source URL fallback is not a processing retry. There is
no automatic submission retry in this contract. Provider-internal execution
retries, durable queue redelivery, other HTTP/LLM clients, TXT processing, and
aggregate attempts across separate logical runs are **not measured** here.

Existing policy, retry budget, backoff, request limits, cleanup, exception mapping,
and submission-uncertainty behavior are unchanged. Observability uses ContextVars;
it does not replace/mutate the orchestrator or its Provider instance. Subclass
behavior and concurrent shard/task attribution are preserved.

## Durable closure

1. `S0_FAILURE_RETRY_RUN_STARTED` is awaited before processing starts.
2. Each entered orchestration scope gets a contiguous ordinal and bounded
   per-operation counters, updated in memory at actual method entry/exit.
3. All `S0_FAILURE_RETRY_SCOPE_TERMINAL` summaries and one
   `S0_FAILURE_RETRY_RUN_TERMINAL` manifest commit in one transaction after the
   logical invocation exits. The manifest declares the exact scope count.

Zero is observed only with a valid start, complete terminal, and every declared
scope. Zero Provider scopes is valid when the complete logical path made no
Provider calls (including a local-only path or a pre-Provider failure). Missing
starts/terminals/scopes, repeated ordinals/Provider identities, mixed revisions,
invalid counters, and unexpected payload fields yield `not_available`. Unrelated
bounded snapshot truncation/incompleteness yields at most `partial`.

Bounds: 128 orchestration scopes, four fixed operations per scope, seven fixed
counters per operation, 100,000 attempts per operation, at most 130 events per
logical invocation. Overflow marks coverage incomplete; processing continues.
No per-poll database writes are introduced. Worker threads create/use/close their
own database sessions; source/document association is checked with bounded column
projections. If a ProcessingRun already exists its source/document must match.
Events may precede run initialization, as with existing durable events. The
baseline CLI still requires an existing ProcessingRun; it never creates one to
make an early invalid-source attempt appear accepted.

Persistence is fail-open. A failed start write suppresses the final publication;
a failed terminal transaction leaves the start without closure. Crash or repeated
cancellation may also leave incomplete evidence. None is converted to zero.
Duplicate invocations sharing a processing run remain ambiguous, not silently
merged. No request/response payload, exception text, filename, path, URL, token,
raw storage reference, or raw Provider job ID is emitted. Correlation columns use
existing run/document identities; event payloads use hashed source/Provider scopes
and an opaque invocation scope with the exact Staging backend revision.

## Composition and verification

The new overlay runs after the final durable-event composition, both on initial
composition and on its idempotent fast path. Raw Production orchestration and PDF
entrypoint files remain unchanged in git. Runtime collection requires valid
`staging-revision.txt` and the existing durable-event gate. Both focused baseline
CI and Staging Integration CI exercise the new tests; artifact verification checks
the installed hooks and modules. PR CI must skip deployment.

Focused CI applies the existing orchestration diagnostics and only the
orchestration hunks of the **existing** Staging polling-resilience patch before
instrumentation. Without those prerequisites it
would exercise the raw non-retrying Production source, not the tested Staging
retry policy. The authoritative integration workflow continues to compose the
entire existing overlay chain.

Synthetic tests cover success, actual dispatched retries, normal polling, result
availability waits, nonretryable failure, uncertain submit, cancellation/deadline/
request limit before dispatch, cancellation during dispatch, retry budget, Provider
job failure vs RPC failure, concurrent scopes, overflow/mismatched association,
atomic rollback, privacy, malformed/missing/duplicate evidence, thread ownership,
disabled gates, and overlay idempotence. On/off comparison checks identical call
counts, sleeps and processing outcome. No real PDF is uploaded or processed.

The supplementary raw-source preprocessing suite
`tests/test_pdf_ingestion_async_preprocessing.py` has three existing failures when
run against the fully composed artifact: one outdated direct-call source marker
and two fake descriptors missing `document_id`. The same failures were reproduced
on the unchanged Staging baseline. This candidate does not alter that suite or
claim that the entire repository test suite passes.

The fresh small and medium runs after separately authorized Staging promotion
showed explicit zero failures/retries with complete durable closure, including
two sequential Provider scopes for medium. They do not replace synthetic
failure-path tests or establish real nonzero-retry/concurrent-scope acceptance.
No further PDF run is requested for the accepted success-path target. Any
separately scoped acceptance must pin the exact deployed revision and use a fresh run;
historical executions must not be relabeled as new-revision evidence. Local
tests alone do not establish Staging acceptance.
