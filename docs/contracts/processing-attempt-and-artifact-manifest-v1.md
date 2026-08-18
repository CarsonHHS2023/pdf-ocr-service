# Processing Attempt and Artifact Manifest Contract v1

| Field | Value |
|---|---|
| Document Type | Proposed Contract |
| Contract Version | v1 |
| Approval Status | Accepted for phased implementation; runtime conformance not yet claimed |
| Date | 2026-08-15 |
| Authority Domain | Durable processing-attempt identity, idempotency, artifact descriptors, compute completion, retry/reuse, and Backend/Modal handoff |
| Related Architecture | [Scalable Storage and Processing Architecture](../architecture/scalable-storage-and-processing-architecture.md) |
| Related Storage Design | [Content-Addressed Artifacts and Document Reuse](../storage/content-addressed-artifacts-and-document-reuse.md) |
| Related Plan | [Scalable Processing Migration Plan](../plans/scalable-processing-migration-plan.md) |

## 1. Purpose

This contract defines the stable control/data boundary required to move Atlas processing into an elastic compute plane without making process memory, Modal job state, or large HTTP payloads authoritative.

The contract separates:

- **execution identity** — one processing attempt;
- **compatibility identity** — whether an existing computation can be reused;
- **artifact identity** — immutable bytes and their checksums;
- **business identity** — Document, SourceFile, candidate, selection, user/tenant ownership.

## 2. Processing attempt identity

Every processing execution has a globally unique immutable `processing_attempt_id`.

Target invariant:

```text
processing_attempt_id == ProcessingRun.processing_run_id
```

The durable ProcessingRun must be created before expensive remote compute is submitted.

The attempt ID is a correlation/provenance identity. It is not an artifact-content key and must not prevent reuse of identical immutable artifacts across attempts.

## 3. Processing fingerprint

A deterministic `processing_fingerprint` identifies compatible tenant-neutral compute:

```text
SHA256(canonical_json({
  source_sha256,
  pipeline_contract_version,
  normalized_options,
  output_affecting_processor_versions
}))
```

### 3.1 Required properties

- deterministic canonical serialization;
- independent of filename, user identity, timestamps, container IDs, transient URLs, and attempt ID;
- includes every option/version that can materially alter reusable output;
- versioned so fingerprint rules can evolve safely;
- persisted or reconstructable for lookup/audit.

### 3.2 Example output-affecting version inputs

Depending on the active pipeline, these may include:

- preprocessing policy/version;
- OCR model/version;
- structure-recovery contract/version;
- structure-refinement prompt/model version;
- asset-generation policy/version;
- SPR schema/contract version.

Infrastructure-only changes that provably do not affect outputs need not invalidate reuse.

## 4. Durable attempt state machine

The control plane owns durable state. Minimum target states:

```text
queued
  -> submitted
  -> processing
  -> artifacts_ready
  -> canonicalizing
  -> succeeded

terminal/error alternatives:
  -> failed_retryable
  -> failed_terminal
  -> cancelled
```

Implementation may map these onto existing bounded status fields during migration, but semantics must remain explicit.

### 4.1 State rules

- `queued`: durable run exists; compute not yet confirmed submitted.
- `submitted`: a compute request/handle has been accepted or deterministically recoverable.
- `processing`: compute is active or expected active.
- `artifacts_ready`: immutable completion descriptor/manifest is durable and ready for Backend validation.
- `canonicalizing`: Backend is validating/materializing business content.
- `succeeded`: required artifacts validated and business transaction committed.
- `failed_retryable`: transient/infrastructure/provider failure permits a new attempt or partial retry.
- `failed_terminal`: input/policy/contract failure should not automatically repeat unchanged work.

A Backend restart must be able to reconcile any nonterminal state without requiring the original Python task to survive.

## 5. Artifact descriptor

Every durable artifact referenced by a processing manifest uses a bounded descriptor conceptually equivalent to:

```json
{
  "artifact_ref": "opaque-or-content-addressed-reference",
  "role": "spr",
  "sha256": "...",
  "byte_size": 12345,
  "media_type": "application/json",
  "retention_class": "T0",
  "producer_step": "spr_builder",
  "producer_version": "...",
  "rebuildable": false,
  "page_range": null
}
```

### 5.1 Required descriptor invariants

- `artifact_ref` resolves through the configured object-storage abstraction;
- checksum and byte size describe the immutable stored bytes;
- `role` is controlled/versioned vocabulary, not a free-form security decision;
- artifact descriptors do not embed credentials or temporary signed URLs;
- a temporary URL may be produced separately at delivery time but is never durable identity;
- immutable artifacts are create-only or integrity-checked on collision.

## 6. Processing Artifact Manifest v1

The final manifest is immutable and contains enough information to validate/recover the attempt without reading process-local state.

Conceptual shape:

```json
{
  "schema_version": "atlas.processing-manifest.v1",
  "processing_attempt_id": "...",
  "processing_fingerprint": "...",
  "source": {
    "source_file_ref": "...",
    "artifact_ref": "...",
    "sha256": "...",
    "byte_size": 1234567,
    "media_type": "application/pdf"
  },
  "pipeline": {
    "contract_version": "...",
    "backend_source_revision": "...",
    "compute_source_revision": "...",
    "runtime_build": "...",
    "processor_versions": {}
  },
  "routing": {
    "page_count": 100,
    "native_text_pages": [],
    "presentation_pages": [],
    "ocr_pages": []
  },
  "artifacts": [],
  "spr": {
    "artifact_ref": "...",
    "sha256": "...",
    "byte_size": 0
  },
  "warnings": [],
  "completed_steps": [],
  "completed_at": "..."
}
```

The exact JSON schema is implemented and locked by contract tests in the phase that introduces runtime conformance. Until then this document governs semantics rather than claiming an already deployed wire shape.

## 7. Processing completion descriptor

The compute plane should return or publish a compact descriptor rather than the complete raw/SPR payload:

```json
{
  "processing_attempt_id": "...",
  "processing_fingerprint": "...",
  "status": "artifacts_ready",
  "manifest_ref": "...",
  "manifest_sha256": "...",
  "source_sha256": "...",
  "page_count": 100
}
```

The descriptor may be returned by API/callback and should also be recoverable durably, for example from an attempt-scoped completion object or deterministic lookup.

A callback is therefore an acceleration signal, not the sole source of completion truth.

## 8. Backend -> Compute submission contract

Submission should contain references and policy, not full source bytes:

```json
{
  "processing_attempt_id": "...",
  "processing_fingerprint": "...",
  "source": {
    "artifact_ref": "...",
    "sha256": "...",
    "byte_size": 1234567,
    "media_type": "application/pdf"
  },
  "pipeline_contract_version": "...",
  "normalized_options": {},
  "output_prefix_or_write_capability": "implementation-specific"
}
```

Security credentials/write capabilities are runtime secrets or short-lived capabilities and must not be persisted in the manifest.

## 9. Idempotent submission semantics

For the same request identity/fingerprint:

- compatible completed result: return/reuse completed artifact set;
- compatible active compute: return current handle/state and do not launch duplicate expensive work;
- retryable failure: permit a new attempt according to policy;
- same attempt ID with different source/fingerprint/options: reject as an identity conflict;
- same artifact key with a different checksum: reject as an integrity conflict.

The existing behavior of simply rejecting every duplicate active job is insufficient for the target multi-user/single-flight architecture. Runtime implementation should converge toward replay-safe idempotent semantics.

## 10. Shard contract

Large documents should support independently durable/retryable work units. A shard descriptor includes, at minimum:

- stable source identity;
- processing fingerprint or compatible stage fingerprint;
- deterministic page/range identity;
- stage/version;
- artifact checksum/size;
- completion status.

Example:

```text
ocr shard: pages 51-72
```

Retry must be able to compute only missing/invalid shards where stage semantics permit it.

Shard size is planner/resource driven, not required to be a fixed 50 pages.

## 11. Single-flight contract

The control plane must coordinate compatible concurrent requests so that a single compatible compute flight can serve multiple logical ProcessingRuns.

Required behavior:

1. compute fingerprint;
2. transactionally inspect/claim active compatible compute;
3. if an active compatible flight exists, attach the new logical run as a consumer;
4. otherwise create/claim the compute flight and submit it once;
5. all consumers independently finalize their business state from the immutable artifact set under their own authorization/ownership context.

The claim must not rely only on one web process's memory.

## 12. Reuse contract

Cross-user artifact reuse is permitted only for tenant-neutral immutable computation and only after the new user's source possession/bytes have been independently validated according to the storage security policy.

A reused ProcessingRun records at least:

- its own processing/run ID;
- source/business identity;
- processing fingerprint;
- reuse disposition (`reused_completed`, `joined_active`, or equivalent bounded value);
- reused artifact-manifest identity;
- finalization result.

It must not expose the identity of the user who first produced the artifact set.

## 13. Recovery/reconciliation contract

A reconciler can query durable nonterminal ProcessingRuns and decide:

```text
completion descriptor/manifest exists and validates
    -> continue finalization

compute is still active/recoverable
    -> leave/refresh state

partial shards exist
    -> resume missing work according to compute policy

compute lost and retryable
    -> submit a new attempt or recovery execution

terminal deterministic failure recorded
    -> fail without infinite retry
```

Reconciliation must be idempotent. Replaying it after success must not create duplicate candidates/selections or corrupt ProcessingRun history.

## 14. Backend finalization contract

Before marking a run succeeded, Backend must validate:

- attempt/fingerprint/source identity;
- manifest schema version;
- manifest checksum if referenced by descriptor;
- required artifact existence;
- required artifact checksum/size;
- allowed processor/contract version;
- SPR validation;
- expected document/source relationship;
- business authorization/selection policy.

Only after validation does Backend persist/materialize SCv2 and update selection/ProcessingRun state transactionally.

Modal must never promote or overwrite a user-owned/current selection.

## 15. Error classes

Runtime contracts should expose bounded machine-readable classes, at least distinguishing:

- invalid/unsupported input;
- integrity mismatch;
- contract/version mismatch;
- authorization/capability failure;
- object-store transient failure;
- compute capacity/transient failure;
- provider transient failure;
- provider terminal/rejected input;
- shard partial failure;
- finalization/persistence transient failure;
- finalization invariant failure.

Raw provider bodies, secrets, signed URLs, SQL, and document contents must not be placed in durable public status fields.

## 16. Conformance tests required before runtime claim

A runtime may claim v1 conformance only after automated tests cover:

- deterministic fingerprint serialization;
- same-attempt identity conflict rejection;
- exact artifact checksum/size validation;
- create-only object collision behavior;
- completed-result idempotent replay;
- active single-flight join;
- Backend restart reconciliation;
- lost callback recovery;
- partial shard retry;
- duplicate finalization safety;
- cross-user reuse without ownership leakage;
- manifest validation failure before DB success;
- Modal inability to mutate Neon business state through this contract.
