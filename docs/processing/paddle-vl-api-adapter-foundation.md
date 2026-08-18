# paddle-vl-api Adapter Foundation

| Field | Value |
|---|---|
| Document Type | Provider Adapter Foundation |
| Authority Domain | Paddle-VL provider-adapter responsibilities and provider protocol isolation boundary |
| Applies To | `app/processing/errors.py`, `models.py`, `provider.py`, `paddle_vl/models.py`, `paddle_vl/client.py`, `paddle_vl/mapping.py`, request submission, status polling, result retrieval, artifact handling, error mapping, transport inputs, and Paddle-VL-specific models |
| Implementation Status | Adapter foundation implemented without production route integration, orchestration, persistence, storage ingestion, or production provider calls |
| Security Boundary | Authenticated provider calls disable redirects; safe logs and errors exclude tokens, full signed source URLs, raw results, and artifact bytes |

M2-003B adds a narrow Atlas provider-adapter foundation for the verified `paddle-vl-api` async job protocol. It does not change any production route, upload behavior, local OCR pipeline, database model, migration, Reader serialization, or MinerU-Popo transformation.

## Scope and package structure

Production code lives under `app/processing/`:

- `errors.py` defines provider-independent safe error categories and details.
- `models.py` defines narrow typed Atlas boundary models and the provider protocol.
- `provider.py` exports the minimal provider protocol.
- `paddle_vl/models.py` serializes one-document `/ocr/jobs` requests.
- `paddle_vl/client.py` implements the async HTTP client operations.
- `paddle_vl/mapping.py` maps statuses, progress, and page identity metadata.

This is intentionally not a plugin registry or multi-provider marketplace.

## Configuration

`app.config.Settings` now includes optional `paddle_vl_api_base_url`, optional `paddle_vl_api_bearer_token`, `paddle_vl_api_timeout_seconds`, and `paddle_vl_api_default_result_profile`. The adapter still requires explicit `PaddleVLClientConfig` construction before use. Importing the package does not create a network client or call the network.

No production URL or token is hard-coded. Token values are redacted from configuration representation and error strings.

## Stable endpoints

The adapter implements only the stable async control-plane endpoints:

- `POST /ocr/jobs`
- `GET /ocr/jobs/{job_id}`
- `GET /ocr/jobs/{job_id}/result`, with caller-selected result profile
- `GET /ocr/jobs/{job_id}/artifact`

It does not implement spike endpoints, `/ocr/sync`, `/warmup`, polling loops, orchestration, persistence, storage ingestion, or production route integration.

## Typed models

The Atlas-facing boundary returns typed models for accepted submissions, job status, provider progress, provider result metadata, artifact bytes plus metadata, error details, and processing page identity. Raw provider JSON is preserved only as adapter-specific payload on paddle-vl results/statuses for forward compatibility; it is not the generic M2 contract.

## Status and progress mapping

Provider statuses map as follows:

| Provider | Atlas provider lifecycle |
| --- | --- |
| `queued` | `queued` |
| `running` | `running` |
| `completed` | `provider_completed` |
| `partial_failed` | `provider_partial_failed` |
| `failed` | `failed` |
| `expired` | `expired` |

`completed` intentionally means provider execution completed. It is not mapped to final Atlas ingestion or normalization success. Provider progress preserves provider counters and marks 100% as provider-only completion.

## Error mapping

The adapter maps provider HTTP and structured error bodies into safe provider-independent categories: configuration, authentication, validation/request, duplicate job conflict, unavailable, timeout, job not found, result not ready, result expired, artifact missing/expired, provider execution failure, malformed response, and unexpected provider error.

Errors preserve HTTP status, provider code, safe message, retryability, and IDs where available. They do not include bearer tokens, authorization headers, raw unsafe response bodies, or source URLs.

## Page mapping

Pure helpers validate provider page identity metadata:

- one-based `page_number`
- zero-based original `page_index`
- zero-based `local_page_index`
- one-based inclusive `source_page_range`
- duplicate pages
- missing pages
- local range consistency
- stable sorted output

Invalid mappings raise a typed malformed-provider-response error and are not silently repaired.

## Artifact handling

Artifact download always uses the configured provider origin and the stable `/ocr/jobs/{job_id}/artifact` endpoint. The adapter ignores arbitrary external artifact URLs from result payloads, verifies SHA-256 when metadata or response headers supply it, detects size mismatch when practical, returns bytes plus metadata, and does not persist, decompress, transform, or expose temporary provider URLs to application code.

## Security boundaries

Authenticated calls disable automatic redirects so credentials are not forwarded to another origin. Safe logs/errors may include provider name, job ID, request ID, endpoint category, HTTP status, provider status, and elapsed time, but must not include tokens, full signed source URLs, raw results, or artifact bytes.

## Fixture-based testing

Focused tests use committed fixtures under `tests/fixtures/providers/paddle_vl_api/` and `httpx.MockTransport`. They make no live provider calls and require no Paddle, Modal, GPU, or external service.

## Explicit non-goals

This PR does not implement ProcessingRun or Observation tables, Alembic migrations, raw result persistence, MinerU-Popo transformation, structured processing output, Reader changes, existing route cutover, production provider calls, a polling coordinator, or CI live provider calls.

## Next step

A follow-up task should introduce orchestration/persistence around Atlas processing attempts and decide how provider-completed results flow into the Atlas transformation boundary before MinerU-Popo and structured output.
