# M2-003D Non-Persistent Processing Orchestration

| Field | Value |
|---|---|
| Document Type | Orchestration Design |
| Authority Domain | Non-persistent processing orchestration and one-attempt in-memory execution responsibilities |
| Applies To | `OrchestrationRequest`, `PollingPolicy`, provider job submission, status polling, result retrieval, optional artifact download, Raw Processing Result ingestion, and in-memory orchestration outcomes |
| Implementation Status | Component remains unused pending independent verification and a later integration task |

This document describes the narrow in-memory orchestration service added for
M2-003D. It connects the provider adapter to the Raw Processing Result ingestion
boundary without changing upload, OCR, Reader, or background processing paths.

## Purpose

The service coordinates one Atlas processing attempt for one Atlas Document and
one primary SourceFile. It submits one provider job, polls provider status,
retrieves the caller-selected result profile, downloads the artifact when the
provider returns artifact metadata, ingests the Raw Processing Result through
Atlas Storage, and returns a typed in-memory outcome.

Provider completion is intentionally not Atlas success. Atlas success for this
service requires retained Raw Processing Result evidence.

## Architecture flow

```text
approved provider-reachable HTTPS source
    -> provider client submit_job()
    -> provider status polling
    -> provider result retrieval
    -> artifact download when required
    -> Raw Processing Result ingestion
    -> in-memory orchestration outcome
```

The flow stops at Raw Processing Result retention. It does not call MinerU-Popo,
does not create Structured Processing Output, and does not update Document
business status.

## Input model

`OrchestrationRequest` contains only the one-attempt data needed at this
boundary:

- Atlas identity: processing attempt ID, correlation ID, Document ID, SourceFile
  ID.
- Source transport: provider-reachable HTTPS source URL, source SHA-256,
  optional ETag, source media type.
- Provider request: provider name, provider job ID, provider request ID, result
  profile, provider job options, optional expected page count.
- Ingestion: optional caller-supplied Raw Result storage reference when the
  storage boundary supports create-only writes to that reference.

It intentionally excludes `SourceFile.storage_reference`, local filesystem paths,
signed URL persistence, database sessions, Reader fields, and route-specific
objects.

## Validation

The request validates required identities, HTTPS source URL, SHA-256 checksum,
non-negative expected page count, and supported result profiles. The polling
policy validates positive timeout and poll intervals, maximum interval
consistency, and positive maximum status request count when supplied.

## Polling policy

`PollingPolicy` is explicit and bounded. It supports:

- total timeout based on an injected monotonic clock;
- initial poll interval;
- maximum poll interval;
- optional exponential backoff;
- optional maximum status requests;
- optional maximum result requests for repeated `RESULT_NOT_READY`;
- injected sleep function for tests.

The orchestrator does not use wall-clock datetime arithmetic, does not busy-loop,
does not poll indefinitely, clamps sleeps to the remaining deadline, and does not start a new Atlas processing attempt. `poll_count` counts provider status requests only; result-retrieval attempts are separately bounded by `max_result_requests` when configured.

## Phase model

The provider-independent in-memory phases are:

- `validating`
- `submitting`
- `provider_queued`
- `provider_running`
- `provider_completed`
- `retrieving_result`
- `downloading_artifact`
- `ingesting_raw_result`
- `raw_result_retained`
- `provider_partial_failed`
- `failed`
- `timed_out`
- `submission_uncertain`

These are not database statuses and are not mapped to Document status.

## Submission behavior

The service builds one provider request from the Atlas input and submits exactly
one provider job. If the accepted response is malformed or the returned provider
job ID differs from the requested provider job ID, orchestration fails closed and
polling is not started.

## Uncertain submission

If submission times out or fails with a transient transport/unavailable provider
error, the orchestrator raises a typed `submission_outcome_uncertain` error. It
preserves the provider job ID and indicates that reconciliation is needed. It does
not blindly resubmit and does not start a second Atlas attempt.

## Result retrieval

After provider `completed` or `partial_failed`, the orchestrator requests the
caller-selected result profile. It does not silently fall back to a weaker
profile. A `RESULT_NOT_READY` provider response is treated as pollable within the
same deadline because provider completion does not guarantee immediate result
availability. Repeated not-ready responses never resubmit the job and may be
bounded with `max_result_requests`.

Malformed profile or identity combinations are rejected.

## Inline path

When the result includes inline provider payload, the service passes the raw
adapter-specific payload to `ingest_inline_result`. The payload is not normalized
by orchestration. The retained envelope includes safe provider provenance,
selected profile, terminal provider status, source checksum, source media type,
warnings/errors, and optional page summary.

## Artifact path

When the result includes artifact metadata, the service calls the provider
artifact operation, relies on the provider client to verify bytes against safe
metadata, and passes the exact bytes to `ingest_artifact_result`. The service does
not expose or retain artifact URLs, does not decompress, does not transform, and
does not persist artifact bytes outside Atlas Storage.

Artifact expiry or retrieval failure is an orchestration artifact failure, not a
claim that provider execution itself failed.

## Partial failure

For provider `partial_failed`, the service preserves that terminal provider state
and attempts to retain usable inline or artifact evidence. The returned outcome is
partial, not success. If no usable result evidence is available, it returns a
partial outcome without a retained Raw Processing Result. Missing-page diagnostics
are preserved through an invalid page summary when partial evidence is otherwise
usable; malformed completed-result page mappings fail closed.

## Timeout

On timeout or maximum status request exhaustion, orchestration stops waiting and
raises a typed timeout with elapsed time, poll count, and provider job ID. No
provider cancellation is attempted because cancellation is not implemented. The
provider job may continue running after Atlas stops waiting.

## Raw Result ingestion

The only durable write performed by this service is Raw Processing Result object
retention through the existing Atlas Storage ingestion boundary. The service does
not write orchestration phase, poll history, provider job status, Document status,
ProcessingAttempt, retry state, or scheduler state.

## Security

Outcomes and errors omit bearer tokens, source URLs, artifact URLs, raw provider
payloads, artifact bytes, and transport headers. Provider-client messages are
redacted before becoming orchestration error text. Provider provenance includes
only safe fields available from typed provider status/result models.

## No persistence and no route integration

No route, startup hook, upload path, OCR path, Reader path, or legacy local OCR
pipeline constructs or invokes the orchestrator in this PR. The component remains
unused pending independent verification and a later integration task.

## Explicit non-goals

This PR does not add database models, migrations, background workers, queue
infrastructure, public APIs, retries across new Atlas attempts, webhooks,
MinerU-Popo calls, Structured Processing Output, Reader compatibility, cleanup
workers, or live provider calls in CI.

## Next step

After M2-003D is independently verified, evaluate M2-003E: Define Processing
Attempt Persistence Model. Do not authorize that step from this document alone.
