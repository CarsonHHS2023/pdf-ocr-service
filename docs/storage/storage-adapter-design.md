# Storage Adapter Design

| Field | Value |
|---|---|
| Document Type | Storage Design |
| Version | v1 |
| Authority Domain | storage-adapter boundaries and design responsibilities |
| Applies To | StorageObjectReference, ObjectKey, ObjectMetadata, StorageProvider, StorageAdapter, StoredObject, original TXT/PDF source bytes, local filesystem implementation |

## Status

Human-confirmed v1 design decisions recorded; implementation remains pending future implementation review.

This document does not authorize implementation by itself. It records accepted v1 design directions for a future M1 implementation task, while exact method signatures, classes, configuration names, key namespace, schema use, and provider placement remain pending implementation review. It does not change production code, public APIs, database models, migrations, CI, dependencies, configuration, or runtime behavior.

## Objective

Current storage behavior is spread across filesystem paths, database BLOBs, database text fields, cleanup code, upload logic, and Reader-specific paths. Originals are written under `uploads/` and normally deleted, TXT output is written under `output/`, page and image bytes live in database columns, OCR/MinerU payloads live in text columns, and cleanup uses direct path operations.

The Storage Adapter should establish one infrastructure boundary for object mechanics without taking ownership of business meaning or policy. The design principle is: separate meaning from mechanics. Business gives objects meaning. Storage manages bytes and object mechanics.

## Scope

The first Storage Adapter design supports current M1 needs only.

It should enable:

- retaining original TXT/PDF source bytes;
- storing and retrieving objects through a provider-independent interface;
- deleting objects through explicit mechanics;
- checking object existence;
- returning stable storage references;
- local filesystem implementation first;
- future provider replacement without changing business/API contracts.

It should not implement:

- S3;
- Cloudflare R2;
- Azure Blob;
- Modal Volume;
- Hugging Face Volume abstraction;
- encryption;
- compression;
- deduplication;
- versioning;
- lifecycle workers;
- garbage collection;
- signed URLs;
- public object URLs;
- multipart upload;
- streaming video;
- CDN behavior;
- object replication;
- provider migration tooling.

## Core boundary

The Storage Adapter is an infrastructure boundary that knows:

- object references;
- bytes or streams;
- object metadata required for mechanics;
- provider-specific implementation details behind the boundary.

Storage must not know:

- Document type;
- Book/Receipt/Contract semantics;
- Reader behavior;
- Category/Collection/Domain;
- retention business policy;
- legal meaning;
- canonical knowledge;
- learning behavior.

Storage knows objects and bytes. Business knows meaning and policy.

Storage may report whether bytes exist, write bytes, return bytes, delete bytes after an authorized caller asks it to, and calculate mechanical metadata. Storage must not decide that a `Document` is a book, that a retained Source may be purged, that an artifact is canonical knowledge, or that Reader compatibility should be changed.

## Design vocabulary

The vocabulary below is conceptual. This task does not require every concept to become a separate Python class.

| Term | Purpose | Belongs in v1? | Public or internal? | Persisted? | Provider-independent? |
|---|---|---:|---|---|---|
| `StorageObjectReference` | Stable handle a business row can store and later pass back to Storage for resolution. | Yes, conceptually. | Public inside application/service boundary; not public API. | Yes, where a business/artifact row needs to reference bytes. | Yes. |
| `ObjectKey` | Provider-portable address within a storage namespace, such as a relative key. | Yes, internally. | Internal to Storage or storage-aware infrastructure code. | Possibly as part of a reference, pending decision. | Should be. |
| `ObjectMetadata` | Mechanical metadata such as byte size, checksum, content type, creation time, and provider checksum. | Minimal v1 only. | Internal return/value data; selected fields may be copied to business metadata. | Storage itself need not persist all metadata; business decides what schema stores. | Mostly, except provider checksums such as ETag. |
| `StorageProvider` | Low-level implementation for local disk now and future cloud providers later. | Local provider only in v1. | Internal infrastructure. | No. | Interface yes; implementation details no. |
| `StorageAdapter` | Application-facing boundary exposing the minimal operations and hiding provider mechanics. | Yes. | Internal application/service interface, not API contract. | No. | Yes. |
| `StoredObject` | Return concept combining bytes/stream plus metadata. | Optional in v1. | Internal. | No. | Yes if it contains provider-neutral fields. |

Avoid over-modeling: v1 can be an interface/protocol plus small value objects if that is enough. A separate `StoredObject` class is useful only if `get` must return both content and metadata without multiple calls.

## Stable storage reference

A stable storage reference is the durable identifier business metadata stores to reconnect an owner record, such as `SourceFile`, to stored bytes. It should not be a public API contract and should not expose local machine paths, buckets, credentials, or provider-specific mechanics.

### Option A: store raw provider URI/path directly

Examples:

- `file:///...`
- `s3://bucket/key`
- `r2://bucket/key`

| Dimension | Assessment |
|---|---|
| Portability | Weak; persisted values encode provider and often location. |
| Provider migration | Hard; migration rewrites every reference or requires legacy URI support forever. |
| Debugging | Easy because operators can see the location. |
| Public API leakage | High risk if existing path fields or responses surface the value. |
| Database simplicity | Simple single string. |
| Backward compatibility | Superficially compatible with current string path fields, but cements the current problem. |
| Testability | Easy for local tests, weaker for provider-independent contract tests. |

### Option B: store opaque provider-independent reference and resolve it through Storage

| Dimension | Assessment |
|---|---|
| Portability | Strong; the reference can remain stable while provider mapping changes. |
| Provider migration | Strong; Storage can resolve old/new mappings internally. |
| Debugging | Weaker unless tooling can resolve and inspect references. |
| Public API leakage | Low; opaque references should stay internal and provider-neutral. |
| Database simplicity | Simple if a single string is used; requires resolver discipline. |
| Backward compatibility | Good if old paths are treated as legacy references during transition. |
| Testability | Strong; fake/local providers can resolve the same reference format. |

### Option C: store provider name + object key as separate fields

| Dimension | Assessment |
|---|---|
| Portability | Medium; object key can be portable, but provider name persists. |
| Provider migration | Medium; can migrate per-provider, but schema rows reveal provider placement. |
| Debugging | Good. |
| Public API leakage | Medium risk if fields are serialized. |
| Database simplicity | More columns and schema decisions; clearer querying. |
| Backward compatibility | Requires schema work and compatibility mapping. |
| Testability | Good; explicit provider selection is easy to test. |

### Accepted v1 design direction

Use **Option B: opaque provider-independent logical object ID** for business persistence. Business/application callers must not parse it, and it must not expose local paths, provider names, buckets, credentials, or provider-specific mechanics.

For v1, this direction does **not** require a separate mapping registry. The Local provider may derive its internal object key from the logical ID behind the Storage boundary. Future provider migration must preserve the logical reference without leaking provider mechanics into public APIs. Exact encoded string syntax remains an implementation detail and does not define final database columns.

## Object key strategy

Object keys are mechanical storage addresses, not business truth. They should be provider-portable, collision-safe, immutable after write where practical, and free of user-sensitive original filenames.

Requirements to evaluate:

- **Deterministic vs generated keys:** deterministic keys make lookup and cleanup easy; generated object IDs reduce accidental business leakage and collision risk.
- **Collision safety:** keys must not collide across uploads, retries, documents, or providers.
- **Document grouping:** grouping by document/source can help debugging and manual cleanup, but leaks business structure into mechanics.
- **Source/artifact distinction:** source and artifact keys should not be confused; Storage can store both, while Business assigns meaning.
- **Extension handling:** extensions help humans/tools, but must not be trusted as content type or security proof.
- **Immutability:** original source keys should behave as immutable evidence references once committed.
- **Human readability:** useful for operators, but should not expose titles, filenames, user names, tenant names, or legal details.
- **Provider portability:** avoid absolute paths, drive letters, provider URI schemes, or characters that behave differently across providers.
- **Avoiding business-sensitive data:** original filenames are metadata, not authoritative keys.

Example conceptual patterns:

| Pattern | Benefits | Risks | Status |
|---|---|---|---|
| `documents/{document_id}/sources/{source_file_id}/original.pdf` | Easy grouping and debugging; maps to current aggregate. | Encodes business IDs and source role in mechanics; document ID changes are awkward. | Candidate only. |
| `objects/{object_id}` | Strong decoupling, low leakage, easy provider migration. | Less readable; needs metadata lookup for debugging. | Candidate only. |
| `sources/{source_file_id}` | Simple for source retention. | Couples source table identity to storage; weaker for multiple renditions/extensions. | Candidate only. |

### Accepted v1 design direction

Use generated collision-safe, immutable, non-sensitive object IDs. Original filenames remain provenance metadata, not authoritative keys. Source objects use create-only semantics: an existing key with the same checksum may be treated as an idempotent retry, but an existing key with different bytes/checksum must fail. Silent overwrite of retained source evidence is prohibited.

Exact key namespace/path pattern remains deferred to implementation review.

## Minimal v1 operations

| Operation | Current requirement | Future usefulness | Complexity | v1? | Deferred? |
|---|---|---|---|---:|---:|
| `put` | Required to retain original TXT/PDF bytes. | Foundational for all providers. | Medium due atomicity/integrity. | Yes | No |
| `get` | Required for future processing/reprocessing and tests. | Foundational. | Low for bytes; higher for streams. | Yes | No |
| `delete` | Required as explicit mechanics after policy approval and cleanup. | Foundational. | Medium because missing/partial failure semantics matter. | Yes | No |
| `exists` | Required for verification and compatibility checks. | Useful for health/repair. | Low. | Yes | No |
| open/read stream | Not required for initial small TXT/PDF retention if bytes are already read today. | Important for future large audio/video and cloud efficiency. | Medium to high. | No | Yes |
| `copy` | Not required. | Useful for migrations/versioning later. | Provider semantics vary. | No | Yes |
| `move` | Not required. | Useful for staging/finalize later. | Hard across providers; usually copy+delete. | No | Yes |
| `list` | Not required for request path. | Useful for admin/orphan tooling. | Risky and provider-specific pagination. | No | Yes |
| `stat`/`head` | Partly covered by `exists` and returned metadata. | Useful for repair and lazy reads. | Low/medium. | Optional only if metadata returned by `put/get` is insufficient. | Prefer defer |
| `generate_url` | Not needed; public URLs are out of scope. | Useful for downloads/CDN later. | Security and expiration complexity. | No | Yes |

### Accepted v1 operation set

Implement only `put`, `get`, `delete`, and `exists` for v1. `put` returns mechanical metadata for the bytes actually stored:

- stable storage reference;
- byte size;
- SHA-256 checksum.

Because `put` returns actual mechanical metadata, `stat`/`head` is not required in v1. Do not define exact Python signatures in this design.

## Bytes vs streams

| Option | Assessment |
|---|---|
| Option A: bytes-only API | Matches current upload behavior, since current endpoints read TXT/PDF bytes into memory before writing. It is easiest to test and simplest for local provider implementation. It is not ideal for future audio/video or very large PDFs. |
| Option B: file-like stream API | Better for large files and cloud providers, but increases complexity around lifetime, retries, checksums, test doubles, and async behavior. Current M1 needs do not require it. |
| Option C: support both through a small abstraction | Future-friendly but risks designing tomorrow's storage features today if both are implemented immediately. |

### Accepted v1 design direction

Use a **bytes-first v1 API** for original TXT/PDF retention because it matches the current upload implementation and minimizes M1 risk. This is not the permanent interface for all future object sizes. Stream support may be added later as an additive operation that does not break existing bytes-based callers. Large PDF, audio, and video support requires a separate design review before implementation.

## Sync vs async

| Approach | Assessment |
|---|---|
| Synchronous interface | Best matches local filesystem and current direct `open`/`unlink` behavior; easiest to test. In FastAPI request handlers, large blocking operations can still block the event loop if called directly. |
| Asynchronous interface | Better fit for async web handlers and some cloud clients; awkward for local disk without threadpool wrappers; more complex tests. |
| Sync core with async wrapper | Practical migration path: reliable local implementation first, optional async dependency wrapper later where request path needs it. |
| Provider-dependent mixed behavior | Avoid; it leaks provider mechanics into callers and complicates tests. |

### Accepted v1 design direction

Use a **synchronous core interface** for the local v1 adapter. Local provider mechanics are synchronous, and current code already performs blocking filesystem I/O directly. Async route call sites own any future thread-offloading decision. Storage must not expose fake async methods that perform blocking work directly. Future cloud or large-object needs may justify an additive async design.

## Error model

A small provider-independent taxonomy is enough:

| Error | Meaning | Retryable? | Fail closed? | Mapping |
|---|---|---:|---:|---|
| Object not found | Reference/key resolves but bytes are absent. | Usually no, except eventual-consistency future providers. | Yes for evidence reads. | Service may map to not-found or failed dependency depending business row state. |
| Write failure | Bytes were not durably stored. | Sometimes. | Yes. | Upload should fail or mark retention failed; do not pretend evidence is retained. |
| Read failure | Bytes exist but cannot be read. | Sometimes. | Yes. | Internal/service error; do not expose provider details. |
| Delete failure | Authorized delete could not complete. | Sometimes. | Yes for policy state; do not mark purged until confirmed. | Service error or deferred cleanup state. |
| Invalid reference | Reference malformed, unsupported, or unsafe. | No. | Yes. | Internal validation/business data error. |
| Provider unavailable | Storage backend unavailable. | Yes. | Yes. | Service unavailable/internal infrastructure error. |
| Integrity mismatch | Size/checksum differs from expected. | Maybe after rewrite/retry. | Yes. | Internal integrity failure; quarantine/repair later. |
| Object already exists | Create-only source write found an existing object. | Only when checksum matches as idempotent retry. | Yes when bytes/checksum differ. | Business/service layer decides retry handling. |

Conceptual error names are `ObjectNotFound`, `InvalidReference`, `WriteFailure`, `ReadFailure`, `DeleteFailure`, `ProviderUnavailable`, `IntegrityMismatch`, and `ObjectAlreadyExists`. Do not implement exception classes in this PR.

Provider SDK exceptions must remain internal and be translated at the boundary. Missing-object deletion must be reported distinctly rather than silently treated as success; the business layer decides whether missing-on-delete is acceptable idempotency or evidence inconsistency. Evidence read and integrity failures fail closed. Public API error mapping remains out of scope, and this design does not change current API error responses.

## Integrity metadata

Storage may calculate mechanics/integrity metadata. SourceFile or future business metadata decides what is persisted and why.

| Metadata | v1 assessment |
|---|---|
| Byte size | Recommended for v1; cheap and already conceptually present on `SourceFile`. |
| SHA-256 checksum | Recommended for v1 write-time calculation/verification where bytes are available. |
| Content type | Caller/business metadata may provide it; Storage should not trust or infer policy from it. |
| Original filename | Business/source metadata, not Storage key authority. |
| Created timestamp | Useful mechanically, but database rows already have timestamps; optional. |
| ETag/provider checksum | Provider-specific; keep internal unless needed for debugging/repair. |

### Accepted v1 integrity behavior

For v1, Storage calculates and returns actual byte size and SHA-256 checksum for bytes passed to `put`. If callers supply expected size/checksum, Storage verifies them. Business/`SourceFile` decides what is persisted and why. Original filename and MIME type remain provenance/business metadata. Provider ETag must not be treated as SHA-256. Do not redesign the `SourceFile` schema here.

## Retention and deletion boundary

Business/policy decides whether deletion is allowed. Storage executes deletion mechanics. Storage must not autonomously delete original evidence. Temporary cleanup may be system-authorized when object policy permits it. `delete()` is a mechanism, not a policy decision.

Future implementation should prevent application code from bypassing policy by routing source deletion through a dedicated source-retention/business service that checks source type, retention state, deletion authority, and downstream references before calling Storage. Direct provider path deletion should be treated as legacy technical debt and removed from source-object paths over time.

Accepted boundary: Business/policy authorizes deletion; Storage executes mechanics; retained Source objects must not be deleted directly by generic application cleanup. Exact user/admin/compliance authority is deferred. No new source-deletion API or UI is authorized in M1-003C.

This task does not implement policy enforcement.

## Ownership and source of truth

- `Document` is authoritative for business identity.
- `SourceFile` is authoritative for source association/provenance metadata.
- Storage is authoritative for object-byte existence and mechanics.
- A storage reference links `SourceFile` or future Artifact records to stored bytes.
- Stored bytes do not become business truth solely because they exist.
- Database metadata does not prove bytes still exist.
- Storage existence does not prove business ownership still exists.

Consistency risks include metadata rows pointing to missing objects, orphan objects with no owning row, retained bytes whose policy state is stale, and derived artifacts mistaken for original evidence. The adapter can reduce mechanical inconsistency, but it cannot replace business ownership or transaction design.

## Local filesystem provider design

The first provider should be a local filesystem provider conceptually. It should:

- operate under one configured root directory;
- prevent path traversal;
- create parent directories safely;
- write atomically where practical;
- avoid partial-file exposure;
- support deterministic tests with temporary directories;
- avoid storing absolute machine-specific paths in public contracts;
- clean temporary files on failed writes where practical.

Minimum M1 implementation requirements include one configured storage root; rejection of absolute paths, parent traversal, Windows drive prefixes, and path escape; create-only source writes unless checksum-idempotent retry is confirmed; temporary and final files on the same filesystem; complete and closed temporary writes before atomic publication; failed temporary-write cleanup; no machine-specific absolute paths exposed to business/public APIs; unsafe symlink conditions treated as fail-closed; and tests for both POSIX-style and Windows-style traversal inputs.

Conceptual atomic write strategy:

1. Resolve a provider-portable object key under the configured root.
2. Reject absolute paths, `..`, drive prefixes, symlinks where unsafe, or resolved paths outside the root.
3. Create parent directories with safe permissions where practical.
4. Write bytes to a unique temporary file in the same directory or same filesystem.
5. Flush and close the temporary file.
6. Rename/replace into final location atomically where supported by the OS.
7. Remove the temporary file on failure where practical.

This design does not implement the provider.

## Configuration

Conceptual configuration needs:

- provider type;
- local root;
- optional namespace/prefix;
- future credentials/provider configuration.

Configuration belongs outside business models. Secrets must not be stored in database rows. Public APIs must not expose provider credentials. Current v1 may support only a local provider. Environment-variable names are not defined here; if future implementation proposes names, they should be labeled implementation recommendations and reviewed with existing settings conventions.

## Dependency injection and construction

| Option | Assessment |
|---|---|
| Option A: global singleton | Simple but hard to test, hard to replace, and can hide provider state. |
| Option B: FastAPI dependency | Good for router-level integration and request tests; aligns with current FastAPI structure. |
| Option C: service constructor injection | Strong for unit tests and non-HTTP services; makes ownership explicit. |
| Option D: application container/factory | Clean long-term, but likely heavier than M1 needs. |

### Accepted v1 construction direction

Use a small storage factory built from settings, a FastAPI dependency for route injection and test override, and explicit injection into source-retention/service/background-task functions as needed. Avoid import-time global provider construction with filesystem side effects. Do not perform a broad service-layer refactor solely for dependency injection. Exact class/function placement remains an implementation detail. Do not implement dependency injection in this PR.

## Transitional integration map

| Current item | Current owner | Current storage mechanism | Future Storage Adapter candidate | M1 migration? | Remain DB-resident for now? | Compatibility risk |
|---|---|---|---|---:|---:|---|
| `uploads/{book_id}_original.txt` | Upload ingestion / SourceFile metadata | Temporary local file, deleted after processing | Yes, as retained Source object | Yes for original source retention | No, bytes should be retained via Storage if approved | Medium; current tests expect deletion/null paths. |
| `uploads/{book_id}_original.pdf` | Upload ingestion / SourceFile metadata | Temporary local file, deleted after rendering | Yes, as retained Source object | Yes for original source retention | No, bytes should be retained via Storage if approved | High; current rendering needs path and current behavior deletes original. |
| `output/{book_id}_processed.txt` | Document/Reader compatibility | Durable local text file | Possible derived artifact | Prefer defer | N/A filesystem today | High for TXT Reader content; moving now may change behavior. |
| `Document.original_file_path` | Compatibility metadata | String path, usually null on success | Legacy field, not future provider reference | No broad change except compatibility handling if needed | N/A | High because response field exists. |
| `Document.processed_file_path` | Reader TXT compatibility | String path to `output/` | Future artifact reference or compatibility shim | Defer | N/A | High because TXT content reads from it. |
| `SourceFile.storage_reference` | Source provenance metadata | Nullable string, currently empty in success paths | Primary candidate for stable source reference | Yes if original retention approved | N/A | Medium; semantics must be clear. |
| `PdfPage.page_image_data` | PdfPage / processing | Database BLOB | Future derived artifact candidate | Defer | Yes | High for OCR, crop, page image endpoint. |
| `BookImage.image_data` | BookImage / Reader image endpoint | Database BLOB | Future presentation/artifact candidate | Defer | Yes | High for `image_id` marker compatibility. |
| `PdfPage.ocr_raw_json` | Page OCR processing | Database text | Future processing observation/artifact | Defer | Yes | Medium; MinerU depends on it. |
| `MineruResult.result_json` | MinerU/Reader content | Database text | Future structured artifact/canonicalization input | Defer | Yes | High for PDF Reader content assembly. |

## M1 implementation boundary

| Scope | Description | Assessment |
|---|---|---|
| Scope 1 | Retain original TXT/PDF through `LocalStorageAdapter` only. | Smallest useful boundary; directly addresses source evidence gap while preserving Reader behavior. |
| Scope 2 | Also move processed TXT to Storage. | Useful later, but risks TXT Reader compatibility and path response semantics. |
| Scope 3 | Also move page/image blobs to Storage. | Too broad for M1; affects OCR, image endpoints, and DB behavior. |
| Scope 4 | Move all storage-related data. | Not appropriate; large migration and high runtime/API risk. |

### Accepted M1 implementation scope

Choose **Scope 1** for M1-003D: retain original uploaded TXT and PDF bytes through a Local Storage Adapter only. Explicitly defer processed TXT migration, `PdfPage` image BLOB migration, `BookImage` BLOB migration, OCR JSON migration, MinerU JSON migration, all other Artifact migration, and cloud providers.

Processed TXT remaining in `output/` is an intentional transitional compatibility boundary, not evidence that Storage already owns every file. Preserve Reader behavior and avoid a broad migration.

## Compatibility

Future implementation must preserve:

- existing Reader API paths unchanged;
- response fields unchanged;
- image marker protocol unchanged;
- current `book_id`/`image_id` behavior unchanged;
- TXT/PDF processing behavior unchanged where possible;
- existing disposable test DB may be recreated;
- current DB blob persistence may remain transitional;
- provider references must not leak into current public API.

No Reader compatibility change is authorized by this design.

## Failure scenarios

| Scenario | Consistency risk | Preferred ordering | Compensation direction | M1 must handle? | Deferred? |
|---|---|---|---|---:|---:|
| Failed source write | `SourceFile` claims retention when bytes are absent. | Do not mark retained until write succeeds. | Fail upload or mark retention failed explicitly. | Yes for original retention. | No |
| DB commit succeeds but object write fails | Metadata without bytes. | Avoid by writing object before final retained metadata. | Clear reference/retained state or fail transaction. | Yes | No |
| Object write succeeds but DB commit fails | Orphan object. | Write first, commit metadata second. | Best-effort delete object; later orphan cleanup. | Best effort | Full orphan GC deferred |
| Delete policy approved but object deletion fails | Business says deleted but bytes remain. | Delete object before final purge state where practical. | Keep pending-delete/failed-delete state later. | Basic failure propagation | State machine deferred |
| DB row deleted while object remains | Orphan and possible stale sensitive data. | Policy/service should delete object before or with row deletion. | Orphan cleanup later. | Best effort for sources once implemented | GC deferred |
| Object missing while DB reference remains | Broken reprocessing/evidence read. | Verify after write; check on read. | Surface internal/service error and repair later. | Read/exists behavior yes | Repair workflow deferred |
| Duplicate upload retry | Key collision or duplicated objects. | Use collision-safe generated key or idempotency plan. | If duplicate key, fail closed or verify checksum. | Basic collision safety | Idempotency workflow deferred |
| Process crash during write | Temp/partial file may remain. | Atomic temp write then rename. | Ignore non-final temp files or cleanup later. | Atomic local write should handle partial exposure | Temp scavenger deferred |
| Partial file | Evidence corruption. | Atomic write and checksum/size verification. | Delete failed temp/final where safe, fail closed. | Yes | No |
| Checksum mismatch | Stored bytes differ from source metadata. | Compute before/after write where practical. | Fail retention; do not mark retained. | Yes for bytes API | Advanced quarantine deferred |

Do not design a distributed transaction system.

## Transaction boundary

| Option | Benefits | Risks |
|---|---|---|
| Option A: write object first, then commit metadata | Avoids committed metadata pointing to absent bytes when write fails; natural for source retention. | DB failure can leave orphan objects. |
| Option B: commit metadata first, then write object | Gives row identity before storage; easy to reference source ID. | Dangerous because committed row can claim retention before bytes exist. |
| Option C: staging state + write + finalize metadata | Most explicit and reliable; can model pending/failed/final states. | More schema/service complexity; may exceed smallest M1 scope. |

### Accepted M1 transaction direction

For M1, use this ordering:

1. write object;
2. verify actual size/checksum;
3. commit `storage_reference` and retained state.

If the database commit fails, attempt best-effort deletion of the newly written object and record/log orphan cleanup failure. Do not introduce staging database states or distributed transactions in M1. Staging/finalization may be required later for real production data, retries, and multi-instance execution.

## Testing strategy

Future tests should include:

### Unit tests

- local `put`/`get`/`delete`/`exists`;
- path traversal protection;
- atomic write behavior with temporary files;
- checksum and byte-size calculation;
- missing object errors;
- duplicate key behavior;
- failure cleanup;
- temporary directory isolation.

### Integration tests

- upload integration for original TXT/PDF retention;
- Reader compatibility for TXT content and PDF content;
- original source retention state and storage reference population;
- no provider path leakage in public responses;
- delete behavior after authorized business path calls Storage.

### Architecture regression tests

- production upload/source paths do not use direct local path deletion for retained Source objects;
- provider-specific paths do not leak into schemas/responses beyond legacy compatibility fields;
- Storage remains independent of `Document` type and Reader semantics.

### Future provider contract tests

- same behavior across Local, S3, and R2 providers when those providers exist.

Do not modify CI in this PR.

## Provider contract testing

A future provider contract suite should run the same behavioral tests against:

- Local provider;
- future S3 provider;
- future R2 provider.

Provider parity matters because business code must not depend on local filesystem behavior such as absolute paths, immediate directory listing, path separators, or unlink semantics. Contract tests should define Atlas storage behavior, not mirror any one cloud SDK.

## Security considerations

Security considerations include:

- path traversal and absolute path injection;
- unsafe filenames and trusting original filenames as keys;
- MIME type trust and content sniffing limitations;
- checksum integrity and corruption detection;
- secret isolation from database rows and public APIs;
- unauthorized deletion of source evidence;
- object reference guessing if references are exposed;
- future user/tenant isolation;
- executable content stored as opaque bytes;
- malicious uploads that exploit parsers during processing.

This is not a security implementation task.

## Observability

Future observability may include structured operation logs for:

- operation name;
- object key/reference;
- provider;
- operation duration;
- byte count;
- failure category;
- correlation/document ID where appropriate.

Logs must not expose secrets, credentials, raw sensitive content, or unnecessary original filenames. Observability should help diagnose mechanics without turning provider details into public contracts.

## Alternatives considered

| Alternative | Assessment | Status |
|---|---|---|
| Continue direct filesystem access | Lowest immediate effort but preserves path coupling, provider leakage risk, and source retention gap. | Rejected as target architecture. |
| Add helper functions only | Reduces duplication but does not create a provider boundary or contract. | Rejected for Storage Adapter goal. |
| Introduce a small Storage Adapter | Creates the smallest useful boundary while preserving current behavior. | Accepted direction, implementation pending confirmation. |
| Adopt a full object-storage framework/library | May solve many future features, but adds dependency and design weight before current needs require it. | Deferred/rejected for M1. |
| Move all BLOBs immediately | Aligns with long-term object storage but risks Reader/OCR compatibility and requires broad migration. | Deferred. |

## Recommended architecture

```text
Business Service / Ingestion Policy
        │
        │ authorized write/read/delete request
        ▼
Storage Adapter
        │
   ┌────┴────┐
   │         │
Local     Future Cloud
Provider  Provider
```

Business policy remains outside Storage. Storage hides mechanics and returns provider-independent references/metadata to business services.

## Proposed implementation sequence

Recommended small PR sequence:

1. Add storage interface/value types and Local provider.
2. Add focused provider contract tests.
3. Retain original TXT/PDF using Local provider.
4. Populate `SourceFile.storage_reference` and retained state according to accepted M1 source-retention scope.
5. Preserve Reader compatibility.
6. Verify cleanup/error behavior.
7. Defer DB blob migration.

Interface/provider and upload integration should preferably be separate PRs if review bandwidth allows. A combined PR may be acceptable only if it remains narrow: local provider plus original source retention, no DB blob migration, no public API changes, and explicit compatibility tests.

## Open questions

1. What exact encoded string syntax should the opaque logical reference use?
2. What final object key namespace/path pattern should be used internally by the Local provider?
3. Should `SourceFile.retained=0` distinguish never retained, retention failed, policy-deleted, and external-reference-only?
4. Should upload integration and storage interface/provider land in one PR or two?
5. What user/admin/compliance actor may authorize deletion of retained sources?
6. Where exactly should factory, dependency, and injected source-retention functions live?

## Non-goals

This document does not implement Storage. It does not add an adapter, provider, interface, class, API, model field, migration, dependency, CI job, lifecycle worker, cloud integration, encryption, compression, deduplication, signed URL support, or runtime behavior change.

## Decision table

| Decision | Status | Notes |
|---|---|---|
| Storage Adapter as infrastructure boundary | Accepted direction | Implementation requires future task approval. |
| Storage independent of business meaning | Accepted | Storage knows objects and bytes; Business knows meaning and policy. |
| Opaque logical reference | Accepted for v1 design | Business/application callers must not parse it; no provider mechanics or paths may leak. |
| No v1 mapping registry | Accepted | Local provider may derive an internal key from the logical ID behind Storage. |
| Generated immutable object IDs | Accepted | Collision-safe, non-sensitive IDs; original filenames remain provenance metadata. |
| Source create-only / checksum-idempotent retry | Accepted direction | Same checksum may be retry; different bytes/checksum must fail; silent overwrite prohibited. |
| `put`/`get`/`delete`/`exists` | Accepted v1 set | `put` returns stable reference, byte size, and SHA-256 checksum. |
| `stat`/`head` | Deferred | Not required in v1 because `put` returns actual mechanical metadata. |
| `list`/`copy`/`move`/`generate_url`/streaming open | Deferred | Not needed for M1 source retention. |
| Bytes-first with additive future streams | Accepted | Large PDF/audio/video support requires separate design review. |
| Sync core | Accepted for v1 | Async route call sites own future thread-offloading decisions; no fake async blocking methods. |
| Mechanical size/SHA-256 returned by `put` | Accepted | Caller-supplied expected values are verified when provided. |
| Local provider first | Accepted for M1 implementation direction | Conceptual only in this PR; no provider implemented. |
| Factory + FastAPI dependency + explicit injection | Accepted direction | No import-time global provider construction with filesystem side effects. |
| Original TXT/PDF retention only | Accepted M1 implementation scope | Scope 1; retain original uploaded source bytes first. |
| Processed TXT migration | Deferred | `output/` remains intentional transitional compatibility boundary. |
| DB BLOB/OCR/MinerU migration | Deferred | Keep `PdfPage`, `BookImage`, OCR JSON, and MinerU JSON unchanged for compatibility. |
| Object-first then metadata commit | Accepted M1 transaction direction | Write object, verify metadata, then commit `storage_reference`/retained state. |
| Staging transaction state | Deferred | May be needed later for production data, retries, and multi-instance execution. |
| Business-authorized source deletion | Accepted boundary | Storage executes mechanics; retained Source deletion must route through business/source-retention service. |
| Exact actor/permission model | Deferred | User/admin/compliance authority remains future policy work. |
| Cloud providers | Deferred | S3/R2/Azure/etc. out of scope. |
| Exact method signatures/classes/config names/key namespace | Pending implementation review | No interfaces, provider classes, config names, or final namespace are authorized here. |

## M1-003D implementation notes

M1-003D implements the accepted v1 boundary in `app/storage/` with a synchronous bytes-first protocol, provider-independent errors, `StorageReference`, `PutResult`, a settings-backed factory, a FastAPI dependency, and a Local filesystem provider. The only migrated production path is original uploaded TXT/PDF source retention.

The implemented opaque logical reference format is `src_<32 lowercase hex uuid characters>`, for example `src_0123456789abcdef0123456789abcdef`. The value is generated internally, contains no absolute path, provider name, bucket, credential, or user filename, and callers must treat it as opaque. The Local provider resolves the reference without a mapping registry by validating the full reference and deriving a sharded object path below the configured root from the generated identifier. That derivation is provider mechanics, not business meaning.

Local `put` computes and returns the actual byte size and SHA-256 checksum. Expected size/checksum mismatches raise `IntegrityMismatch` before publication. Writes are create-only: the same reference and same bytes/checksum are accepted as an idempotent retry, while different bytes for an existing reference raise `ObjectAlreadyExists`. Temporary files are created in the final directory, flushed/closed, then atomically published with atomic create-only `os.link` followed by temp cleanup; fsync is intentionally omitted for M1 because the durability posture matches existing local filesystem behavior and focuses on atomic visibility rather than crash-consistency guarantees.

Reference validation rejects traversal, absolute paths, Windows drive/UNC-style strings, empty references, and invalid characters by accepting only the generated `src_<uuidhex>` shape. The provider resolves paths under one configured root and fails closed on object/destination symlink conditions. It never returns absolute local paths.

Storage is constructed by `create_storage_provider(settings)` using `storage_root` and injected into FastAPI routes through `get_storage_provider`, allowing tests to override with a temp-root Local provider. No provider singleton is constructed at import time. The current Hugging Face Space is intentionally test-only and has no Persistent Storage configured; the default Local provider therefore writes to ephemeral container storage that may be lost with SQLite data during rebuilds. This is acceptable only for the disposable test deployment. Production deployment must use persistent mounted storage or a durable provider before accepting real user data.
