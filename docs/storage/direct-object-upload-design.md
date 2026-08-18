# Browser Direct Object Upload — S0 Data-Plane Cutover

| Field | Value |
|---|---|
| Document Type | Storage / Upload Architecture |
| Status | Implementation-facing Staging design |
| Date | 2026-08-17 |
| Authority Domain | Large source-file ingress, durable source placement, and S0 runtime gates |
| Applies To | Atlas Backend Staging, Reader/Bookshelf Staging, private S3-compatible Object Storage |
| Related Storage Design | [Storage Adapter Design](storage-adapter-design.md) |
| Related Scalability Architecture | [Scalable Storage and Processing Architecture](../architecture/scalable-storage-and-processing-architecture.md) |

## Decision

Large source-file bytes must not use the Hugging Face Space application ingress as the Atlas data plane.

The accepted Staging cutover is:

```text
Browser
  |  small authenticated JSON: create direct-upload session
  v
Atlas Backend / Neon control plane
  |  short-lived presigned PUT + bounded metadata
  v
Browser -------------------------------> Private S3-compatible Object Storage
                                           |
                                           | server-side publish/copy
                                           v
                                      durable src_* object
                                           |
                           small authenticated completion JSON
                                           v
Atlas Backend -> SourceFile/Document -> ProcessingRun -> S0/Modal
```

Backend remains authoritative for business state. Object Storage owns durable binary source bytes. Neon owns business metadata and processing state. Modal remains elastic compute.

### Object-storage provider priority

The first provider to runtime-prove is **Hugging Face Storage Buckets**, using the HF S3-compatible gateway. The reasons are operational simplicity and vendor consolidation: Atlas already uses Hugging Face for the control-plane Space and existing bucket-backed storage.

Cloudflare R2 remains a compatible fallback if browser presigned PUT against the HF S3 gateway cannot satisfy the runtime acceptance gates. End users never need to install either provider; the browser only receives a short-lived presigned upload URL.

## Runtime evidence that triggered this cutover

The 528-page test PDF is 65,445,424 bytes. Repeated Staging tests established the following boundary:

1. Browser CORS preflight for the HF Space upload endpoint returned HTTP 200 in about 40 ms.
2. The actual upload body then waited for 120 seconds and was aborted by the frontend timeout.
3. A pure ASGI probe installed outside FastAPI CORS middleware recorded no entry for the actual POST body.
4. Neon created no new `Document`, `SourceFile`, or `ProcessingRun` for the failed attempt.
5. Changing raw octet-stream to multipart/form-data and moving the server spool from the HF bucket mount to `/tmp` did not remove the failure.

Therefore the failed body did not reach the Atlas ASGI application boundary. The evidence does not support blaming `request.form()`, `/tmp`, OpenCV, Neon, or ProcessingRun creation for this failure.

The HF resumable bridge remains compatibility code, not the target data plane.

## Initial implementation slice

The first runtime slice is intentionally bounded:

- PDF only;
- browser-direct private object-store upload;
- single PUT up to 100 MiB;
- short-lived presigned URL;
- SHA-256 computed by the browser and carried in signed completion claims;
- temporary ingress object first;
- server-side object-store copy to a durable Atlas `src_*` reference only after completion validation;
- no database schema migration;
- direct upload disabled unless explicitly configured.

The 65.4 MB / 528-page runtime test fits this slice. Files above the single-PUT boundary require the next direct multipart slice rather than a fallback through HF Space ingress.

## Why ingress and durable keys are separate

Browser upload targets a temporary key:

```text
<atlas-prefix>/ingress/<upload_id>
```

Successful completion publishes inside the object store to the durable provider-independent Atlas reference mapping:

```text
<atlas-prefix>/objects/<shard>/<shard>/src_<uuid>
```

This separation provides three useful properties:

1. incomplete/uncommitted bytes do not become business-owned source evidence;
2. server-side copy does not send the source through the Atlas Backend/HF Space;
3. orphan cleanup can target `ingress/` independently from durable `objects/`.

For providers with lifecycle rules, an ingress-prefix lifecycle can be the crash-recovery backstop. **HF Storage Buckets currently do not support lifecycle rules**, so Atlas must provide reference-aware cleanup for abandoned ordinary ingress objects. The cleanup task must never delete durable `objects/` content.

## Direct-upload control-plane contract

### Create

`POST /api/v1/direct-upload-sessions`

The browser sends only bounded metadata:

- filename;
- byte size;
- SHA-256;
- content type.

The Backend:

1. verifies direct upload is explicitly enabled and fully configured;
2. enforces the current PDF/single-PUT size policy;
3. allocates `upload_id`, `document_id`, `source_file_id`, and opaque `src_*` storage reference;
4. creates short-lived HMAC-signed completion claims;
5. returns a presigned private object-store PUT URL and the exact required headers.

No `Document`, `SourceFile`, or `ProcessingRun` is created at this point.

### Browser PUT

The browser sends the file directly to the presigned object-store URL. It must not add Atlas `Authorization: Bearer ...` to this request. The object-store URL itself is the temporary bearer capability.

For generic S3/R2, signed user metadata may carry checksum/upload identifiers. For HF Storage Buckets, arbitrary `x-amz-meta-*` metadata is not persisted, so the HF presigned PUT signs only the object key and supported headers such as normalized `Content-Type`.

The private object store must permit browser PUT from the Staging frontend origin. Browser CORS/presigned PUT against the HF gateway is a runtime capability gate and must be tested before enabling the frontend cutover.

### Complete

`POST /api/v1/direct-upload-sessions/{upload_id}/complete`

The Backend:

1. verifies the signed completion claims and expiry;
2. HEAD-verifies the temporary object size and content type;
3. where the provider preserves trusted user metadata, also verifies checksum/upload-id metadata;
4. publishes the ingress object inside Object Storage to the durable `src_*` key using server-side copy;
5. verifies the published object is present with the expected mechanical metadata;
6. creates the `Document` and retained primary `SourceFile` transactionally;
7. queues the existing PDF ingestion background path;
8. best-effort deletes the ingress object.

The object remains available on a DB commit failure so the same signed claims can be retried. The completion path must never delete a potentially winning durable object because another identical completion request lost a database race.

## Integrity model

The browser-computed SHA-256 is not treated as final proof merely because it is signed into a session.

For generic S3/R2 providers that preserve `x-amz-meta-*`, completion can compare the expected SHA-256 with object metadata as an inexpensive admission check.

HF Storage Buckets do **not** preserve arbitrary user metadata. Therefore HF completion uses size/content-type plus the signed object/session identity as the lightweight admission gate. Final source integrity remains fail-closed in the existing ingestion path:

1. `SourceFile.checksum_sha256` stores the browser-declared expected SHA-256 from the signed completion claims;
2. background retained-source retrieval downloads the durable object exactly as required for preprocessing;
3. Atlas checks `%PDF-`, exact byte size, and recomputes SHA-256 over the actual bytes;
4. any mismatch fails before OpenCV/provider processing.

This avoids a redundant 65 MiB Object Storage -> HF download inside the `/complete` request while preserving actual-byte integrity before processing.

## Deferred page count

The old synchronous `/api/v1/upload` path opened the request body with PyMuPDF before returning, primarily to populate `Document.pages_count`.

Direct upload must not download the entire source back into the request handler just to count pages. Instead:

1. direct completion creates the PDF `Document` with page count unknown;
2. background retained-source retrieval occurs once as part of the existing bounded preprocessing path;
3. after source verification, PyMuPDF determines the real page count before the S0 heartbeat/OpenCV context is entered;
4. heartbeat and OpenCV receive the real integer page count;
5. the Backend persists that count if it was previously missing;
6. existing uploads that already have a page count continue passing it as an invariant.

This removes an otherwise redundant Object Storage -> HF transfer before processing begins.

## Transitional Storage federation

Existing Atlas references remain valid. `SourceFile.storage_reference` is an opaque `src_*` logical reference, not a physical path.

During migration:

- existing local/HF-mounted source and derived objects remain on the primary LocalStorage provider;
- current processing/derived `put()` calls continue writing to that primary provider;
- newly committed browser-direct source objects live in the secondary S3-compatible provider;
- reads/deletes check primary first and only touch the secondary when the reference is absent locally.

Primary hits intentionally short-circuit. An object-store outage must not make existing local/HF-mounted books unreadable.

No historical mass migration is required for this cutover.

## Hugging Face Storage Bucket S3 compatibility

HF Storage Buckets are accessed through the S3 gateway with these Atlas requirements:

- endpoint: `https://s3.hf.co/<namespace>`;
- bucket argument: bare HF bucket name;
- region: `us-east-1`;
- path-style addressing is required;
- boto request checksum calculation is limited to `when_required`;
- arbitrary user metadata is not relied upon;
- `CopyObject` is used only within the same HF namespace.

`S3StorageProvider` auto-detects the `s3.hf.co` endpoint and applies these compatibility rules. Other S3-compatible providers retain their normal behavior.

## Configuration

Direct upload is fail-closed and disabled by default.

Preferred HF Staging settings when enabled:

- `ATLAS_DIRECT_UPLOAD_ENABLED=true`
- `ATLAS_DIRECT_UPLOAD_SIGNING_SECRET=<32+ character secret>`
- `ATLAS_OBJECT_STORAGE_ENDPOINT_URL=https://s3.hf.co/carsonhhs`
- `ATLAS_OBJECT_STORAGE_BUCKET=<private HF bucket name>`
- `ATLAS_OBJECT_STORAGE_ACCESS_KEY_ID=<HFAK... S3 access key>`
- `ATLAS_OBJECT_STORAGE_SECRET_ACCESS_KEY=<HF S3 secret>`
- `ATLAS_OBJECT_STORAGE_REGION=us-east-1`
- optional `ATLAS_OBJECT_STORAGE_PREFIX=atlas`
- optional `ATLAS_DIRECT_UPLOAD_URL_TTL_SECONDS`
- optional `ATLAS_DIRECT_UPLOAD_SINGLE_PUT_MAX_BYTES`

HF S3 credentials are generated from a Hugging Face access token and inherit that token's permissions. Prefer a fine-grained/write token scoped only to the Staging bucket/namespace when available.

Credentials are server-side only and must never be returned to the browser or logged.

## Browser capability gate for HF

Do not enable the Reader frontend direct-upload path merely because boto3 HEAD/PUT works server-side. The decisive Staging probe is browser -> HF S3 gateway:

1. Backend creates a presigned PUT for a temporary `atlas/ingress/...` key.
2. GitHub Pages Staging performs the PUT without Atlas Authorization headers.
3. Browser preflight, if emitted, must complete normally.
4. The actual PUT must complete without the 120-second HF Space ingress failure mode.
5. Backend HEAD must observe the exact byte size/content type.
6. Server-side `CopyObject` must publish to the durable `src_*` key.
7. The ingress object must be deleted after successful commit.

First prove this with a 1-2 MiB PDF/blob, then with the real 65,445,424-byte / 528-page PDF.

If the HF browser PUT/CORS gate cannot be made reliable, retain the S3 abstraction and move only the data-plane provider to Cloudflare R2 rather than returning the payload to HF Space ingress.

## Orphan cleanup

HF Storage Buckets do not currently expose S3 lifecycle rules. Atlas therefore owns cleanup of abandoned ordinary single-PUT ingress objects.

The first runtime proof may use explicit best-effort cleanup after success/failure. Before multi-user rollout, add a bounded scheduled GC that:

- only scans the Atlas `ingress/` prefix;
- deletes objects older than a conservative TTL;
- never deletes any key referenced by committed `SourceFile` state;
- records bounded cleanup telemetry;
- is idempotent and safe across retries.

Future direct multipart uploads benefit from HF's automatic expiry of incomplete multipart sessions, but committed temporary ingress objects still require Atlas ownership-aware cleanup.

## Runtime acceptance gates

Direct upload is not runtime-proven until a real 528-page file demonstrates all of the following in Staging:

1. Browser never sends the 65.4 MB PDF body to the HF Space host.
2. Presigned HF Storage Bucket PUT completes successfully.
3. Completion endpoint creates exactly one `Document` and one retained primary `SourceFile`.
4. `SourceFile.storage_reference` resolves through Storage federation to the durable HF bucket source.
5. Background retrieval validates actual source byte size and SHA-256.
6. Page count is discovered and persisted as 528 without a second pre-processing source download in the request handler.
7. Presentation classification completes 528/528 with bounded memory.
8. Ordinary V4 remains globally monotonic and bounded across all 528 pages.
9. Provider runtime preflight succeeds.
10. #320 byte-bounded sharding materializes sequential provider shards within the hard size cap and remaps provider-local pages to original pages.
11. Canonicalization and Reader v2 output complete.

Until those gates are observed, #320/#326 and S0 remain not fully runtime-proven.

## Next additive slices

After the 528-page single-PUT proof:

1. add S3-compatible direct multipart upload for files above ~100 MiB, with browser part retry and bounded concurrency;
2. add durable orphan/reference-aware GC telemetry;
3. migrate additional source/artifact classes only when their ownership/retention contracts are explicit;
4. connect content-addressed duplicate detection so identical sources can reuse retained content/processing safely across uploads without sharing user ownership.
