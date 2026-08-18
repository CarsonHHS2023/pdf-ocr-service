# Source Transport Grant Service

| Field | Value |
|---|---|
| Document Type | Grant Service Design |
| Authority Domain | Short-lived source-transport grant creation, validation, retrieval accounting, expiry, revocation, inspection, and cleanup boundaries |
| Applies To | `app/processing/transport/models.py`, `service.py`, `errors.py`, grant records, opaque tokens, source descriptors, TTL, authorization, retrieval accounting, revocation, process-local in-memory state, cleanup, and future endpoint integration |
| Implementation Status | Provider-independent in-memory transport grant domain implemented with no HTTPS route, Storage access, orchestration integration, persistence, or provider client behavior changes |
| Security Boundary | Transport grants are URL-path-safe bearer credentials for retained-source transport; plaintext tokens, token digests, local paths, full transport URLs, source bytes, request headers, and authorization headers must not be logged or exposed |

## Purpose

M2-003F introduces a provider-independent, in-memory transport grant domain for
future provider-reachable source download endpoints. It models how Atlas can
issue a short-lived credential for one retained `StorageReference` without
exposing source bytes, local storage paths, signed URLs, or provider-specific
OCR options.

The package is intentionally narrow:

- `app/processing/transport/models.py` defines safe grant descriptors, policy,
  lifecycle state, creation results, authorized descriptors, and stored records.
- `app/processing/transport/service.py` owns the process-local registry,
  cryptographic token generation, digest lookup, authorization, retrieval
  accounting, revocation, inspection, and cleanup.
- `app/processing/transport/errors.py` defines typed log-safe errors.

## Accepted M2 test decisions

- The initial transport is Atlas-controlled and provider-only HTTPS, but this
  task does **not** create the HTTPS route.
- Grant tokens are opaque, high-entropy, URL-path-safe bearer credentials.
- Grants may be replayed until expiry, revocation, or an optional retrieval
  limit; strict one-time-use behavior is not implemented.
- State is in process memory only and is acceptable only for disposable test
  deployments.
- Production transport can later switch to durable object storage or presigned
  URLs behind the same provider-independent boundary.

## Grant identity and metadata

A transport grant identity is distinct from the `StorageReference`, Atlas
processing attempt ID, provider job ID, document ID, and source-file ID. Stored
records retain those identifiers for authorization context and diagnostics, but
none of them are embedded in the token.

The grant stores source provenance needed by a future endpoint: SHA-256, byte
size, media type, optional ETag, and optional filename as provenance metadata.
The filename is not part of token or URL identity.

Safe metadata is defensively copied and frozen on creation. The service rejects
metadata keys that exactly normalize to sensitive names such as tokens, secrets,
authorization headers, bearer credentials, signed/source/download URLs, local
paths, cookies, query strings, credentials, API keys, or `x-amz-signature`; it
does not scan arbitrary metadata values and allows non-secret count keys such as
`token_count` or `path_count`.

## Token handling and digest storage

The service generates tokens with `secrets.token_urlsafe(32)`, providing 256 bits
of randomness before URL-safe encoding. The registry stores only a SHA-256 digest
of the random token. Because the plaintext token is generated from sufficient
cryptographic entropy and is not derived from business identifiers, offline
guessing of a digest is infeasible for this test transport posture.

The plaintext token is returned only in `TransportGrantCreationResult`. The
creation result redacts the token from `repr`, and stored records, safe
descriptors, authorized descriptors, and typed errors do not expose the plaintext
token or token digest.

## Lifecycle and TTL

Grant state is derived from record fields and an injected UTC clock:

- `active` when the grant is usable;
- `expired` when `now >= expires_at`;
- `revoked` after explicit revocation;
- `exhausted` when an optional retrieval limit has been reached.

State precedence is `revoked` first, then `expired`, then `exhausted`, then
`active`. Revoked records are eligible for explicit cleanup immediately, and
expired records are unusable even before cleanup removes them. The default TTL is
20 minutes, with a one-hour maximum TTL guard. Callers can supply a shorter
positive finite TTL. Expiry is derived once from creation time, uses timezone-
aware UTC datetimes, and affects only transport authorization; it never deletes
the retained source. A caller-supplied test clock that returns naive datetimes is
rejected. If a test clock moves backward, state is recomputed against that clock;
production callers should provide a monotonic-enough UTC wall clock.

## Replay and retrieval accounting

Replay is allowed by default. `authorize(token)` checks that a token maps to an
active grant and returns a safe authorized descriptor without changing retrieval
counters. Unknown, expired, revoked, and exhausted credentials use distinct
internal errors, but the future route layer can collapse them to a generic
unauthorized/not-found response.

`record_retrieval(token)` atomically authorizes and records one successful
retrieval completion. The first successful completion sets `first_retrieved_at`,
every completion updates `last_retrieved_at`, and `retrieval_count` increments
without automatically revoking the grant. Future endpoint code should call this
after successful byte delivery so failed or partial deliveries do not count as
successful retrievals. No begin/complete lease protocol is implemented in this
first version. Future endpoint code must also decide where to re-check grant
state around byte delivery; an authorized descriptor is a snapshot and revocation
after authorization invalidates subsequent authorizations, not the already
returned Python value.

## Revocation, expiry, and cleanup

Revocation is explicit by safe grant ID, idempotent, records `revoked_at` once,
and requires no plaintext token. A revoked token no longer authorizes retrieval.
Unknown grant revocation returns no descriptor and does not expose token state.

Expiry requires no background worker for correctness. Authorization checks the
injected clock every time. `cleanup_expired(limit=...)` is a bounded, explicit
operation that removes expired and immediately-revoked registry records from
memory only. Cleanup order follows the process-local dictionary iteration order
and is not a cross-process contract. It never returns tokens or digests, never
calls Storage, and never deletes retained source bytes.

## Concurrency

The in-memory registry uses a process-local re-entrant lock around create,
lookup, revocation, retrieval accounting, inspection, and cleanup. This prevents
lost retrieval-count updates and keeps revocation/authorization atomic within
one Python process.

This is not multi-process durability. Process restarts, Hugging Face rebuilds,
and container replacement lose all grants. Each worker or replica has its own
registry; multiple workers/replicas cannot share grants, and there is no audit
durability or high availability. Sticky routing plus shared persistent transport
state, or a presigned durable object-storage transport, would be required before
relying on this approach outside the accepted disposable test deployment.

## Security and redaction

The service deliberately avoids logging. Safe fields for future logs are grant
ID, processing attempt ID, provider job ID, lifecycle state, retrieval count,
timestamps, byte size, media type, and operation outcome.

Never log or expose plaintext tokens, token digests, local storage paths, future
full transport URLs, source bytes, request headers, or authorization headers.

## No Storage access and no route

This task does not instantiate the service in application startup, dependency
injection, routers, orchestration, provider clients, upload flow, OCR flow, or
Reader flow. It does not call `Storage.get()`, `Storage.put()`, path parsing,
object existence checks, SourceFile mutation, or source deletion.

## Explicit non-goals

M2-003F does not add HTTP routes, source byte streaming, presigned URLs,
object-storage providers, database tables, Alembic migrations, audit
persistence, authentication middleware, background cleanup workers, provider URL
construction, orchestration integration, or provider client behavior changes.

## Next task

The recommended next task is **M2-003G Implement Private Source Transport
Endpoint**. Do not authorize M2-003G until this grant service is independently
verified.
