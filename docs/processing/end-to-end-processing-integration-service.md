# End-to-End Processing Integration Service

| Field | Value |
|---|---|
| Document Type | Integration Service Design |
| Authority Domain | Integration-service responsibilities and in-process execution boundary |
| Applies To | `app.processing.integration`, retained source descriptors, public-origin validation, temporary transport URL builder, source-transport grants, `ProcessingOrchestrator`, and raw-result ingestion delegation |

Task M2-003H-B adds a narrow in-process coordinator that connects an already-retained source to the existing source-transport grant service and `ProcessingOrchestrator` without adding public routes, persistence, background workers, or live provider calls.

## Package structure

- `app.processing.integration` owns the retained source descriptor, public-origin validation, temporary transport URL builder, integration request/outcome/error models, and `EndToEndProcessingIntegrationService`.
- Existing source transport grants remain in `app.processing.transport`.
- Existing provider submission, polling, and raw-result ingestion remain delegated to `app.processing.orchestration`.

## Configuration

`ATLAS_PUBLIC_SOURCE_TRANSPORT_ORIGIN` maps to `Settings.public_source_transport_origin`. It is optional during application startup and validated only when the integration service is invoked. The value must be an HTTPS origin with a host, no userinfo, no query, no fragment, and no arbitrary path. It is normalized with a trailing slash.

## URL redaction

URL-bearing models use repr-safe fields. Debug representations may show `<redacted>` but must not reveal the temporary source URL or the opaque transport token. Provider serialization still includes the source URL so the provider request payload remains unchanged.

## Source descriptor

`RetainedSourceDescriptor` is an already-resolved value object. It carries the Atlas document ID, source-file ID, `StorageReference`, retained flag, SHA-256 checksum, byte size, media type, optional ETag, and optional filename. The coordinator validates it without querying a database and without calling `Storage.get` merely to prove existence.

## Coordinator sequence

The service performs exactly one in-process attempt:

1. validate the retained source descriptor;
2. create one 20-minute transport grant;
3. receive the plaintext token once;
4. build `/internal/source-transport/{token}` under the trusted public origin;
5. construct an `OrchestrationRequest` using the standard profile and minimal provider options;
6. invoke `ProcessingOrchestrator.run_once` once with a five-minute timeout, 2s initial polling, 10s maximum polling, and 1.5 backoff;
7. apply the terminal grant policy;
8. inspect the final safe grant state;
9. return a typed integration outcome or typed integration error.

## Grant lifecycle

Successful retained raw results, definite provider failures, provider expiry, and ingestion failures after provider completion revoke the grant. Timeout and submission uncertainty do not revoke immediately; the process-local grant remains active and expiry-managed when the in-memory registry is still available. Revocation failures, including process-local registry loss after restart, preserve the primary outcome and attach a safe cleanup warning without automatic resubmission.

## Outcomes and errors

`ProcessingIntegrationOutcome` includes Atlas identities, provider job/request IDs, terminal phase/status, retained raw-result envelope and storage reference, raw-result checksum and size, elapsed time, poll count, safe warnings, grant ID, final grant state, and revocation status. It excludes plaintext tokens, full transport URLs, bearer tokens, local paths, source bytes, and artifact bytes.

`IntegrationError` categories distinguish invalid retained source, invalid public origin, grant creation failure, URL construction failure, orchestration failure, submission uncertainty, timeout, cleanup warning, and unexpected integration failure. Structured orchestration errors are preserved rather than flattened into unsafe strings.

## Security

The URL builder is provider-independent, uses no business IDs, emits no logs, persists nothing, and never infers origin from request Host headers. Tokens and full URLs are excluded from repr and safe errors.

## Non-goals

This task does not add live provider access, database lookup, route integration, upload integration, ProcessingAttempt persistence, MinerU-Popo calls, structured processing output, Reader output, object storage, or background workers.

## Next task

Recommended next task: **M2-003H-C Independently Verify End-to-End Integration Service**.
