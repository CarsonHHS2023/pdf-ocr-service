# Safe processing operator entry

| Field | Value |
|---|---|
| Document Type | Operator Guidance |
| Authority Domain | safe operator entry for a bounded processing test deployment |
| Applies To | disposable M2 test deployment; `POST /internal/operator/process-once`; operator authorization; retained test source descriptors; provider invocation through `EndToEndProcessingIntegrationService.process()`; operator-safe response handling |
| Execution Scope | One controlled end-to-end processing integration invocation inside the running Hugging Face application process |

Task M2-003H-D adds a disposable, operator-only entry point for one controlled end-to-end processing integration invocation inside the running Hugging Face application process.

## Purpose and status

The route is for the disposable M2 test deployment only. It is not a public product API and must not be exposed to normal users. It exists so Carson can run the first controlled live provider smoke from the same process that owns the in-memory source transport grant registry, configured storage provider, private source transport endpoint, and integration service.

## Route and enablement

The mechanism is:

```text
POST /internal/operator/process-once
```

The route is excluded from OpenAPI. It is disabled by default with:

```text
ATLAS_PROCESSING_OPERATOR_ENABLED=false
```

Enable it only for the disposable smoke deployment:

```text
ATLAS_PROCESSING_OPERATOR_ENABLED=true
ATLAS_PROCESSING_OPERATOR_TOKEN=<high-entropy independent secret>
ATLAS_PUBLIC_SOURCE_TRANSPORT_ORIGIN=<trusted HTTPS origin>
```

The operator token is independent from `PADDLE_VL_API_BEARER_TOKEN`; do not reuse provider credentials.

## Authentication policy

The route requires:

```text
Authorization: Bearer <ATLAS_PROCESSING_OPERATOR_TOKEN>
```

Disabled, missing bearer, malformed bearer, invalid bearer, and an enabled route with a missing or low-entropy configured token all collapse to the same generic `404 Not found` response. This hides route existence for the disposable internal entry. Comparison uses constant-time `secrets.compare_digest`, and the route never echoes or logs the Authorization header.

## Request boundary

The request accepts one retained test source descriptor and provider identity metadata:

- processing attempt ID and optional correlation ID;
- document ID and source file ID;
- opaque `StorageReference`;
- retained flag, SHA-256, byte size, media type, optional ETag, and filename metadata;
- provider name, provider job ID, and optional provider request ID;
- `result_profile=standard`;
- `test_fixture_only=true` with the committed fixture SHA-256, byte size, and PDF media type.

The request rejects extra fields, non-retained sources, invalid references/checksums/sizes/media types, non-`standard` profiles, provider options, and `test_fixture_only` requests whose checksum/size/media type do not match the committed fixture evidence. It does not accept source URLs, transport tokens, provider bearer tokens, operator tokens in the body, local paths, arbitrary provider base URLs, arbitrary Atlas public origins, database/session identifiers, Reader fields, or MinerU-Popo fields.

## Dependency composition and ownership

After authorization and validation, including committed fixture-evidence validation, the route constructs the existing typed `ProcessingIntegrationRequest` and delegates to `EndToEndProcessingIntegrationService.process()` exactly once. The route does not create grants, build source URLs, poll provider status, ingest raw results, or revoke grants directly.

The default same-request composition uses:

- the application-lifetime `InMemoryTransportGrantService` from source transport dependencies;
- the configured storage provider;
- a request-owned `PaddleVLClient` and `ProcessingOrchestrator`;
- the configured `ATLAS_PUBLIC_SOURCE_TRANSPORT_ORIGIN`.

The request-owned provider client is closed in a `finally` block on success, integration failure, validation conversion failure, or unexpected failure. Tests may override the dependency with an externally owned service; externally owned fake dependencies are not closed as Paddle clients.

No provider client is constructed until after operator authentication and request validation succeed, and no network call occurs at import time or startup.

## Synchronous timeout limitations

The route runs synchronously and delegates to the integration service with the accepted first-smoke policy: 20 minute grant TTL, 5 minute orchestration timeout, 2 second initial poll interval, 10 second maximum poll interval, and 1.5 backoff factor.

Risks remain for the live smoke: the Hugging Face proxy or client may time out before five minutes, the browser/client may disconnect, the provider job may continue, the process may restart, and there is no persistent recovery. If the platform request timeout is shorter than the smoke duration, that is a deployment blocker for M2-003H-E rather than justification to add a queue in this PR.

## Safe response and redaction

Responses include only operator-safe metadata: status, processing attempt ID, provider terminal status, integration terminal phase, raw result storage reference/checksum/size, poll count, elapsed seconds, grant final state, revocation status, safe warnings, and typed error category/phase when applicable.

Provider job IDs, provider request IDs, and grant IDs are redacted as type prefix plus final four characters, for example `job_...7f3a` and `req_...91bc`. Runtime IDs are not mutated internally.

The route never returns source transport tokens, complete source transport URLs, provider bearer tokens, operator bearer tokens, source bytes, artifact bytes, local paths, raw provider responses, or HTTP Authorization headers.

## Tests

Focused tests are in `tests/test_processing_operator_endpoint.py`. They cover disabled/default behavior, authentication collapse, OpenAPI exclusion, method handling, request validation, dependency override and close behavior, exactly-one invocation, response redaction, timeout/submission uncertainty, definite integration failure, unexpected failure, ID redaction, and application-lifetime grant dependency identity.

All tests are in-process with fakes. They do not submit live provider jobs, call Modal, authenticate to a provider, or allow a source transport URL to leave the test process. The route still requires a pre-existing retained `StorageReference` for the committed fixture bytes in the deployment storage before M2-003H-E can run.

## Non-goals

This route does not add a public processing API, upload integration, OCR route integration, Reader integration, database models, migrations, ProcessingAttempt persistence, background workers, queues, job listing, job polling, cancellation, batch jobs, callbacks/webhooks, MinerU-Popo calls, structured processing output, object storage, or provider protocol changes.

## Live-smoke prerequisites

Do not start M2-003H-E until M2-003H-D is independently reviewed, CI is green, and the disposable deployment has:

```text
ATLAS_PROCESSING_OPERATOR_ENABLED=true
ATLAS_PROCESSING_OPERATOR_TOKEN=<secret>
ATLAS_PUBLIC_SOURCE_TRANSPORT_ORIGIN=<trusted HTTPS origin>
```

The manual smoke owner and approver is Carson. The first successful Raw Processing Result remains retained through M2-003H closeout. A live smoke is blocked until the committed fixture source has been retained in deployment storage and the operator request can reference that retained `StorageReference` without exposing secrets. The disposable [smoke fixture preparation](smoke-fixture-preparation.md) route documents the operator-authenticated, fixed-fixture-only preparation step.

## Next task

Recommended next task: **M2-003H-E Run Controlled Live Provider Smoke**.
