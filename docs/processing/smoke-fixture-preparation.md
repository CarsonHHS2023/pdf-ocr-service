# Smoke fixture preparation

| Field | Value |
|---|---|
| Document Type | Fixture Preparation Procedure |
| Authority Domain | controlled preparation of the smoke-test source fixture |
| Applies To | temporary H-E smoke workflow; `POST /internal/operator/prepare-smoke-fixture`; fixed fixture `test-only-source-transport.pdf`; runtime resource packaging; Storage retention; checksum, size, media type, and PDF-header validation |

Task M2-003H-E0 adds a disposable, operator-only mechanism that retains the fixed non-sensitive source fixture in the configured Atlas Storage before the controlled live provider smoke.

## Purpose and scope

The route prepares exactly one fixture for later use by `POST /internal/operator/process-once`:

```text
POST /internal/operator/prepare-smoke-fixture
```

It is hidden from OpenAPI, disabled by default, and belongs only to the temporary H-E smoke workflow. It is not a public upload API and must not be reused for arbitrary documents.

## Fixed fixture and packaging

The canonical runtime resource is packaged under:

```text
app/resources/source_transport/test-only-source-transport.pdf
```

It is byte-for-byte synchronized with the committed test fixture at:

```text
tests/fixtures/source_transport/test-only-source-transport.pdf
```

Production code reads the runtime resource instead of importing from `tests/`, which keeps deployment packaging explicit while preserving a test assertion that both files match.

Accepted fixture evidence:

- byte size: `605`
- SHA-256: `fb084e43d06e039118d2a72a40353eebcec09abdbe732cf30917608723126420`
- media type: `application/pdf`
- PDF header: required

The route fails closed before Storage writes if the resource is missing, not a regular file, has different bytes, has a different hash or size, has a different media type, or lacks a PDF header.

## Authentication and request boundary

The route reuses the existing operator controls:

```text
ATLAS_PROCESSING_OPERATOR_ENABLED=true
ATLAS_PROCESSING_OPERATOR_TOKEN=<high-entropy independent secret>
Authorization: Bearer <ATLAS_PROCESSING_OPERATOR_TOKEN>
```

Disabled, missing, malformed, invalid, low-entropy, or provider-token-reused operator credentials collapse to the same generic `404 Not found` behavior as the process-once route.

Authentication happens before fixture reading, checksum calculation, Storage provider construction, Storage writes, Storage reads, or response construction involving Storage metadata.

The route accepts no request body and no query parameters. Body and query inputs are rejected; they are not credential fallbacks and cannot select a file, path, URL, filename, bytes, or StorageReference.

## Storage strategy and idempotency

The route writes through the injected `StorageProvider` abstraction. It does not hard-code local storage and does not parse or expose provider-local paths.

The deterministic opaque reference is derived only from the fixed smoke namespace and accepted fixture SHA-256, then encoded in the existing `StorageReference` format:

```text
src_<first-32-hex-of-sha256("source-transport-smoke/<fixture-sha256>.pdf")>
```

Repeated calls in the same deployment therefore target the same opaque reference.

Behavior:

- first valid request writes the fixture and returns `disposition=retained_or_already_present`;
- repeated valid request with identical retained bytes returns the same reference and the same disposition;
- a different existing object at that reference returns a safe conflict and is not overwritten or deleted.

## Post-write verification

After `StorageProvider.put()`, the route reads the retained object back with `StorageProvider.get()` and verifies that the result is bytes with the retained size and SHA-256. This proves that the object required by the later operator request exists in the configured Storage provider. The route is not transactional: if `put()` succeeds but post-write verification fails, the response is a failure and the object may remain for operator investigation; the route does not delete or claim rollback.

## Safe response and errors

A successful response contains only safe metadata:

- `status=ready`
- fixed fixture ID `test-only-source-transport`
- opaque `storage_reference`
- SHA-256
- byte size
- media type
- truthful disposition `retained_or_already_present`
- safe message

It never returns fixture bytes, local fixture paths, Storage local paths, operator tokens, provider tokens, source transport tokens, source transport URLs, Authorization headers, or provider credentials.

Safe error mappings:

- disabled/auth failure: generic `404 Not found`;
- query/body input: `422` with a generic policy message;
- corrupt/missing fixture or retained-byte mismatch: generic `500`;
- different existing object at deterministic reference: generic `409`;
- provider unavailable/read/write failure: generic `503`;
- unexpected failure: generic `500`.

## Explicit non-goals

This task does not submit an OCR job, create a Transport Grant, construct a source transport URL, call the integration service, invoke the orchestrator, call `paddle-vl-api`, add uploads, accept arbitrary bytes or paths, add database state, add migrations, add queues/workers, call MinerU-Popo, or modify the provider reference.

## H-E prerequisites and next task

Do not authorize M2-003H-E until this route is independently verified, Required Backend CI is green, the disposable deployment contains the runtime fixture, and the operator configuration remains enabled with the independent operator secret.

Recommended next task: **M2-003H-E Run Controlled Live Provider Smoke**.
