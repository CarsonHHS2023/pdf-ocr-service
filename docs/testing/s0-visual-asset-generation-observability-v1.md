# S0 visual-asset generation observability v1

## Status and scope

This contract defines the S0 producer and collector boundary for
`visual_asset_generation_seconds`. The implementation is Staging-only and does
not change PDF selection, rendering, OpenCV behavior, enhancement policy,
storage placement, retries, failure handling or Reader output.

Implementation and CI do not constitute Staging acceptance. Until a fresh
eligible run is collected from an exact deployed revision, the required metric
remains `not_instrumented` in the accepted S0 baseline. S0 and M5 remain In
Progress; S1/S2 are not started.

## Exact measured boundary

The measured operation is one invocation of the final composed
`pdf_canonicalization.enrich_candidate_with_pdf_visual_assets(...)` callable.
The observer is installed after the existing visual-crop/OpenCV compatibility
layers, so the interval includes work performed by that final callable chain:

- coordinate-aligned PDF page/crop rendering;
- the configured OpenCV visual transform;
- visual rendition writes;
- configured visual enhancement when it is enabled;
- final visual metadata/lifecycle attachment inside the enrichment chain.

The interval explicitly excludes:

- the storage read that obtains the coordinate-aligned PDF bytes;
- SPR normalization and structure refinement, including page-image preparation;
- SPR persistence;
- candidate transformation before visual enrichment;
- candidate, selection and ProcessingRun database commits after enrichment;
- Reader fetch, browser decode and paint.

`canonicalization_duration_seconds` contains this interval and remains a
separate, broader metric. The two values must not be added.

The clock is `time.perf_counter_ns()`. The producer records an exact integer
nanosecond delta and the collector converts it to seconds. Persisted event
timestamps are not used to reconstruct the duration.

## Producer lifecycle

The final `PdfCanonicalizationService.canonicalize(...)` wrapper owns one
observation root using the retained envelope's ProcessingRun, Document and
SourceFile identities plus the exact Staging revision. A `ContextVar` transfers
that root through the already-existing `asyncio.to_thread` canonicalization
boundary. The synchronous canonicalization worker owns measurement settlement
and the final database write; cancellation of its asyncio waiter does not create
a detached event-loop publisher.

The producer buffers exactly two records and writes them in one database
transaction after canonicalization settles:

| Ordinal | Event | Meaning |
|---:|---|---|
| 0 | `S0_VISUAL_ASSET_GENERATION_RUN_STARTED` | One canonicalization observation root exists. |
| 1 | `S0_VISUAL_ASSET_GENERATION_RUN_TERMINAL` | The visual call completed, failed, was not required, or became invalid. |

Both records contain only the fixed common fields `contract_version`,
`measurement_scope`, `method`, `observation_id`, hashed `source_scope_id`,
`backend_revision` and `ordinal`. The terminal additionally contains:

- `operation_outcome`;
- `clock_status` and `duration_ns`;
- counts of newly generated asset and rendition identities;
- a fixed allowlisted reason.

No filename, title, content, path, URL, token, storage reference, raw exception
message or provider body is allowed. Payloads must survive the shared sanitizer
unchanged and stay within the existing 8192-byte UTF-8 limit.

Observation failures remain fail-open for document processing. A missing or
failed evidence write is never converted to zero. A second enrichment call in
one canonicalization root executes normally but invalidates that root's metric.

## Collector admission

The strict collector requires all of the following before returning `observed`:

- exactly two decodable, bounded events with ordinals 0 and 1;
- one common observation/source/revision identity;
- exact SourceFile association and a succeeded ProcessingRun;
- `operation_outcome=completed` and `clock_status=measured`;
- a nonnegative exact duration within the integer contract;
- at least one newly generated asset identity and one newly persisted rendition.

Missing, duplicated, mixed, malformed, oversized, unknown-field, failed,
not-required, clock-unavailable, zero-generated-asset or zero-rendition evidence maps to
`not_available`. Complete absence of these event names maps to
`not_instrumented`. The collector does not choose the newest duplicate root and
does not infer this metric from canonicalization time, artifact size, process
RSS or existing visual metadata. It also exposes the validated method, scope,
generated counts and Backend revision as a separate auxiliary breakdown; those
fields are not additional duration metrics.

## Verification and acceptance gates

The implementation gate requires synthetic success, zero-duration, no-call,
delegate-failure, invalid-clock, invalid-result-count, duplicate/mixed identity,
privacy, oversized-payload, disabled-Staging and atomic local-SQL tests. The
composed test must prove the wrapper is installed after the existing visual
chain and that only the exact event contract maps the required metric.

After exact-head CI, artifact verification and an authorized Staging deploy, use
the cheapest fresh PDF fixture that is known to generate at least one durable
visual asset. Confirm the exact deployed revision, run/source identity, two-event
ordinal sequence, duration, generated counts and privacy audit. A multi-page
rerun is not automatically required because this metric is one canonicalization
operation rather than a Provider shard aggregate. No 100-page or 528-page run is
authorized by this contract.

Production remains unchanged until a separate promotion decision.
