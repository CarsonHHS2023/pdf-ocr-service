# Provider-Reachable Source Transport

| Field | Value |
|---|---|
| Document Type | Provider-Reachable Transport Design |
| Approval Status | Proposed |
| Authority Domain | Construction and delivery of temporary provider-reachable source transport references without exposing Storage internals or source identity as transport credentials |
| Applies To | Retained source bytes behind opaque `StorageReference`, public HTTPS origin requirements, private endpoint option, transport grants, transport URLs, provider fetch behavior, Local/HF deployment limitations, revocation, cleanup, and Storage boundary relationships |
| Implementation Status | Proposed architecture; implementation not authorized |
| Transport Boundary | Temporary provider-reachable source transport is separate from durable source identity and Storage ownership; no production durability is claimed for the current HF test posture |
| Security Boundary | Transport URLs are temporary credentials that must not be retained in downstream results, Reader data, logs, or application APIs |

## Status

State: Proposed architecture; implementation not authorized.

- Atlas commit inspected: `ce43a022e3b3774852b9a7b2a271b64dc2435de5`.
- Provider reference commit inspected: `3a790e3e4c0ececef316bd2ca5aa03d84f6c6159`.
- Provider implementation revision recorded by the inventory: `20b9ec9`.
- Review date: 2026-07-15.
- Current deployment limitations: the Atlas Hugging Face test deployment uses
  Local Storage and SQLite on an ephemeral filesystem with no configured
  Persistent Storage; the remote `paddle-vl-api` deployment accepts HTTPS PDF
  URLs for async jobs and runs in a separate provider environment.
- `paddle-vl-api` was inspected as read-only evidence. No file under
  `/workspace/paddle-vl-api-reference` was edited.

This document is architecture and security design only. It does not authorize an
implementation, route, signed URL, upload endpoint, object-storage provider,
schema, migration, Storage Adapter change, orchestration change, or provider
change.

## Objective

Atlas now has retained original source bytes referenced by an opaque
`StorageReference`. The remote processing provider currently accepts an HTTPS
PDF URL as async job input. The configured Local Storage provider stores bytes
behind Atlas and derives local filesystem paths internally; those paths are not
provider-reachable and must not become provider contracts.

The required boundary is therefore:

```text
Atlas opaque StorageReference
    ↓
secure, temporary, provider-reachable source transport
    ↓
paddle-vl-api HTTPS PDF input
```

The boundary must make one retained source object temporarily reachable to an
authorized provider without exposing Storage internals, local paths, durable
business identifiers, or Source identity as transport credentials.

## Current state

### Verified current implementation

- `SourceFile` identifies source provenance for a `Document`, including
  filename, type, MIME type, byte size, checksum, storage reference, retained
  flag, and primary-source flag.
- Uploads retain original source bytes through the injected Atlas Storage
  provider before TXT/PDF processing continues.
- The only configured Storage provider is Local Storage. It uses opaque
  `src_<uuidhex>` references and internally maps them to sharded filesystem
  paths beneath `storage_root`.
- `StorageReference` is opaque. Application and provider code are not supposed
  to parse it as a local path or URL.
- Current Hugging Face test storage is ephemeral. Local Storage objects,
  SQLite, and any future in-process transport grant state can be lost when the
  container is rebuilt.
- The remote provider async protocol accepts `documents[].pdf_source_url` and
  requires HTTPS. It can also receive optional `pdf_source_sha256` and
  `pdf_source_etag`.
- The provider downloads the PDF, enforces byte/time limits, verifies the
  optional source SHA-256, checks PDF magic bytes, splits the PDF into temporary
  page ranges, and uses an execution cache for downloaded source/range files.
- Atlas non-persistent orchestration currently requires an already-approved,
  provider-reachable HTTPS `source_url` plus source checksum and media type.
- No Atlas source-transport service currently exists.
- No production source-download API exists.
- No presigned object-storage URL capability exists.
- No provider upload/bytes endpoint exists for async jobs.

### Proposed architecture separation

The current implementation above is factual context only. The remainder of this
document proposes a transport boundary that requires human confirmation before
implementation. Proposed terms such as grant, transport URL, transport object,
and lifecycle state are conceptual and do not imply new Python classes, database
fields, tables, migrations, or routes in this task.

## Terminology

### Source identity

The Atlas business/evidence identity represented by `Document`, `SourceFile`,
and the opaque `StorageReference`. Source identity is durable Atlas state and is
not a URL, token, local path, or provider-specific handle.

### Source transport

A temporary mechanism by which an authorized provider retrieves the retained
source bytes needed for a processing job. Source transport is operational and
credential-like; it does not redefine the Source.

### Transport grant

A time-limited authorization allowing retrieval of one retained source object for
one processing attempt or provider job.

### Transport URL

An HTTPS URL associated with a transport grant. It is a temporary transport
credential and must be treated as secret until it expires or is revoked.

### Transport object

A temporary provider-reachable copy or projection of retained source bytes, if
the selected implementation requires one. A transport object is not the retained
Source and must have independent cleanup semantics.

### Provider retrieval

The provider's download of bytes using the temporary transport.

## Core architectural rules

| Rule | Evaluation |
|---|---|
| 1. `StorageReference` is never sent to the provider as a URL/path. | Required to preserve Storage opacity and migration freedom. |
| 2. Local filesystem paths are never exposed. | Required because local paths are not cross-deployment contracts and can leak internals. |
| 3. Transport URLs are temporary credentials. | Required; access depends on TTL/revocation and secrecy. |
| 4. Transport URLs are not source identity. | Required; `Document`, `SourceFile`, `StorageReference`, and checksum remain identity/provenance. |
| 5. Transport URLs must not be retained in Raw Processing Result envelopes, Structured Processing Output, M3 content, Reader data, logs, or application APIs. | Required to prevent credential persistence and downstream leakage. |
| 6. Source checksum remains the stable integrity identity. | Required for provider and Atlas verification across transport mechanisms. |
| 7. Provider download bytes must be verified against the expected source SHA-256. | Required; current provider supports optional `pdf_source_sha256`. |
| 8. Transport expiry must not delete the retained original Source. | Required; grant lifecycle is separate from source retention. |
| 9. Transport cleanup must not be delegated to generic source cleanup. | Required; transport objects/grants have their own lifecycle. |
| 10. Business/processing orchestration authorizes transport; Storage or transport infrastructure executes byte delivery. | Required to keep policy separate from byte mechanics. |
| 11. Applications do not generate provider transport directly. | Required; Reader/upload APIs must not mint provider credentials. |
| 12. Transport failure is distinct from source loss and provider OCR failure. | Required for safe retry, diagnostics, and future attempt state. |

## Requirements

| Requirement | Classification | Notes |
|---|---|---|
| One retained source object | Required for first implementation | M2 remains one Atlas `Document` / `SourceFile` per provider job. |
| One processing attempt/provider job | Required for first implementation | Grant scope should not span unrelated jobs. |
| HTTPS | Required for first implementation | Matches provider protocol and prevents cleartext credentials. |
| Short lifetime | Required for first implementation | Exact TTL requires human approval. |
| Unguessable authorization | Required for first implementation | Use high-entropy grant IDs/tokens or equivalent signatures. |
| Exact source byte delivery | Required for first implementation | No rendering, conversion, or recompression. |
| Content length where available | Required for first implementation | Helps provider limits and observability; streaming may make it unavailable in rare cases. |
| PDF media type | Required for first implementation | The provider expects PDFs; use `application/pdf` for source transport. |
| Source checksum verification | Required for first implementation | Provider must receive/verify expected SHA-256; Atlas may also verify before issuing. |
| No directory listing | Required for first implementation | Transport URL must address only an authorized object. |
| No arbitrary `StorageReference` access | Required for first implementation | Grant must bind to one authorized retained source. |
| No cross-source access | Required for first implementation | Token for Source A cannot retrieve Source B. |
| No local path exposure | Required for first implementation | Applies to URLs, headers, logs, errors, and provider payloads. |
| Safe expiration | Required for first implementation | Expiry denies retrieval without deleting retained source bytes. |
| Replay policy | Required for first implementation | Must be compatible with provider retries; exact policy needs confirmation. |
| Revocation policy | Required for first implementation | Revocation timing requires confirmation. |
| Provider-compatible redirects or no redirects | Required for first implementation | Provider permits HTTPS redirects but Atlas should prefer no redirects initially. |
| Bounded download time | Required for first implementation | Provider already has a download timeout; Atlas should also bound serving time later. |
| Observability without credential logging | Required for first implementation | Metrics/events must redact tokens and full URLs. |
| Testability without live provider access | Required for first implementation | Unit/integration tests can use mocked provider/download clients. |
| Persistent/auditable grants | Required before production | First test version may be in-memory; production likely needs auditability. |
| Private-network SSRF/allowlist hardening | Required before production | Current provider only enforces HTTPS and limits; origin restrictions need owner decision. |
| Durable source storage | Required before production | Real user data requires persistent source storage, not ephemeral HF storage. |
| Streaming/open Storage support | Optional/deferred | Needed for large PDFs; current Storage `get()` returns bytes. |
| Range request support | Optional/deferred | Useful for some clients, not proven required by current provider. |
| Transport object store | Optional/deferred | Only needed if selected option uses copied/projection objects. |

## Option analysis

### Option A — Atlas authenticated short-lived download endpoint

```text
StorageReference
    ↓
Atlas transport grant
    ↓
short-lived HTTPS endpoint
    ↓
provider downloads exact source bytes
```

This option creates an Atlas-controlled, provider-only HTTPS endpoint that
streams or returns the retained source bytes for a valid transport grant.

- Compatibility with current Local Storage: strongest current fit because Atlas
  can retrieve bytes with `Storage.get()` without exposing the local path.
- Compatibility with current HF test deployment: feasible for disposable testing
  if the HF app is publicly reachable by the provider and the source object plus
  grant survive long enough.
- Deployment reachability: requires the provider to reach the Atlas deployment
  over HTTPS; local developer machines would need a safe tunnel or mocked tests.
- Authentication mechanism: high-entropy grant token or signed grant; exact
  placement requires human decision.
- Token placement: URL path/query is most compatible with a provider that only
  accepts URLs; bearer header is safer in logs but requires provider support for
  custom source-download headers.
- URL leakage risk: high if full URLs are logged, stored in provider internal
  state, browser history, analytics, exceptions, or Raw Results; redaction is
  mandatory.
- Restart behavior: in-memory grants die on restart; production should persist
  grant metadata or use stateless verifiable signatures with revocation tradeoffs.
- Horizontal scaling: in-memory grants require sticky routing or shared state;
  persisted grants or signed URLs scale better.
- Byte streaming: current Storage returns bytes, so first version may buffer the
  full PDF; true streaming requires separate Storage design.
- Range support: optional unless provider or large-file behavior requires it.
- Checksum headers: can expose safe checksum headers, but provider verification
  should use request `pdf_source_sha256` as the stable mechanism.
- TTL: short and configurable; must cover provider retrieval, not full OCR.
- Revocation: straightforward with server-side grant state; harder with purely
  stateless signatures.
- Database/state needs: none for a disposable test if in-memory is accepted;
  production likely needs persistent/auditable grant records.
- Server load: Atlas proxies all provider download bytes and may become a
  bottleneck for large PDFs or concurrent jobs.
- Production readiness: useful as initial M2/test bridge, but should not be
  assumed to be permanent production architecture if object storage can serve
  bytes directly.

This is not a public user download endpoint. It would be provider transport
only.

### Option B — Presigned durable object-storage URL

```text
Atlas Storage object
    ↓
object-storage presigned URL
    ↓
provider downloads directly
```

- Future S3/R2/Azure compatibility: strong; all can issue temporary object URLs
  or equivalent signed access.
- Provider independence: strong if the orchestration boundary only needs HTTPS
  URL, expiry, checksum, media type, and optional headers.
- URL expiry: native and scalable in object stores, but revocation before expiry
  depends on provider and bucket policy mechanics.
- Checksum/integrity: provider still verifies `pdf_source_sha256`; object-store
  ETag alone is not sufficient for all multipart/encrypted cases.
- No Atlas byte proxy: improves scalability and reduces application load.
- Production scalability: likely strongest for real workloads.
- Provider/client support: compatible with current provider if a single HTTPS URL
  is sufficient and no custom headers are needed.
- Current Local provider incompatibility: Local Storage cannot produce a
  provider-reachable presigned URL today.
- Development/test complexity: requires durable object-storage infrastructure,
  credentials, networking, lifecycle policy, and secure configuration.
- Storage Adapter changes: likely requires provider-specific signing mechanics
  behind a provider-independent transport boundary, not direct orchestration
  dependency on S3/R2/Azure APIs.
- Credential/security posture: signing credentials must be tightly scoped and
  never logged; bucket policy must prevent listing and cross-object access.

### Option C — Provider upload/bytes endpoint

```text
Atlas Storage.get()
    ↓
Atlas uploads bytes to provider
    ↓
provider creates execution input
```

- Existing provider protocol gap: async jobs do not currently accept uploaded
  bytes; only sync `/ocr/sync` accepts multipart and it is not the async job
  protocol Atlas orchestration targets.
- Large PDF memory/streaming: Atlas and provider would need streaming multipart
  or chunked upload semantics to avoid buffering.
- Retry/idempotency: uploads need idempotent request IDs, duplicate handling,
  partial upload cleanup, and uncertain-submission recovery.
- Source checksum: provider should still verify uploaded bytes against expected
  SHA-256.
- Provider-side retention: provider must define how long uploaded execution
  inputs remain and how they are cleaned.
- Duplicated transfer: Atlas uploads bytes into provider storage; provider may
  still copy/split them internally.
- Async job submission relationship: upload could become a separate create-input
  step before job submission or a combined submission/upload endpoint.
- Provider changes required: significant.
- Coupling: stronger Atlas/provider coupling than a generic HTTPS URL contract.
- Security: avoids URL exposure but adds provider-side upload auth, quotas, and
  input retention risks.
- Production scalability: possible, but less provider-independent and not
  supported by current provider inventory.

### Option D — Temporary transport object in a separate transport store

```text
retained Source
    ↓
temporary provider-reachable transport object
    ↓
short-lived URL
    ↓
provider
    ↓
transport object cleanup
```

- Separation from durable Source storage: strong if transport objects are
  clearly temporary and never become Source identity.
- Ownership: transport service owns the copy/projection; Storage remains owner
  of retained source bytes.
- Copying cost: extra write and storage cost for every processing attempt.
- TTL: can be short and independent of source retention.
- Cleanup: requires lifecycle worker or object-store expiration and orphan
  monitoring.
- Orphan risk: higher than direct URLs; failed submissions can leave transport
  copies until TTL cleanup.
- Infrastructure: needs provider-reachable storage distinct from current Local
  Storage or an Atlas route serving the temporary store.
- Object-store compatibility: good when the temporary store is object storage.
- Local/test implementation: possible only with a reachable Atlas endpoint or
  local-compatible temporary object store.
- Relation to Option B: duplicates many presigned URL mechanics, but uses a
  temporary copy instead of the durable source object. It may be useful when
  durable storage is private or unsuitable for direct provider access.

### Option E — Direct shared filesystem mount

Directly sharing the Local Storage filesystem with the remote Modal provider is
not a valid current transport contract.

- Deployment coupling: requires Atlas and provider to share infrastructure and
  mount semantics.
- Lack of cross-platform reachability: a local HF path is not reachable from the
  remote provider environment.
- Local path leakage: it would expose provider-specific Storage mechanics and
  violate `StorageReference` opacity.
- Provider-specific infrastructure: ties Atlas to one deployment topology.
- Production portability: poor for object storage, multi-region deployments,
  local development, and third-party providers.
- A local path is not a transport contract: it is an implementation detail of
  one Storage provider and cannot express temporary authorization, TTL,
  revocation, HTTPS delivery, or checksum verification.

## Decision matrix

| Option | Current Local/HF test feasibility | Production scalability | Security | Provider changes required | Atlas changes required | Infrastructure dependency | Streaming suitability | TTL/revocation | Failure isolation | Recommendation |
|---|---|---|---|---|---|---|---|---|---|---|
| A — Atlas short-lived endpoint | Medium/high if Atlas is HTTPS-reachable; restart losses acceptable only for test | Medium; Atlas proxies bytes | Good with strong tokens/redaction; URL leakage risk | None for URL-only provider | Route/service/grants later | Public HTTPS Atlas deployment | Limited initially by `Storage.get()` bytes buffering | Strong with server state | Good if categorized separately | Best initial M2/test candidate, human confirmation required |
| B — Presigned object-storage URL | Low today with Local Storage | High | Strong with scoped signing; revocation nuances | None if provider accepts URL | Transport abstraction and storage signing later | Durable object storage | Strong; provider downloads direct | Native expiry; revocation varies | Good; Atlas not byte path | Preferred production direction to evaluate, not selected yet |
| C — Provider upload/bytes | Low; provider async gap | Medium | Avoids URL leakage; adds upload/input retention risks | Yes | Upload workflow/client changes | Provider-side input storage | Good only if streaming upload implemented | Provider-defined | Provider coupling increases | Defer/reject for current M2 |
| D — Temporary transport store | Medium if backed by Atlas endpoint; low without reachable store | Medium/high with object store | Good if isolated; orphan/copy risks | None if URL-based | Copy/grant/cleanup service | Temporary reachable store | Strong with object store; limited if Atlas-buffered | Good with TTL store plus grants | Good if source and transport lifecycles separate | Consider later or as object-store variant |
| E — Shared filesystem | Low for remote Modal provider | Low | Poor; path leakage/coupling | Likely yes/deployment-specific | Unsafe path exposure | Shared mount | Variable | Weak | Poor; source/transport blur | Reject as transport contract |

## Recommended direction

Codex Recommendation — Human Confirmation Required.

### Initial M2/test direction

Use an Atlas-controlled, short-lived, provider-only HTTPS transport endpoint
backed by current Storage. This is the smallest bridge from current Local
Storage to the provider's HTTPS URL protocol without exposing local paths or
changing provider behavior.

This recommendation is not accepted automatically. It requires human approval of
token placement, TTL, replay policy, revocation timing, grant persistence, size
limits, and whether the HF deployment is reachable/safe enough for disposable
smoke tests.

### Production direction

Define a provider-independent transport-grant abstraction that can later issue
presigned durable object-storage URLs without changing orchestration contracts.
Production should prefer direct object-storage delivery if it proves more
secure, scalable, and operationally simple than proxying bytes through the Atlas
application.

The Atlas application endpoint must not be treated as the permanent production
architecture merely because it is the likely initial M2/test bridge.

## Provider-independent transport boundary

Orchestration should depend on a conceptual transport result containing only the
information needed to submit a provider job and reconcile the grant:

- provider-reachable HTTPS URL;
- expiry time;
- source checksum;
- media type;
- optional content length;
- transport/grant identity;
- optional safe headers required by the provider, if the provider supports them.

The boundary must not include:

- local path;
- `StorageReference` parsing;
- bearer token or signed URL persisted in retained business metadata;
- provider-specific OCR settings;
- Reader fields.

No exact Python signatures are defined here.

## Grant identity and lifecycle

Conceptual transport-grant states may include:

- `created`;
- `active`;
- `consumed`, if consumption is tracked;
- `expired`;
- `revoked`;
- `failed`.

These are transport-grant states, not processing-attempt states. The first test
version may not need persistence if human reviewers accept restart loss for
disposable data. Production may require persistent/auditable grant records.
Provider download may occur more than once because of retries, redirects, or
provider-side re-fetch behavior. Strict one-time-use URLs may therefore conflict
with provider retry/download behavior.

No database fields are defined here.

## TTL policy

TTL must cover source retrieval, not the entire OCR job. It should account for:

- provider queue delay before the coordinator starts downloading;
- provider download timeout;
- orchestration submission uncertainty;
- provider retries or duplicate fetches;
- job start delay in the provider environment;
- large-file download duration;
- Atlas/HF cold start and wake-up delay;
- clock skew between Atlas, provider, and object-store infrastructure;
- test vs production environment availability.

Result polling duration should not drive source-transport TTL once the provider
has downloaded and verified the PDF. A short configurable TTL range should be
selected during implementation planning, with different defaults possible for
disposable tests and production. This document intentionally does not set an
implementation constant without human approval.

## Replay and multiple-download policy

Options:

- Strictly one-time token: smallest replay window, but fragile if the provider
  retries after a partial download or follows validation paths that re-fetch.
- Bounded multiple downloads: allows a small number of retrievals before expiry;
  balances retry compatibility and abuse reduction.
- Unlimited downloads until expiry: most compatible but relies entirely on short
  TTL, secrecy, rate limits, and revocation.
- Revoke after verified provider download: safest after positive confirmation,
  but current provider does not callback to Atlas with a verified-download event.

Recommendation requiring human confirmation: use bounded multiple downloads or
unlimited downloads until short expiry for the first test version, then move
toward bounded downloads plus explicit revocation/audit when provider behavior
is better characterized. Avoid strict one-time tokens unless provider retry
behavior is proven compatible.

## Authentication design

| Mechanism | Evaluation |
|---|---|
| Opaque token in URL path | Compatible with URL-only provider input; easier to redact by path pattern; can still appear in logs. |
| Opaque token in query string | Compatible with URL-only input and object-store signatures; high leakage risk in logs, proxies, and stored provider state. |
| Bearer header | Better separation of URL and secret, but current provider request model only documents source URL/ETag/SHA-256, not custom download headers. |
| Signed URL | Strong for object stores and stateless grants; query-heavy signatures increase redaction needs and revocation tradeoffs. |
| Mutual/service identity | Strongest service-to-service posture but operationally heavier and not part of current provider URL protocol. |

Current provider compatibility favors a URL-contained credential unless the
provider is enhanced to send custom headers for source download. Human reviewers
must decide whether to accept path/query token leakage risk for M2 testing or
require provider header support first.

No actual secrets are included in this document.

## URL and token safety

Minimum rules:

- high-entropy random grant IDs/tokens or equivalent cryptographic signatures;
- HTTPS only;
- no source filename required in the URL;
- no `StorageReference` in the URL;
- no `Document` or `SourceFile` ID required in the URL;
- no credential logging;
- no credential in error bodies;
- no persistence in Raw Result envelopes;
- no analytics/referrer leakage;
- safe redaction helpers for URLs, tokens, and signed query strings;
- no directory traversal;
- no arbitrary URL forwarding;
- no open redirect.

## Provider URL validation and SSRF

There are two directions to keep separate:

1. Atlas generates a URL for the provider.
2. The provider downloads the URL supplied by Atlas.

Atlas should generate only URLs for Atlas-controlled or approved transport
origins. Provider-side SSRF defenses remain provider implementation ownership,
but Atlas must not assume provider defenses are complete. Current provider
evidence shows HTTPS enforcement, redirect HTTPS enforcement, byte/time limits,
and no hostname/IP allowlist or private-network block.

Before production, human reviewers should decide whether `paddle-vl-api` must be
restricted to Atlas-controlled origins. Production hardening should assess:

- Atlas-controlled origin allowlist;
- private-network SSRF controls;
- DNS rebinding;
- redirect validation on every hop;
- maximum redirect count;
- IPv4/IPv6 private ranges;
- loopback, link-local, and metadata endpoints;
- host changes after redirect;
- HTTPS downgrade prevention;
- provider deployment hardening.

Atlas transport design should avoid arbitrary URL forwarding and should not make
Atlas a blind proxy for user-supplied URLs.

## Byte delivery semantics

Transport must deliver:

- exact original retained bytes;
- no PDF re-rendering;
- no transcoding;
- no decompression/recompression;
- `application/pdf` media type for PDF source transport;
- `Content-Length` when known;
- optional ETag that is safe and not confused with source identity;
- SHA-256 integrity through provider request metadata and/or response headers;
- safe `Content-Disposition`, preferably generic and not dependent on original
  filename;
- streaming when available in a future Storage boundary;
- range requests only if needed by provider behavior or large-file support;
- failure if the retained object is missing or the storage reference is broken.

Processed TXT, rendered page images, OCR JSON, and Reader presentation data are
not part of this source transport.

## Streaming and memory

Current Storage `get()` returns bytes. A first Local Storage-backed transport
endpoint may therefore buffer the full PDF in memory before responding. This is
acceptable only with a documented size limitation for M2/test if human reviewers
approve it.

Large documents eventually require a streaming/open support design in Storage or
an object-storage presigned URL path. Adding streaming to Storage is deferred and
requires separate design. This task does not implement streaming.

## Relationship to Storage

- Storage owns retained bytes.
- Transport obtains bytes through Storage or provider-specific Storage mechanics
  behind an approved boundary.
- Transport does not become a Storage provider.
- Transport does not alter `SourceFile.retained`.
- Transport expiry does not delete source bytes.
- Transport grants are not Storage references.
- Future presigned URLs may be produced by provider-specific Storage mechanics
  behind a provider-independent transport boundary.

## Relationship to orchestration

Future orchestration responsibilities may include:

- request/create a transport grant;
- obtain provider-reachable URL and safe metadata;
- submit the provider job;
- retain grant identity/expiry in memory or future attempt state;
- reconcile uncertain submission;
- revoke or allow transport expiry when safe;
- distinguish transport failure from provider processing failure.

The current orchestrator is not modified in this PR.

## Relationship to future Processing Attempt persistence

A future persisted attempt may need to record:

- transport grant ID;
- transport type;
- issued time;
- expiry time;
- revocation time;
- source checksum;
- provider job ID;
- transport failure category.

It must not persist:

- plaintext grant token;
- signed URL;
- local filesystem path.

No schema is defined here.

## Failure model

| Failure category | Retryable | Terminal for current attempt | Requires new grant | Requires new processing attempt | Infrastructure consistency failure |
|---|---|---|---|---|---|
| Source not retained | No | Yes | No | Yes after retention decision | Maybe, if expected retained |
| Source reference broken | Usually no | Yes | No | Yes after repair | Yes |
| Grant creation failed | Yes if transient | No if retry succeeds | Yes | No | Maybe |
| Transport unavailable | Yes | No until retry budget exhausted | Maybe | Maybe | Maybe |
| Grant expired | Yes | No if new grant can be issued before submission certainty is lost | Yes | Maybe | No |
| Grant revoked | Maybe | Maybe | Yes | Maybe | No |
| Unauthorized retrieval | No for same request | Yes for that retrieval | Maybe | Maybe | Security event |
| Source checksum mismatch | No | Yes | Maybe after investigation | Yes | Yes if Storage bytes differ from Source metadata |
| Source size mismatch | No until investigated | Yes | Maybe | Yes | Yes if metadata promised a size |
| Provider download timeout | Yes | Maybe after budget | Maybe | Maybe | No unless transport is overloaded |
| Provider rejected URL | Maybe after URL policy fix | Maybe | Yes | Maybe | No |
| Transport cleanup failed | Yes | No for OCR result | No | No | Operational/orphan risk |

## Cleanup and revocation

Cleanup and revocation strategies:

- Expiration: baseline requirement; denies retrieval after TTL.
- Explicit revocation after provider download: ideal, but requires a reliable
  verified-download signal or server-side retrieval tracking.
- Revocation after accepted job submission: risky because the provider may not
  have downloaded the source yet.
- Revocation after provider status changes to running: safer than submission but
  still not proof that source download completed unless provider status semantics
  guarantee it.
- Revocation after timeout: useful for uncertain submission and abandoned jobs.
- Uncertain submission: if Atlas cannot determine whether the provider accepted
  the job, keep the grant valid only within the configured TTL and avoid
  indefinite extension.
- Provider retry: revocation must not break legitimate provider re-fetches.
- Orphaned grants: production needs cleanup workers, TTL scans, or object-store
  lifecycle rules.
- Audit records: production may need grant create/retrieve/revoke/expire events
  without storing credentials.

No cleanup is implemented by this task.

## Current HF test posture

- Current Local Storage and SQLite may be lost on container rebuild.
- Any local transport service or in-memory grant state may also be lost.
- This is acceptable only for disposable test data.
- Remote provider retrieval fails if the HF container is unavailable, sleeping,
  rebuilding, rebuilt, or no longer has the retained local source bytes/grant
  state.
- No production durability is claimed.
- Real user data requires persistent source storage and production-grade
  transport infrastructure before acceptance.

## Observability

Safe events and metrics:

- grant created;
- grant retrieval started/completed/failed;
- bytes delivered;
- checksum verified;
- grant expired/revoked;
- provider job correlation;
- elapsed retrieval time.

Never log:

- token;
- full transport URL;
- signed query;
- source bytes;
- `Authorization` headers;
- local paths.

## Testing strategy

Future tests should cover, without live provider calls in Required Backend CI:

- grant creation;
- expiry;
- revocation;
- authorized retrieval;
- unauthorized retrieval;
- exact bytes;
- SHA-256;
- media type;
- missing source;
- broken Storage reference;
- multiple downloads/replay;
- path traversal;
- URL/token redaction;
- provider redirect behavior;
- provider hash verification;
- orchestration handoff;
- uncertain submission;
- container restart/test-environment loss;
- mocked provider integration;
- manual live provider smoke outside required CI.

## Implementation split recommendation

These are candidate follow-up tasks grounded in the current repository state;
rename them if they conflict with roadmap planning.

### M2-003F

Implement provider-independent transport grant models/service with no route.
This can validate grant scope, TTL policy, redaction, and orchestration-facing
metadata without exposing source bytes.

### M2-003G

Implement a private Atlas source-transport HTTP endpoint for the current Local
test environment. It should be provider-only, short-lived, redacted in logs, and
explicitly limited by test-size constraints.

### M2-003H

Integrate transport grant creation with non-persistent orchestration and run a
manual live-provider smoke. Required CI should use mocked provider/download
behavior.

### Later production task

Implement presigned durable object-storage transport behind the same
provider-independent boundary after persistent source storage and security
posture are approved.

## Human decisions required

1. Initial transport option.
2. Production transport direction.
3. Whether the first implementation uses an Atlas download endpoint.
4. Token location: path, query, header, or signed URL.
5. Whether the provider can send custom authorization headers for source
   download.
6. TTL range and environment-specific defaults.
7. Replay/multiple-download policy.
8. Revocation timing.
9. Whether grant state is initially in memory or persisted.
10. Whether source transport must be audited.
11. Initial document-size limitation.
12. Streaming timing.
13. Provider SSRF/allowlist hardening before production.
14. Whether transport-grant identity belongs in future Processing Attempt
    persistence.
15. Production object-storage provider timing.

## Non-goals

This task does not:

- implement transport;
- expose source bytes;
- add a public route;
- add authentication middleware;
- add provider upload;
- add object storage;
- add streaming;
- modify Storage Adapter;
- add database schema;
- alter provider protocol;
- run a live provider smoke;
- change orchestration;
- change upload/Reader/OCR behavior.

## Decision summary

| Decision | Current evidence | Options | Recommendation | Blocking level | Human confirmation required? |
|---|---|---|---|---|---|
| Initial provider-reachable transport | Atlas has retained bytes behind opaque Local Storage; provider needs HTTPS URL | A, B, C, D, E | Option A for M2/test | Blocks live non-persistent provider jobs from retained Local sources | Yes |
| Production transport direction | Local/HF is ephemeral; object storage not implemented | A, B, D | Provider-independent grant boundary that can issue Option B later | Blocks production user data posture | Yes |
| URL credential placement | Provider documents source URL but not custom source headers | Path, query, bearer header, signed URL, service identity | Prefer provider-compatible URL credential for test only; revisit headers/object signing | Blocks first implementation details | Yes |
| TTL/replay/revocation | Provider may retry downloads; no callback confirms verified retrieval | One-time, bounded, until-expiry, revoke-on-download | Short configurable TTL with retry-compatible replay; revocation after safe signal/timeout | Blocks safe operational policy | Yes |
| Storage relationship | Storage owns bytes and Local paths internally | Proxy via Storage, presign through future provider mechanics, copy to transport store | Transport obtains bytes through Storage without becoming Storage | Blocks boundary correctness | Yes |
| Persistence/audit | No `ProcessingAttempt` persistence currently exists | In-memory, persisted grants, auditable attempts | In-memory may be acceptable only for disposable test; production likely persisted/audited | Blocks production readiness | Yes |
| SSRF/allowlist | Provider currently lacks hostname/IP allowlist in inventory | Atlas-controlled origin, provider hardening, both | Require Atlas-controlled origins/provider hardening before production | Blocks production security | Yes |
