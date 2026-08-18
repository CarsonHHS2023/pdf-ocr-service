# M2-003H End-to-End Processing Integration Plan

| Field | Value |
|---|---|
| Document Type | Integration Plan |
| Authority Domain | End-to-end processing integration planning and responsibility sequencing |
| Applies To | Atlas Storage, Transport Grant, Private Source Transport Endpoint, paddle-vl-api async job, Non-Persistent Orchestrator, and Raw Processing Result Ingestion |
| Implementation Status | Implementation planning approved; no live provider call performed |

## Status

Approved for implementation planning; no live provider call performed.

- Planning date: 2026-07-15.
- Atlas commit inspected: `3e4a4f0915e68d8fdbab66b0b6bc9c6e7f81a385`.
- Provider reference commit inspected: `3a790e3e4c0ececef316bd2ca5aa03d84f6c6159`.
- Provider implementation revision from inventory: `20b9ec9` (`Merge pull request #36 from CarsonHHS2023/codex/fix-merge-regression-in-modal_app.py`).
- Current deployment evidence accepted for this plan:
  - Atlas public origin: `https://carsonhhs-pdf-ocr-service.hf.space`.
  - The current Hugging Face deployment is disposable and contains no production data.
  - The current deployment uses one effective server process/worker/replica for this test posture.
  - The Transport Grant registry is in-memory and restart-losing.
  - Uvicorn application access logging is disabled.
  - A synthetic canary request did not appear in visible Container Logs.
  - Hugging Face internal CDN/reverse-proxy logging is not observable by the Space owner; this residual risk is accepted only for disposable M2 testing.
  - Provider configuration is present in the HF deployment as deployment secrets named `PADDLE_VL_API_BASE_URL` and `PADDLE_VL_API_BEARER_TOKEN`; their values were not read or recorded.
  - Required Backend CI passed and executed `tests/test_source_transport_grants.py` and `tests/test_source_transport_endpoint.py`.
  - Manual smoke owner: Carson.
  - Non-sensitive test fixture: `tests/fixtures/source_transport/test-only-source-transport.pdf`.
  - M2-003H is authorized for a controlled disposable test only.
- M2-003H authorization source: M2-003G.2 deployment gate authorization recorded in the source transport deployment preflight evidence.
- Provider reference handling: `/workspace/paddle-vl-api-reference` was read-only for this task and remained clean.

## Objective

Define the first controlled Atlas end-to-end processing path:

```text
Atlas Storage
    ↓
Transport Grant
    ↓
Private Source Transport Endpoint
    ↓
paddle-vl-api async job
    ↓
Non-Persistent Orchestrator
    ↓
Raw Processing Result Ingestion
```

The flow stops before:

- MinerU-Popo transformation;
- Structured Processing Output;
- M3 canonical content;
- Reader;
- application publication.

## Current implemented components

| Component | Source files | Current responsibility | Inputs | Outputs | Lifecycle ownership | Currently wired? | Missing integration boundary |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Storage | `app/storage/base.py`, `app/storage/models.py`, `app/storage/local.py`, `app/storage/memory.py`, `app/storage/dependencies.py` | Provider-independent byte persistence through `put`, `get`, `delete`, `exists`, and `stat`. | Bytes and optional `StorageReference`; reference for reads. | `PutResult`, bytes, stat metadata, or storage errors. | Storage provider implementation and caller-supplied retention policy. | Wired to Raw Result ingestion; source transport endpoint obtains a provider through its dependency. | No service currently resolves retained Source metadata into a processing attempt input. |
| Transport Grant Service | `app/processing/transport/service.py`, `app/processing/transport/models.py`, `app/processing/transport/errors.py`, `app/processing/transport/dependencies.py` | Process-local grant creation, token authorization, retrieval counting, revocation, inspection, and explicit cleanup. | `StorageReference`, Atlas/source identities, SHA-256, size, media type, TTL, replay/retrieval policy, safe metadata. | Descriptor plus plaintext token once on creation; authorized descriptors; revoked/expired descriptors. | In-memory process; restart-losing; caller owns grant use and terminal revocation decisions. | Wired to source transport endpoint for authorization/counting only. | No integration service creates one grant for a processing attempt and revokes it after orchestration policy. |
| Source transport endpoint | `app/routers/source_transport.py`, `app/main.py` | Private, schema-hidden `GET /internal/source-transport/{token}` byte delivery for authorized retained PDF bytes. | Opaque token path segment; grant registry dependency; storage provider dependency. | PDF bytes with no-store headers; collapsed `404`; transport failures. | Endpoint owns request-time authorization, storage read, byte-size/checksum verification, and retrieval counting. | Wired to grant service and storage dependencies. | No trusted public URL builder connects a newly issued token to the orchestrator/provider submission path. |
| Provider adapter | `app/processing/paddle_vl/client.py`, `app/processing/paddle_vl/models.py`, `app/processing/paddle_vl/mapping.py` | Async paddle-vl-api client for job submission, status polling, result retrieval, artifact download, protocol mapping, and safe error categories. | Configured base URL/bearer token; provider request from orchestration. | Provider submission/status/result/artifact models or safe provider errors. | Adapter owns provider HTTP behavior; configuration owns credentials. | Wired to the orchestrator through `DocumentProcessingProvider`. | No Atlas-level service prepares source transport URLs before orchestrator invocation. |
| Orchestration service | `app/processing/orchestration.py`, `app/processing/provider.py`, `app/processing/models.py`, `app/processing/errors.py` | Non-persistent one-attempt flow from already prepared HTTPS `source_url` through provider submission, polling, result retrieval, optional artifact download, and Raw Result ingestion. | `OrchestrationRequest`, `PollingPolicy`, provider, storage. | `OrchestrationOutcome` or `OrchestrationError`. | Orchestrator owns one run's in-memory lifecycle and does not persist attempts. | Wired to provider adapter protocol and Raw Result ingestion. | It expects an already prepared provider-reachable HTTPS source URL and does not create/revoke transport grants. |
| Raw Result ingestion | `app/processing/raw_result.py`, `app/processing/ingestion.py` | Canonicalize inline JSON or artifact bytes, validate provenance/metadata, persist Raw Processing Result payload, and return an envelope. | Raw result identity, source provenance, provider provenance, inline payload or artifact bytes, storage. | `RawProcessingResultEnvelope` with storage reference, size, SHA-256, media metadata, page summary. | Ingestion owns Raw Result payload persistence only. | Wired to orchestrator. | No combined integration outcome adds grant state, transport diagnostics, or Atlas attempt-level phases. |

## Integration gap

The orchestrator currently receives an already prepared provider-reachable source URL, but Atlas has no integration service that:

1. retrieves retained source metadata;
2. creates a transport grant;
3. constructs the trusted HTTPS transport URL;
4. passes the URL to the orchestrator;
5. revokes the grant safely afterward;
6. returns a combined integration result.

## Proposed integration service

Introduce a narrow service conceptually named `AtlasProcessingIntegrationService`; the implementation may use a different name if it preserves this boundary.

Responsibilities are limited to:

1. accept one retained source and one processing-attempt request;
2. validate source retention metadata;
3. create one Transport Grant;
4. build one temporary provider URL;
5. invoke the existing non-persistent orchestrator;
6. revoke the grant after the configured terminal boundary;
7. return a typed integration outcome;
8. preserve safe diagnostics.

It must not:

- implement Provider HTTP logic itself;
- call `Storage.get` directly for OCR processing;
- duplicate orchestration polling;
- duplicate Raw Result ingestion;
- update database records;
- call MinerU-Popo;
- publish Reader data.

## Input boundary

The proposed typed input should include these fields.

Atlas identity:

- processing attempt ID;
- correlation/request ID;
- Document ID;
- SourceFile ID.

Source evidence:

- opaque `StorageReference`;
- retained state confirmation;
- source SHA-256;
- source byte size;
- media type;
- optional ETag.

Provider request:

- provider name;
- provider job ID;
- provider request ID;
- result profile;
- provider job options.

Transport policy:

- trusted public origin;
- TTL;
- replay policy;
- optional retrieval limit;
- source-size policy.

Do not accept:

- caller-supplied full transport URL;
- caller-supplied token;
- local path;
- arbitrary `Host` header;
- database session;
- Reader fields.

Implementation-readiness correction: M2-003H-B should accept an already resolved retained-source descriptor from the caller instead of querying the ORM directly. The current ORM exposes `Document` and `SourceFile` columns that can hold Document ID, SourceFile ID, `storage_reference`, `retained`, checksum, byte size, MIME type, and filename, but there is no current repository/service method that resolves and validates those fields for processing. ETag is not an ORM column today; it should remain optional and caller supplied only when a trusted source descriptor has it. This keeps the integration service out of database-session ownership and avoids adding persistent ProcessingAttempt state.

## Trusted public origin

Current test origin: `https://carsonhhs-pdf-ocr-service.hf.space`.

Treat the origin as deployment configuration, not a hard-coded business constant. Accepted configuration name: `ATLAS_PUBLIC_SOURCE_TRANSPORT_ORIGIN`. The setting is optional at application startup and required only when the integration service is invoked.

Validation rules:

- HTTPS only;
- host required;
- no userinfo;
- no query;
- no fragment;
- no arbitrary path unless explicitly approved;
- normalized trailing slash;
- not inferred from incoming request headers.

No example may contain a real token-bearing URL.

## Transport URL construction

Construction rule:

```text
validated_origin.rstrip("/")
    + "/internal/source-transport/"
    + validated_opaque_token
```

Rules:

- construct only in process memory;
- use immediately for provider submission;
- never persist;
- never log;
- never include in error messages;
- never include in Raw Result;
- never include in outcome `repr`;
- never expose to Reader/application APIs.

Implementation should use a small pure `TransportUrlBuilder` if tests need isolated validation/redaction coverage. Otherwise private helper logic inside the integration service is acceptable. Recommendation: use the small pure builder because trusted-origin validation and URL construction are security-sensitive but do not need Storage, provider, or orchestration dependencies.

Implementation-readiness correction: current dataclass `repr` behavior is a blocker for a live smoke until fixed. `OrchestrationRequest` contains `source_url` and currently uses the default dataclass representation; the internal `ProviderSourceDocumentRequest`, `ProviderJobRequest`, and paddle-vl-api request dataclasses also temporarily contain the provider source URL and currently use default representations. Accepted decision: URL-bearing repr redaction and trusted-origin validation are included in M2-003H-B before any live token-bearing URL is constructed. Redaction requirements apply to dataclass repr, exception messages, logging, test assertion failure output, HTTP-client diagnostics, provider request debugging, and any tracing/APM surface.

## Grant creation sequence

Exact order:

1. validate source and deployment configuration;
2. create Transport Grant;
3. receive plaintext token once;
4. construct temporary URL in memory;
5. build orchestration request;
6. submit exactly one provider job.

The token exists only in:

- the grant creation result;
- the temporary URL;
- the immediate call stack;

and nowhere durable.

Temporary URL/token residency inventory for M2-003H-B:

- `TransportGrantCreationResult.token`;
- the URL builder local variables;
- the temporary URL string;
- `OrchestrationRequest.source_url`;
- the internal provider request document's `pdf_source_url`;
- the serialized provider JSON body sent to `POST /ocr/jobs`;
- HTTP client request internals during the immediate submission call.

The integration outcome, Raw Result envelope, errors, logs, PR evidence, and Reader/application responses must never retain the token or full URL.

## Submission uncertainty

When provider submission is uncertain:

- do not automatically submit a second job;
- do not immediately revoke the grant;
- retain the grant until TTL or explicit reconciliation decision;
- return a typed uncertain-submission outcome;
- preserve provider job ID;
- allow provider to retry source download within TTL;
- do not log URL/token.

This is critical because the provider may have accepted the job even if Atlas observed a timeout or temporary provider unavailability during submission.

## Grant revocation policy

### Successful Raw Result retention

Recommended:

- revoke after Raw Processing Result has been successfully retained;
- retained Source remains unchanged.

### Provider failed

- revoke when no further source retrieval is expected.

### Provider expired

- revoke current grant;
- future retry requires a new attempt and new grant.

### Orchestration timeout

- do not immediately revoke if the provider may still be running and may retry source retrieval;
- accepted decision: do not revoke immediately; keep active until TTL expiry unless reliable provider-terminal evidence proves no further retrieval is possible.

### Submission uncertain

- do not revoke immediately;
- accepted decision: keep active until TTL expiry or explicit reconciliation; do not automatically resubmit.

### Ingestion failure after Provider completion

- provider no longer needs source in normal flow;
- revoke after preserving safe diagnostics unless manual retry policy requires otherwise.

Grant revocation, Source deletion, and Raw Result cleanup are separate operations. Revoking a grant must never delete the retained Source, and Raw Result cleanup must follow an explicit test-artifact policy.

## Grant cleanup responsibility

- The integration service may revoke its own grant.
- Grant registry cleanup remains explicit and process-local.
- No background cleanup worker is added.
- Source bytes are never deleted by grant cleanup.
- Restart may discard grant state in the disposable test environment.

## Orchestrator handoff

Existing `OrchestrationRequest` fields map as follows:

| Integration input | `OrchestrationRequest` field | Notes |
| --- | --- | --- |
| processing attempt ID | `processing_attempt_id` | Direct identity mapping. |
| correlation/request ID | `correlation_id` | Optional direct mapping. |
| Document ID | `document_id` | Direct identity mapping. |
| SourceFile ID | `source_file_id` | Direct identity mapping. |
| constructed temporary HTTPS URL | `source_url` | Passed only in memory; must satisfy HTTPS validation. |
| source SHA-256 | `source_checksum_sha256` | Direct mapping; validated as SHA-256 hex. |
| media type | `source_media_type` | Direct mapping; expected fixture is `application/pdf`. |
| provider name | `provider_name` | For first smoke, `paddle-vl-api`. |
| provider job ID | `provider_job_id` | Exactly one job ID per attempt. |
| provider request ID | `provider_request_id` | Optional direct mapping. |
| result profile | `result_profile` | Must be one of `summary`, `standard`, `full`. |
| provider job options | `provider_job_options` | Passed through after current option validation. |
| source ETag | `source_etag` | Optional provenance. |
| expected page count | `expected_page_count` | Optional; use only if known from retained source evidence or fixture metadata. |
| Raw Result destination | `raw_result_storage_reference` | Optional preselected destination; otherwise ingestion lets storage allocate. |

Storage is injected into `ProcessingOrchestrator(provider=..., storage=...)`; the integration service should reuse the existing Storage provider injection instead of reading source bytes for OCR. Expected page count is optional and should remain `None` for the first smoke unless the fixture metadata is intentionally asserted.

## Provider adapter handoff

Existing adapter behavior to preserve:

- bearer token is loaded from configuration and sent only by the adapter;
- async submission uses `POST /ocr/jobs`;
- status polling uses `GET /ocr/jobs/{job_id}`;
- result retrieval uses `GET /ocr/jobs/{job_id}/result` with `profile`;
- artifact download uses `GET /ocr/jobs/{job_id}/artifact` when mapped result metadata requires it;
- provider source URLs must be HTTPS and are supplied in the request body sent by the adapter;
- provider `completed` remains an intermediate provider state until Atlas retrieves and ingests the Raw Result.

Known implementation issue to resolve in M2-003H-B: the integration service must not introduce new provider request shapes. It should build the existing `OrchestrationRequest` and let `_build_provider_request` plus the paddle-vl-api mapping handle provider-specific fields. Any missing provider option, timeout, or source-size signature mismatch must be fixed at the integration boundary or by documented adapter model extension tests, not by duplicating provider HTTP logic.

## Raw Result outcome

A successful integration result should contain:

- Atlas attempt/correlation/document/source identities;
- provider job/request IDs;
- terminal integration phase;
- provider terminal state;
- Raw Processing Result retained envelope;
- Raw Result `StorageReference`;
- byte size;
- SHA-256;
- elapsed time;
- poll count;
- safe warnings;
- grant ID;
- grant final state.

It must not contain:

- plaintext token;
- complete transport URL;
- provider bearer token;
- artifact bytes;
- provider source URL;
- local path.

## State model

Integration-level phases, distinct from provider and orchestration phases:

- `validating_source`;
- `creating_transport_grant`;
- `building_transport_url`;
- `invoking_orchestrator`;
- `processing`;
- `raw_result_retained`;
- `revoking_grant`;
- `completed`;
- `partial`;
- `submission_uncertain`;
- `timed_out`;
- `failed`.

Do not turn these into database statuses in this task.

## Failure matrix

| Failure | Owner | Retryability | Revoke? | New attempt required? | Safe category | Retained evidence |
| --- | --- | --- | --- | --- | --- | --- |
| Source not retained | Integration caller | Retry after retention fixed | No grant created | No, if same attempt has not submitted | User-correctable input | Attempt/source IDs, retained-state flag |
| Broken Source Storage reference | Storage/integration | Retry after reference repair | Revoke if grant was created | Usually yes if provider submission occurred | Internal storage failure | Safe storage error category, source IDs |
| Trusted origin missing | Deployment config | Retry after config is supplied | No grant created | No | Internal configuration | Missing-setting category, no URL |
| Invalid public origin | Deployment config | Retry after config fix | No grant created | No | Internal configuration | Redacted origin validation reason |
| Invalid source descriptor | Integration caller | Retry after descriptor is corrected | No grant created | No | User/internal input | Field-level safe validation reason |
| Grant creation failure | Grant service/integration | Retry if transient or bad input fixed | No grant created | No unless submission occurred | Internal processing | Safe grant error, source IDs |
| Grant registry failure | Grant service/deployment | Retry after process/service recovery | Unknown; inspect if possible | Maybe | Internal availability | Safe registry error, attempt ID |
| URL-construction failure | Integration | Retry after validation fix | Revoke created grant | No unless submission occurred | Internal configuration | Safe validation reason, grant ID |
| Provider configuration missing | Deployment config/provider adapter | Retry after secrets configured | Revoke if no submission happened; otherwise follow uncertainty policy | Maybe | Internal configuration | Safe provider config category |
| Provider authentication failure | Deployment/provider adapter | Retry after credential fix; stop smoke | Revoke when no source retrieval expected | Yes for smoke restart | Internal authentication | HTTP status category, redacted provider code |
| Submission uncertain | Provider adapter/integration | Reconcile first; do not resubmit automatically | No immediate revoke; TTL or explicit reconciliation | Maybe after reconciliation | Internal transient/uncertain | Provider job ID, safe error category, grant ID |
| Provider queued/running timeout | Orchestrator/provider | Retry polling/reconcile; no duplicate submit | Prefer TTL unless terminal state known | Maybe | Internal timeout | Last provider state, poll count, elapsed |
| Provider failed | Provider/orchestrator | New attempt after cause understood | Yes when no retrieval expected | Yes | Provider execution failed | Provider terminal state, safe error code |
| Provider expired | Provider/orchestrator | New attempt only | Yes | Yes | Provider expired | Expiry status, job ID |
| Result not ready | Provider/orchestrator | Continue bounded polling | No while job may continue | No | Provider not ready | Status category, poll count |
| Artifact expired | Provider/orchestrator | New attempt if artifact cannot be restored | Yes if terminal and unrecoverable | Yes | Provider artifact unavailable | Artifact metadata without URL/token |
| Raw Result ingestion failure | Ingestion/storage | Retry ingestion only if payload safely available | Revoke after safe diagnostics unless manual retry policy says otherwise | Maybe | Internal retention failure | Safe ingestion category, checksum/size if computed |
| Grant revocation failure | Grant service/integration | Retry revocation or allow TTL | Already terminal; attempt completed/partial | No | Internal cleanup warning | Grant ID, safe revocation error |
| HF restart/process loss | Deployment/grant registry | Repeat controlled setup | Grant state lost; URL should fail | Yes if submission not terminal/reconciled | Disposable deployment limitation | Restart timestamp, lost grant state |
| Transport endpoint 404 | Endpoint/grant/source evidence | Stop and reconcile grant/source state | Inspect grant if possible | Maybe | Source unavailable | HTTP 404 category, grant ID if safe |
| Transport endpoint 500/503 | Atlas deployment/storage | Retry after deployment/storage fixed; stop if during submission | If reachable later and no provider need, revoke; otherwise TTL may already fail | Maybe | Internal availability | HTTP status category, no URL |
| Transport endpoint unavailable | Atlas deployment | Retry after deployment fixed; stop if during submission | If reachable later and no provider need, revoke; otherwise TTL may already fail | Maybe | Internal availability | HTTP status category, no URL |
| Provider source-download timeout | Provider/Atlas endpoint | Reconcile; no automatic resubmit | Prefer TTL until terminal/reconciled | Maybe | Source retrieval timeout | Provider safe error/status, retrieval count |
| Job identity mismatch | Orchestrator/provider | Stop; reconcile provider job | Revoke when no retrieval expected | Yes | Provider protocol mismatch | Expected/actual job IDs redacted as needed |
| Result profile mismatch | Orchestrator/provider | Stop; fix request/profile mismatch | Revoke when terminal | Maybe | Provider protocol mismatch | Expected/actual profile category |
| Result-not-ready exhaustion | Orchestrator/provider | Continue only by explicit reconciliation | Do not revoke if provider may still run | Maybe | Provider not ready | Poll/result request counts |
| Artifact checksum mismatch | Provider/ingestion | Stop; new attempt or artifact repair | Revoke when no source retrieval expected | Maybe | Integrity failure | Expected/actual artifact checksum if safe |
| Raw Result Storage conflict | Ingestion/storage | Retry only with new storage reference or same bytes | Revoke after preserving safe diagnostics | Maybe | Internal retention conflict | Storage conflict category |
| Source checksum mismatch at provider | Provider/integration/source evidence | Stop; new attempt after source evidence fixed | Yes | Yes | Integrity failure | Expected checksum, provider mismatch category |
| Source checksum mismatch at transport endpoint | Endpoint/storage/source evidence | Stop; endpoint returns failure | Revoke current grant | Yes after repair | Integrity failure | Expected checksum, storage stat/category |

## Security boundary

- No secret, token, or full URL logging.
- No token in `repr`.
- No `StorageReference` in URL.
- No local path in input, provider request, result, or evidence.
- HTTPS only for provider-reachable source URL.
- One effective test worker/process/replica for the disposable smoke posture.
- Non-sensitive test PDF only.
- No customer data.
- Access-log residual risk is accepted only for disposable M2 testing because HF internal CDN/reverse-proxy logs are not observable by the Space owner.
- Provider credentials remain deployment secrets.
- One provider job submission only.
- No token-bearing URL in screenshots, PR comments, pytest assertion failure output, model/dataclass repr, exception chains, HTTPX debug logs, provider request-body logs, tracing, or APM telemetry.

## Manual smoke phases

### Phase 0 — Pre-submit transport verification

Accepted decision: Phase 0 uses in-process service/TestClient evidence. The deployed app has no public grant-creation API, the grant registry is process-local, and no grant-creation HTTP API will be added.

Required sequence:

1. M2-003H-B implements the integration service and safe in-process/TestClient verification before provider submission.
2. For CI/local evidence, use TestClient or direct in-process service calls to write/read the deterministic test PDF through real Storage, create a short-lived grant, build a URL in memory, GET the route, verify exact bytes/size/checksum/headers, verify retrieval count, revoke, verify 404, verify Source remains retained, and verify no token appears in visible logs.
3. Record Phase 0 as in-process/TestClient evidence. Do not authorize or add any public grant-creation HTTP API.
4. Always use a new grant for the actual Provider smoke.

### Phase 1 — Provider authentication and configuration

Perform only a safe authenticated provider check if both the verified protocol and the current Atlas adapter support it. Verification found `/health/config` is unauthenticated in the provider protocol and the current Atlas adapter does not expose a health/config client method. Therefore Phase 1 must not imply an existing authenticated health operation. For the current implementation posture, record local configuration presence without printing values, optionally perform only an unauthenticated `/health/config` check outside the adapter if the smoke owner approves it as non-auth readiness evidence, and otherwise proceed to exactly one controlled job submission. Do not treat health/config as OCR model readiness unless a future protocol revision says so.

### Phase 2 — Submit one async provider job

- one non-sensitive test PDF;
- one Atlas attempt;
- one provider job ID;
- one request ID;
- source checksum supplied;
- selected result profile explicitly recorded;
- no automatic resubmit.

### Phase 3 — Provider source retrieval

Verify:

- endpoint retrieval count increases;
- Provider reports source download success or proceeds to processing;
- source checksum is accepted;
- no token appears in visible logs.

Stop immediately on leakage or integrity failure.

### Phase 4 — Poll and retrieve result

- poll within bounded deadline;
- preserve provider status;
- handle result-not-ready;
- retrieve inline or artifact result;
- do not call MinerU-Popo.

### Phase 5 — Retain Raw Result

- ingest provider evidence through existing ingestion boundary;
- verify Raw Result `StorageReference`;
- verify size/SHA-256;
- verify no temporary provider URL retained.

### Phase 6 — Revoke and cleanup

- revoke grant according to terminal-state policy;
- confirm later GET returns 404;
- confirm original Source remains;
- clean disposable Raw Result/test artifacts only according to existing policy;
- record test outcome without secrets.

## Stop conditions

Immediate stop conditions:

- complete token appears in any visible persistent log;
- Provider authentication fails unexpectedly;
- source checksum mismatch;
- endpoint returns bytes for revoked/invalid grant;
- duplicate provider job submission risk;
- unexpected provider protocol revision;
- Raw Result cannot be retained safely;
- multiple workers/replicas detected;
- customer/production data involved;
- provider repeatedly downloads beyond accepted replay policy;
- source transport endpoint becomes unavailable during submission.

## Smoke evidence record

Safe evidence template:

```text
M2-003H-D smoke evidence
Timestamp start/end:
Atlas commit:
Provider implementation revision:
Provider reference commit:
Fixture path:
Fixture SHA-256:
Fixture size:
Result profile: standard
Provider job ID: <type-prefix>…<last-four>
Provider request ID: <type-prefix>…<last-four>
HTTP status categories:
Provider lifecycle states:
Transport retrieval count:
Raw Result StorageReference: <internal only if safe>
Raw Result SHA-256:
Raw Result size:
Grant final state: revoked|expired
Outcome: PASS|FAIL
Notes: <safe diagnostics only>
```

May record:

- timestamps;
- Atlas commit;
- Provider deployment revision;
- redacted job/request IDs;
- fixture checksum;
- HTTP status categories;
- provider lifecycle states;
- retrieval count;
- Raw Result `StorageReference` only if safe inside internal record;
- Raw Result checksum/size;
- grant revoked/expired state;
- PASS/FAIL.

Must not record:

- bearer token;
- transport token;
- full source URL;
- full signed URL;
- Authorization header;
- provider raw result body in PR comments;
- source bytes.

## Implementation split

### M2-003H-B

Implement Transport URL builder, URL-bearing model redaction, trusted-origin validation using `ATLAS_PUBLIC_SOURCE_TRANSPORT_ORIGIN`, and Atlas processing integration service with fully mocked tests. The origin setting remains optional at application startup and required only when the integration service is invoked.

No live provider call.

### M2-003H-C

Independent verification of the integration service.

### M2-003H-D

Run the controlled manual live-provider smoke and record redacted evidence.

### M2-003H-E

Close M2-003H and update milestone status.

Use different identifiers only if current M2 task numbering requires it.

## Required implementation tests

Plan tests for M2-003H-B:

- trusted origin validation;
- URL construction;
- token/full URL redaction;
- one grant per attempt;
- one provider submission;
- valid orchestration handoff;
- success revocation;
- provider failure revocation;
- timeout does not revoke prematurely;
- uncertain submission does not revoke prematurely;
- ingestion failure handling;
- grant-revocation failure handling;
- no source deletion;
- no token persistence;
- no database;
- no Reader/MinerU-Popo;
- current adapter/orchestrator models used directly;
- current model/request repr redaction for URL-bearing objects;
- origin config missing;
- URL not retained in outcome;
- URL not present in errors;
- provider request captures URL only in the immediate submission payload;
- source descriptor accepted without DB access;
- restart/grant-loss simulation;
- no duplicate ingestion.

No live provider calls in CI.

## Definition of done for M2-003H

1. integration service implemented and independently verified;
2. exactly one controlled live provider job submitted;
3. Provider retrieves the Atlas transport URL;
4. source checksum verified;
5. Provider reaches a terminal state;
6. result retrieved;
7. Raw Processing Result retained in Atlas Storage;
8. original Source remains retained;
9. transport grant revoked or expires according to policy;
10. no secrets/full URL in logs or committed evidence;
11. no automatic duplicate submission;
12. smoke evidence recorded;
13. no MinerU-Popo/M3/Reader integration added;
14. M2 documentation updated.

## Accepted human decisions

The following decisions are accepted and are no longer unresolved for M2-003H-A:

| Decision | Accepted value | Applies to |
| --- | --- | --- |
| URL-bearing repr redaction and trusted-origin validation | Included in M2-003H-B | M2-003H-B |
| Trusted public-origin setting name | `ATLAS_PUBLIC_SOURCE_TRANSPORT_ORIGIN`; optional at application startup and required only when the integration service is invoked | M2-003H-B |
| Phase 0 mechanism | In-process service/TestClient evidence; no grant-creation HTTP API will be added | M2-003H-B/D |
| Timeout revocation | Do not revoke immediately on orchestration timeout; keep the grant active until TTL expiry unless reliable provider-terminal evidence proves no further retrieval is possible | M2-003H-B/D |
| Submission uncertainty | Keep the grant active until TTL expiry or explicit reconciliation; do not automatically resubmit | M2-003H-B/D |
| First live-smoke result profile | `standard` | M2-003H-D |
| First live-smoke transport grant TTL | 20 minutes | M2-003H-D |
| First live-smoke orchestration timeout | 5 minutes | M2-003H-D |
| First live-smoke polling | Initial poll interval 2 seconds, maximum poll interval 10 seconds, backoff factor 1.5 | M2-003H-D |
| First live-smoke provider options | Minimal defaults, one document, no simulation options | M2-003H-D |
| Successful smoke Raw Result retention | Retain the first successful smoke Raw Processing Result through M2-003H closeout for inspection | M2-003H-D/E |
| Job/request ID evidence redaction | Type prefix plus final four characters | M2-003H-D |
| Smoke owner and approver | Carson | M2-003H-D |

No remaining M2-003H-A human decision is unresolved. M2-003H-D still requires the accepted smoke owner/approver to authorize execution immediately before any live provider job is submitted.

## Non-goals

This planning task does not:

- implement the integration;
- call Provider;
- submit a job;
- create a real grant;
- expose a token URL;
- modify routes;
- add persistent state;
- call MinerU-Popo;
- create Structured Processing Output;
- update Reader;
- add M3 data models;
- alter production deployment architecture.

## Decision summary

| Decision | Evidence | Recommendation | Human confirmation required? | Blocking phase |
| --- | --- | --- | --- | --- |
| Proceed with integration planning only | M2-003G.2 authorized M2-003H for disposable controlled testing; no provider call performed in this task | Proceed to M2-003H-B with accepted decisions recorded | No | M2-003H-B |
| Use trusted configured public origin | Accepted HF origin is `https://carsonhhs-pdf-ocr-service.hf.space`; origin must not be inferred from headers | Use `ATLAS_PUBLIC_SOURCE_TRANSPORT_ORIGIN`, optional at startup and required on integration invocation | No | M2-003H-B |
| Build token URL only in memory | Grant service returns plaintext token once; endpoint accepts token in path | Use a narrow builder/helper and redact from repr/logs/errors | No | M2-003H-B |
| Fix URL-bearing repr before smoke | Current request dataclasses would expose `source_url`/`pdf_source_url` in default repr | Include redacted repr or equivalent safe boundary in M2-003H-B before constructing real token URLs | No | M2-003H-B |
| Preserve one-submission rule | Orchestrator can surface `submission_uncertain`; provider may have accepted the job | On submission uncertainty, keep grant active until TTL expiry or explicit reconciliation and do not automatically resubmit | No | M2-003H-B/D |
| Revoke grants by terminal policy | Source transport grants are independent of Source retention and Raw Result cleanup | Revoke after success/failure/expiry when no retrieval expected; do not immediately revoke on timeout/uncertainty | No | M2-003H-B/D |
| Keep integration non-persistent | Current orchestrator and grant registry are non-persistent foundations | Return typed in-memory outcome; do not add DB statuses in M2-003H-B | No | M2-003H-B |
| Smoke with non-sensitive fixture only | Accepted deployment facts specify disposable HF and test-only PDF | Use `tests/fixtures/source_transport/test-only-source-transport.pdf` only | No | M2-003H-D |
| Use accepted first smoke settings | Human decisions recorded in this plan | `standard`, 20-minute grant TTL, 5-minute orchestration timeout, 2s/10s/1.5 polling, minimal defaults, one document, no simulation options | No | M2-003H-D |
| Retain first successful smoke Raw Result through closeout | Human decision recorded in this plan | Keep for inspection through M2-003H closeout, then clean according to closeout policy | No | M2-003H-D/E |
| Redact smoke evidence IDs | Human decision recorded in this plan | Type prefix plus final four characters | No | M2-003H-D |
| Stop before MinerU-Popo/M3/Reader | M2 scope is Raw Processing Result retention | Do not add downstream transformations or publication | No, already scoped | M2-003H-B/D |
