# Content-Addressed Artifacts and Duplicate Document Reuse

| Field | Value |
|---|---|
| Document Type | Storage / Reuse Design |
| Decision Status | Accepted target direction |
| Implementation Status | Planned phased adoption |
| Date | 2026-08-15 |
| Authority Domain | Physical object identity, artifact retention, duplicate-source handling, cross-user compute reuse, and reuse safety |
| Related Architecture | [Scalable Storage and Processing Architecture](../architecture/scalable-storage-and-processing-architecture.md) |
| Related Contract | [Processing Attempt and Artifact Manifest v1](../contracts/processing-attempt-and-artifact-manifest-v1.md) |
| Related Plan | [Scalable Processing Migration Plan](../plans/scalable-processing-migration-plan.md) |

## 1. Core distinction: physical content is not user ownership

Atlas must separate three identities that are easy to conflate:

```text
Immutable physical source / artifact
        -> reusable processing result
        -> user-owned Document / application state
```

Two users may upload byte-identical files. Atlas may store the physical bytes once and compute the immutable processing result once, while each user retains an independent Document, ProcessingRun/provenance record, Reader state, permissions, notes, progress, and later user-specific intelligence.

Object reuse must never imply cross-user authorization.

## 2. Exact source identity — L0 deduplication

The first and highest-confidence deduplication layer is the SHA-256 of the complete source bytes:

```text
source_sha256 = SHA256(source_bytes)
```

Filename, upload date, and user-supplied title are not part of physical source identity.

Example:

```text
User A uploads X.pdf -> SHA256 ABC...
User B uploads Y.pdf -> SHA256 ABC...
```

The system may store one physical object and create two business records that reference it.

Target object layout may be content-addressed, for example:

```text
objects/sha256/ab/abcdef...
```

The exact provider path is not a business contract; the immutable checksum is.

## 3. Source dedupe rules

For an exact SHA-256 match:

- do not store a second identical physical source object unless provider constraints require it;
- create a distinct SourceFile/business association for the new user/document;
- verify media type/size and the complete uploaded bytes before cross-user reuse;
- preserve original filename only as user/document metadata, not object identity;
- do not reveal whether another user caused the object to exist.

### 3.1 Cross-tenant privacy boundary

A client-submitted SHA-256 is not sufficient proof that the client possesses the file. Atlas must not implement an endpoint that effectively says “this exact private file already exists for another user” or grants access solely because the caller knows a hash.

Initial implementation should therefore verify the actual uploaded bytes before cross-user physical dedupe. If upload-bandwidth optimization later becomes important, use an explicit proof-of-possession protocol or equivalent authorization-safe mechanism before skipping upload bytes.

The user-facing response must not distinguish “new object stored” from “existing object reused” unless the reused object is already owned/visible to that same user.

## 4. Processing identity — cross-user compute reuse

Exact source identity alone does not prove that an old processing result is compatible with the current pipeline. Atlas therefore defines a processing fingerprint conceptually as:

```text
processing_fingerprint = SHA256(
    source_sha256
    + pipeline_contract_version
    + normalized_processing_options
    + processor/model/prompt versions that affect output
)
```

The exact canonical serialization is defined by the versioned processing contract and must be deterministic.

The fingerprint must not include user identity when the compute result is tenant-neutral and safe to share.

## 5. Reuse decision

For a requested compatible fingerprint:

```text
existing artifact set status = succeeded
    -> verify required artifacts
    -> reuse immutable artifact set
    -> create this user's own logical ProcessingRun/result linkage

existing compatible computation = active
    -> join single-flight computation
    -> do not start duplicate CPU/GPU work

existing compatible attempt = retryable failure
    -> new attempt may compute/recover missing work

existing failure = deterministic invalid input
    -> do not repeatedly burn compute until input/pipeline changes

no compatible fingerprint
    -> new processing attempt
```

A reused user-visible run should record that compute was reused and the artifact-set identity it consumed. Reuse is provenance, not invisibility.

## 6. Single-flight / request coalescing

If users A and B submit the same processing fingerprint while A's compute is still running, only one compatible compute flight should run.

```text
              shared compute flight
                     P789
                   /      \
             Run A          Run B
          user-owned     user-owned
```

The active-compute claim must be durable enough to survive ordinary backend concurrency and must use database-enforced or transactional uniqueness/locking semantics rather than process-local Python state alone.

A failed callback or restarted web process must not cause a second expensive computation if the first computation can still be reconciled.

## 7. Processing Artifact Set

Reusable compute output is modeled as an immutable artifact set described by a manifest. It may contain:

- OCR/result shards;
- normalized provider results;
- SPR;
- visual assets;
- page-routing information;
- recovery metadata;
- the final immutable manifest and checksums.

The artifact set is system-level compute output, not owned by User A merely because A caused it to be produced first.

User-owned Documents and ProcessingRuns reference or materialize from this shared immutable result according to access/business policy.

## 8. Version changes invalidate incompatible reuse

A source processed with pipeline version V17 is not automatically reused for V18.

```text
source ABC + V17/options -> fingerprint P1
source ABC + V18/options -> fingerprint P2
```

Likewise, options that materially affect semantic output must participate in the fingerprint. Examples may include OCR model/version, prompt/contract version, language policy, preprocessing policy, or other output-affecting normalized parameters.

Do not include incidental execution properties such as transient container ID.

## 9. Higher-level duplicate detection

Exact binary SHA-256 is the first implementation level because it is deterministic and safe. Additional levels are optional optimizations and must not weaken evidence or provenance.

| Level | Meaning | Confidence/use | Reuse scope |
|---|---|---|---|
| L0 | Exact binary SHA-256 match | Exact | Source object and compatible full processing artifact set |
| L1 | Normalized PDF equivalence | High-confidence candidate | Full processing only after deterministic verification/page mapping |
| L2 | Matching page-content fingerprints | Per-page | Reuse matching page work/shards, process changed pages |
| L3 | Same publication/edition/content | Semantic relationship | Metadata/semantic knowledge reuse; layout/bbox artifacts usually not blindly reusable |

### 9.1 L1 — normalized PDF fingerprint

Two PDF byte streams can differ only because of producer metadata, timestamps, object ordering, or compression. A future normalized PDF fingerprint may detect such equivalence. It must be deterministic, versioned, and conservative.

L1 should initially produce a reuse candidate that is verified against normalized page identity rather than silently treating arbitrary PDFs as identical.

### 9.2 L2 — page fingerprints and partial reuse

Page-level fingerprints permit partial reuse when a PDF changes only in a cover, inserted pages, or a small revision.

Example:

```text
A: aa bb cc dd
B: xx aa bb cc dd
```

A verified page mapping can reuse compatible page-level OCR/recovery artifacts for `aa..dd` while computing only `xx`.

Page fingerprints are especially valuable once OCR/result output is already sharded by deterministic page/range units.

### 9.3 L3 — publication / edition identity

A born-digital PDF and a scanned PDF may represent the same book but have different byte/page/render fingerprints. A later publication layer may use ISBN, title/author/edition metadata, normalized text similarity, heading/chapter structure, and other evidence to associate them.

This relationship must not cause blind reuse of coordinate-sensitive assets, page numbers, or bboxes.

## 10. Future shared ContentPackage

At small scale, each user Document may materialize its own selected SCv2 graph even when immutable upstream content is shared. At larger scale, many users uploading the same book could duplicate thousands of nodes/evidence/anchors in PostgreSQL.

If production measurements justify it, introduce a tenant-neutral immutable canonical `ContentPackage` (name provisional) referenced by user Documents:

```text
Artifact Set / SPR
       -> immutable ContentPackage
              |-- Document A / User A state
              |-- Document B / User B state
              `-- Document C / User C state
```

This is a later optimization, not an immediate schema rewrite. It requires explicit ownership, versioning, deletion, selection, and migration design before implementation.

## 11. Retention classes

Artifacts should carry an explicit retention class rather than relying only on path conventions.

| Tier | Role | Typical examples | Lifecycle |
|---|---|---|---|
| T0 Canonical/long-lived | Required durable evidence/application artifact | source, SPR, selected Reader assets, final manifest | Reference/policy governed |
| T1 Recovery | Enables partial retry/reconstruction | OCR shards, page routing, intermediate normalized results | Bounded retention after success; longer on failure if useful |
| T2 Diagnostic | Debug/acceptance evidence | OpenCV rejected candidate, histograms, debug renders | Short TTL/policy |
| T3 Scratch | Execution-only | range PDF, temporary raster, masks | Delete after attempt; never canonical |

Exact retention windows remain policy/configuration decisions and should be backed by cost/recovery evidence.

## 12. Reference-aware garbage collection

Content-addressed sharing makes naive “delete user's Document -> delete object” unsafe. Physical deletion must consider all live references and retention policy.

Target deletion sequence:

```text
remove/expire business reference
    -> determine whether artifact has remaining live references
    -> check retention/legal/recovery policy
    -> mark GC eligible
    -> asynchronous delete
    -> audit success/failure
```

Reference counts may be explicit or derived from an artifact-reference index, but deletion must fail safe. Shared source/artifact bytes must not disappear because one user deletes their logical Document.

## 13. Integrity rules

- Same content-addressed key + same checksum: reuse is allowed.
- Same logical/content-addressed key + different checksum: hard integrity error.
- A manifest may reference only immutable artifacts whose checksum/size can be validated.
- DB success must not be committed before required artifacts are durable and validated.
- Object existence alone does not confer authorization.
- User ownership must be checked at the business layer before artifact delivery.

## 14. Implementation sequence

The implementation order is intentionally conservative:

1. exact server-verified source SHA-256 and content-addressed object identity;
2. processing fingerprint contract;
3. durable cross-user compatible-result lookup;
4. single-flight active-compute coalescing;
5. immutable reusable artifact manifest/set;
6. reference-aware retention/GC;
7. page-level fingerprints and partial reuse if metrics justify it;
8. publication/edition identity and shared ContentPackage only after real scale evidence.

The implementation plan and acceptance gates are defined in [Scalable Processing Migration Plan](../plans/scalable-processing-migration-plan.md).
