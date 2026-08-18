# Private Source Transport Endpoint

| Field | Value |
|---|---|
| Document Type | Private Endpoint Design |
| Authority Domain | Private provider-only source-byte delivery endpoint and bounded in-memory transport-grant access control |
| Applies To | `GET /internal/source-transport/{token}`, opaque path-token authorization, in-memory grant validation, lazy Storage lookup, byte verification, PDF response headers, collapsed error responses, retrieval accounting, and disposable Local/HF test deployment limits |
| Implementation Status | Endpoint implemented as a temporary M2 bridge for disposable Local/HF test deployment, not the final production source transport architecture |
| Security Boundary | Token is the only route credential; unauthorized states collapse to `404 Not Found`; the route is excluded from OpenAPI schema generation and adds no token-bearing application logs or metrics |
| Transport Boundary | Provider-only PDF byte delivery through Storage.get after grant authorization; no public downloads, redirects, range handling, streaming, transforms, source deletion, or grant-creation endpoint |

## Purpose

M2-003G adds the first disposable, provider-only byte-delivery boundary for the
Local/HF test deployment:

```text
GET /internal/source-transport/{token}
  -> authorize in-memory transport grant
  -> lazily resolve Storage provider
  -> Storage.get(storage_reference)
  -> verify actual size and SHA-256
  -> return PDF bytes
  -> record retrieval completion
```

This endpoint is a temporary M2 bridge. It is not the final production source
transport architecture.

## Route and credential model

`GET /internal/source-transport/{token}` accepts one opaque path token. The token
is the only route credential. The path does not include `StorageReference`,
Document ID, SourceFile ID, filenames, local filesystem paths, or arbitrary URLs.

Malformed, unknown, expired, revoked, exhausted, and otherwise unauthorized
tokens all return the same external response: `404 Not Found` with the body
`{"detail":"Not found"}`. The route does not expose grant IDs, expiry,
retrieval limits, storage references, filenames, or token material.

Only GET is implemented for byte delivery. HEAD is explicitly rejected with
`405 Method Not Allowed` so credential probes cannot consume retrieval counts.
FastAPI may answer framework-level OPTIONS requests through application
middleware, but this task adds no POST, PUT, DELETE, list, inspection,
revocation, or grant-creation endpoint. The router is excluded from OpenAPI
schema generation with `include_in_schema=False` to reduce accidental discovery
of the internal credential-bearing path.

## Dependency wiring

The router depends on explicit FastAPI dependencies for:

- `InMemoryTransportGrantService` from
  `app.processing.transport.dependencies.get_transport_grant_service`; and
- a lazy `StorageProvider` factory from
  `app.processing.transport.dependencies.get_storage_provider_factory`.

The grant dependency returns one process-local registry instance for the
application lifetime, so grants are shared across requests in one process and
can be overridden in tests. The Storage dependency is intentionally lazy: FastAPI
resolves only a callable before entering the route, and the route invokes that
callable only after successful initial grant authorization. Invalid credentials
therefore do not initialize or access Storage. Neither dependency performs
import-time network access. Multiple app workers still have separate registries,
and process restart loses all grants.

The router does not instantiate `LocalStorageProvider`, parse local paths, call
Storage `exists()`, delete source bytes, or access grant-service internals.

## Storage retrieval and byte verification

After authorization, the endpoint resolves the Storage provider and then
retrieves bytes with `StorageProvider.get(grant.storage_reference)`. The returned
payload must be `bytes`. The endpoint verifies the actual byte length against
`grant.source_byte_size` and computes SHA-256 over the actual bytes, comparing it
with `grant.source_sha256` using a safe digest comparison. Mismatched or
non-bytes payloads are not returned and do not increment retrieval accounting.

Storage object-not-found and invalid-reference failures map to the same generic
`404 Not Found` response. Storage read/provider availability failures map to a
generic `503 Service Unavailable`; integrity and unexpected failures map to a
generic `500 Internal Server Error`. None of these responses include storage
paths, references, token values, checksums, or grant metadata.

## Media type and response headers

Initial M2 scope is PDF only. The endpoint accepts `application/pdf`, including
case-insensitive values with media-type parameters after normalization, and
rejects unsupported media types generically.

Successful responses return the exact source bytes with:

- `Content-Type: application/pdf`
- `Content-Length: <actual bytes>`
- `Cache-Control: private, no-store`
- `Pragma: no-cache`
- `X-Content-Type-Options: nosniff`

The response does not include `Content-Disposition`, original filename,
StorageReference, Document ID, SourceFile ID, grant ID, provider job ID, source
URL, token, redirects, range handling, streaming, compression, or transforms.

## Retrieval accounting, re-check, and concurrency

Accounting means Atlas successfully prepared the full buffered response and
handed it to the ASGI response layer. It does not prove that the remote provider
received every byte.

The route sequence is:

1. authorize token;
2. lazily resolve Storage provider;
3. retrieve bytes from Storage;
4. verify size and SHA-256;
5. authorize again to catch revocation/expiry during retrieval;
6. build the complete buffered `Response`;
7. call `record_retrieval(token)` before returning it; and
8. return bytes only if the record step succeeds.

Authorization alone, missing source, unsupported media type, non-bytes payload,
size mismatch, checksum mismatch, storage failure, and re-check failure do not
increment retrieval count. Because `record_retrieval` authorizes and increments
under the grant-service lock, concurrent requests racing a one-retrieval limit
can both fetch bytes, but only one records and returns success; the loser fails
closed with the collapsed `404 Not Found` response. There remains a small race
after the final authorization/accounting step and before response delivery; M2
has no lease protocol and does not claim atomic end-to-end provider receipt.

## Memory, logging, and deployment limits

This implementation buffers the full object in memory. The grant service's
policy snapshot remains the authoritative source-size limit for this test
posture (currently 100 MB by default), and the route adds no second hard-coded
size limit. Production streaming or presigned durable object-storage URLs remain
future work.

The route adds no token-bearing application logs or metrics. Framework or
reverse-proxy access logs may include the request path, so deployments must
redact `/internal/source-transport/*` paths and treat transport URLs as secrets.

## Explicit non-goals

This task does not add orchestration integration, grant creation APIs, public
user downloads, database persistence, migrations, object storage, presigned URLs,
streaming Storage APIs, range requests, provider upload endpoints, callbacks,
live provider calls, source deletion, upload behavior changes, OCR route changes,
or Reader behavior changes.

## Next task

Recommended next task: M2-003H Integrate Source Transport with Non-Persistent
Orchestration and Run Manual Live Provider Smoke, after M2-003G is independently
verified.
