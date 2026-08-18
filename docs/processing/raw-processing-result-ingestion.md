# Raw Processing Result Ingestion

| Field | Value |
|---|---|
| Document Type | Ingestion Design |
| Authority Domain | Raw Processing Result intake, validation, provenance, Storage retention, and handoff boundaries |
| Applies To | Inline provider results, already-downloaded artifact bytes, `RawProcessingResultEnvelope`, Atlas Storage writes, provider provenance, ingestion metadata, and page summaries |

M2-003C adds the Atlas-owned boundary for retaining provider output after a provider adapter has already retrieved it. The flow remains:

```text
Provider Adapter -> Raw Processing Result Ingestion -> Atlas Transformation -> MinerU-Popo -> Structured Processing Output
```

This layer does **not** poll providers, call providers, normalize content, create database rows, or expose a public API schema. It accepts provider evidence supplied by orchestration, writes the exact retained payload through Atlas Storage, and returns a provider-independent envelope.

## Envelope

The retained envelope is modeled in `app.processing.raw_result` and contains:

- identity: Atlas processing attempt ID, correlation ID, Document ID, SourceFile ID, provider name, provider job ID, provider request ID, provider profile, and provider status;
- source provenance: source SHA-256, optional ETag, and optional media type; provider-reachable source URLs are not represented;
- provider provenance: build tag, model/pipeline versions, configuration, capabilities, timestamps, warnings, and errors when supplied;
- ingestion metadata: ingestion timestamp, payload media type, encoding, compression, size, SHA-256, Atlas Storage reference, evidence source type, optional artifact metadata, and optional page summary.

The final envelope stores metadata and the Atlas Storage reference only. Raw bytes are not retained in memory by the envelope.

## Inline JSON serialization

Inline provider results are serialized deterministically before checksumming or storage:

```python
json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
```

That means UTF-8 bytes, stable key ordering, compact separators, no ASCII escaping, and rejection of non-standard `NaN`/`Infinity` float values. The SHA-256 is calculated over the exact bytes written to Storage. Unserializable values are rejected and the input payload is not mutated.

## Artifact-byte handling

Artifact ingestion accepts bytes that were already downloaded by the provider client. The ingestion service does not download, decompress, recompress, or transform artifact bytes. Provider-supplied artifact size and SHA-256 metadata are verified when present, then Atlas records the actual size and SHA-256 of the exact bytes written to Storage. Media type, encoding, and compression metadata are preserved.

## Storage ownership

Raw provider evidence is stored as a derived processing object through the injected Atlas Storage provider. Business code does not construct local filesystem paths or provider-specific object keys. If a caller supplies an existing Storage reference, Storage create-only semantics allow an idempotent same-byte retry and reject conflicting bytes. Full ingestion-attempt idempotency remains an orchestration responsibility because this PR does not add database-backed ingestion records.

## Validation and errors

The ingestion boundary validates non-empty Atlas/provider identities, valid SHA-256 strings, non-negative sizes, non-blank profile/status values when supplied, exactly one operation-specific evidence payload, and safe metadata keys. Typed failures distinguish invalid envelope input, serialization failure, provider metadata mismatch, checksum mismatch, size mismatch, Storage write failure, Storage conflict, and unsafe metadata.

Error messages include safe diagnostics such as Atlas attempt ID, provider name, provider job ID, and expected/actual integrity metadata where appropriate. They do not include raw payloads, artifact bytes, bearer tokens, signed URLs, request headers, or source URLs.

## Security and privacy

The envelope intentionally has no field for provider artifact URLs, signed URLs, Authorization headers, request headers, or provider-reachable source URLs. Known unsafe metadata keys in provider provenance or artifact metadata are rejected recursively; the raw provider payload is not scanned or stripped so provider evidence is either persisted exactly as serialized or rejected before persistence by a narrow metadata validation rule. Raw provider payloads are preserved only as the payload bytes explicitly chosen for ingestion; no logs are emitted by this layer.

## Page summary

The envelope can carry a provider-independent page summary built from existing `ProcessingPageIdentity` values. It records observed page count, first/last page, missing pages, duplicate pages, whether the mapping is valid, and represented source ranges. It does not create M3 canonical evidence IDs or duplicate full page payloads.

## Transaction boundary

There is no database transaction in this PR. The current boundary is: write bytes to Storage, return the retained envelope, and let future orchestration decide how to persist business metadata. If later metadata persistence fails, orchestration must perform compensating cleanup or record orphan state. This operation is not a distributed transaction.

## Non-goals

This PR does not implement polling, retries, background workers, upload or Reader route integration, MinerU-Popo transformation, Structured Processing Output, database tables, migrations, retention cleanup, or streaming artifact ingestion. Large artifact bytes are currently accepted in memory; streaming is deferred to a later design.

## Next step

Evaluate `M2-003D Implement Non-Persistent Processing Orchestration` only after this ingestion boundary is independently verified.
