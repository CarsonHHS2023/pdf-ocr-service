# Atlas Document Processing Contract

| Field | Value |
|---|---|
| Document Type | Architecture Contract |
| Authority Domain | Document Processing architecture boundaries for transforming retained Sources into Raw Processing Result and Structured Processing Result |
| Applies To | Document Processing layer; `paddle-vl-api`; future OCR providers; future document-analysis providers; MinerU-Popo; future normalization engines |

## Status

Documentation-only architecture contract for **M2-001 Atlas Document Processing Contract**.

This document is the canonical M2 reference for the Atlas Document Processing layer. It defines architecture boundaries only. It does not define production code, APIs, database models, Alembic migrations, CI behavior, dependencies, runtime behavior, or implementation details.

## Relationship to the Atlas Shared Platform Blueprint

This contract expands only the **Document Processing** portion of the [Atlas Shared Platform Blueprint](persistence-processing-foundation.md#atlas-shared-platform-blueprint).

The Blueprint remains the canonical cross-milestone reference for how Storage, Document Processing, Structured Content, Applications, and Presentation relate to each other. This document must not redefine Storage, Structured Content, Applications, or Presentation. It narrows the processing contract for transforming retained Sources into Raw Processing Result and handing off to the M3 Structured Processing Result normalization boundary.

## 1. Purpose

The mission of Document Processing is to transform retained document Sources into Raw Processing Result and Structured Processing Result.

Document Processing starts from a retained SourceFile/business association, accepts retained source bytes through the Storage boundary, invokes a processing capability, captures provider results, normalizes those results, and emits provider-independent Structured Processing Result output for the next Atlas layer.

Document Processing is provider-independent, application-independent, and implementation-independent. The contract applies to current and future participants, including:

- `paddle-vl-api`;
- future OCR providers;
- future document-analysis providers;
- MinerU-Popo;
- future normalization engines.

Document Processing does **not** define:

- canonical Structured Content;
- Presentation;
- Reader behavior;
- Smart Archive behavior;
- Knowledge schemas;
- application-specific data models.

Those responsibilities belong to downstream milestones and application layers.

## 2. Processing Pipeline

### Target architecture

```text
Retained Source
        ↓
Storage.get()
        ↓
Processing Provider
        ↓
Raw Processing Result
        ↓
Normalization
        ↓
Structured Processing Result (SPR)
        ↓
M4 Structured Content / Structured Document
        ↓
derived presentation/application projections
```

The target architecture keeps every boundary explicit:

1. retained Sources remain owned by Storage;
2. processing providers produce provider-specific Raw Processing Results;
3. normalization converts provider-specific results into Atlas-owned Structured Processing Result;
4. M3 ends at provider-independent SPR, which remains noncanonical;
5. M4 owns content assembly/canonicalization decisions for Structured Content / Structured Document;
6. derived presentation/application projections feed Reader and downstream product behavior.

### Current transitional implementation

The current local OCR-oriented implementation is transitional. It may perform source access, OCR execution, result shaping, and application-facing output close together in one local path. That shape is useful for early validation, but it is not the M2 target contract.

Transitional behavior must not become the long-term architecture. In particular, provider-specific OCR/layout output, local filesystem assumptions, and reader-facing formats must not become stable Atlas contracts.

### Target boundary

The target architecture separates retrieval, provider execution, raw result capture, normalization, and downstream content ownership. This separation allows Atlas to replace providers, add document-analysis capabilities, improve normalization, and evolve Structured Content without forcing application changes.

## 3. Processing Stages

### Source Retrieval

- **Purpose:** Retrieve retained source bytes and required source metadata through the Storage boundary.
- **Input:** A retained SourceFile/business association, its opaque Storage reference, and authorization/context sufficient to request bytes from Storage.
- **Output:** Source bytes or a readable source stream plus retrieval metadata needed for processing provenance.
- **Owner:** Storage owns bytes and storage mechanics; Document Processing owns the request to retrieve bytes for a processing run.
- **Failure boundary:** Retrieval failures remain at the Storage/Processing boundary and include missing objects, denied access, unavailable storage providers, integrity failures, or unsupported source access.
- **Retry boundary:** Retrieval may be retried when failure is transient and retrying does not mutate source evidence or duplicate downstream outputs.

Source Retrieval must not dereference provider-specific filesystem paths directly, infer business meaning from Storage locations, or make Storage responsible for processing policy. Temporary files, rendered pages, page images, or page-range fragments created to transport bytes to a provider are processing implementation details. They must not become durable business Sources unless a future source-retention policy explicitly promotes them.

The contract supports both whole-file processing and page-range or batched processing. Page ranges are processing slices of a retained Source; they are not separate retained Sources by default.

### Processing Provider

- **Purpose:** Analyze source bytes with an OCR, layout, document-analysis, or equivalent processing capability.
- **Input:** Retrieved source bytes or stream, processing options, provider version/capability expectations, request/correlation identity, idempotency context, and processing context.
- **Output:** A provider-specific result, provider job/result reference, provider status, or provider-specific failure.
- **Owner:** The provider owns execution semantics and provider-native output. Document Processing owns provider selection boundaries, invocation policy, provenance capture, and interpretation of provider completion or failure.
- **Failure boundary:** Provider failures include submission failures, validation errors, unsupported formats, provider timeouts, execution errors, cancellation, provider unavailability, quota/rate constraints, and provider-specific internal failures.
- **Retry boundary:** Provider invocation may be retried only when the retry is safe for the processing run, respects request identity/idempotency rules, does not overwrite a successful prior attempt, and does not imply that provider-native results are canonical Atlas data.

### Raw Result

- **Purpose:** Capture the provider-specific output exactly enough to support normalization, debugging, provenance, and policy-based retention.
- **Input:** Provider-native processing result and provider metadata.
- **Output:** Raw Processing Result associated with a specific processing attempt or run.
- **Owner:** Document Processing owns ingestion and lifecycle policy for Raw Processing Results. The provider owns the native format semantics.
- **Failure boundary:** Raw result failures include result retrieval failures, malformed provider output, incomplete payloads, incompatible provider versions, missing metadata, or inability to retain/interrogate the raw result according to policy.
- **Retry boundary:** Raw result handling may be retried when the provider result can be safely re-read or re-requested. If the raw result is lost or unrecoverable, the provider stage may need a new processing attempt.

Raw results should be treated as immutable or version-identifiable once ingested. A later attempt may create a new raw result, but it must not silently overwrite a prior successful raw result or destroy provenance.

### Normalization

- **Purpose:** Convert provider-specific Raw Processing Results into Atlas-owned, provider-independent Structured Processing Result.
- **Input:** Raw Processing Result, provider metadata, source/provenance metadata, and normalization version/capability information.
- **Output:** Structured Processing Result suitable for downstream M4 content decisions.
- **Owner:** Document Processing owns the normalization contract. MinerU-Popo or an equivalent normalization engine may perform normalization work within that contract.
- **Failure boundary:** Normalization failures include unsupported raw result structure, inconsistent reading order, unrepaired layout relationships, invalid normalized output, or normalization engine failure.
- **Retry boundary:** Normalization may be retried from the same Raw Processing Result when deterministic or version-controlled normalization is possible. Reprocessing the source is only required when the raw result cannot support normalization.

Normalization is bounded to processing-output repair and provider cleanup. It must not decide canonical merge rules, long-lived content identity, knowledge truth, or presentation serialization.

### Structured Processing Result

- **Purpose:** Provide normalized, provider-independent processing output as the completed revised M3 boundary.
- **Input:** Successful normalization result plus provenance and version metadata.
- **Output:** Structured Processing Result for downstream M4 Structured Content / Structured Document decisions.
- **Owner:** M3 owns the provider-independent SPR contract and normalization boundary. M4 owns conversion, acceptance, lifecycle, and canonicalization decisions for Structured Content / Structured Document.
- **Failure boundary:** Output failures include invalid normalized structure, missing provenance, incompatible output version, or failure to persist/hand off the output according to the future implementation boundary.
- **Retry boundary:** Output creation may be retried from normalized state or from Raw Processing Result depending on the failure point and idempotency policy.

Structured Processing Result should be expressive enough to preserve order, structural type, text/content, hierarchy, tables, figures, formulas when available, source/page evidence, and processing provenance. This is a semantic minimum, not a final schema.

## 4. Provider Contract

The provider contract is the conceptual boundary between Atlas and a Processing Provider. It describes what Atlas must be able to ask for and understand without defining HTTP endpoints, JSON schemas, SDK interfaces, database tables, or implementation classes.

### Input

A Processing Provider receives source content and processing context. Conceptual input includes:

- source bytes or a source stream;
- declared source media type and source characteristics when known;
- whole-document, page-range, or batch processing scope when applicable;
- processing intent such as OCR, layout analysis, table extraction, figure detection, or document analysis;
- provider options selected by Atlas policy;
- request identity and idempotency/correlation context;
- correlation/provenance context needed to connect provider execution to an Atlas processing run.

### Output

A Processing Provider returns provider-native output. Conceptual output includes:

- extracted text or observations;
- layout information;
- page or region information;
- tables, figures, formulas, hierarchy, reading order, or other detected structures when supported;
- asynchronous job status, progress/counters, and result references when the provider operates asynchronously;
- provider confidence, warnings, or diagnostics when available;
- provider metadata needed for provenance and normalization.

### Errors

Provider errors must remain provider-boundary information until Atlas maps them into processing status. Errors may describe invalid input, unsupported source type, submission failure, provider unavailability, quota/rate constraints, timeout, cancellation, execution failure, partial result, result retrieval failure, or provider-specific validation failure.

### Timeout

Timeout is part of the provider contract. Atlas must be able to distinguish a provider timeout from a normalization failure, Storage failure, cancellation, retry exhaustion, or downstream persistence/handoff failure.

### Cancellation

Cancellation is part of the provider contract when supported by the provider execution mode. Atlas must be able to distinguish an intentional cancellation request or cancellation result from provider timeout, provider failure, normalization failure, and business Document status.

### Version

Provider identity and version must be captured conceptually so that Atlas can understand which provider capability produced a Raw Processing Result and which normalization logic is compatible with it.

### Capabilities

Capabilities describe what a provider can perform, such as supported MIME/document types, whole-document processing, page-range processing, batch processing, OCR/text extraction, layout detection, table extraction, figure extraction, formula extraction, hierarchy detection, reading-order support, handwriting recognition, language support, maximum size/pages, synchronous execution, or asynchronous execution. Capabilities guide provider selection and validation but do not define application behavior.

### Provider metadata

Provider metadata includes provider identity, model or engine version, execution mode, capability set, configuration summary, request identifiers, job identifiers, result identifiers, warnings, and timing/provenance details when available. Metadata supports traceability and normalization; it is not itself canonical Structured Content.

## 5. Raw Processing Result

Raw Processing Result represents the provider-specific result returned by a Processing Provider before Atlas normalization.

It is:

- provider-specific;
- immutable or version-identifiable as received;
- useful for normalization, diagnostics, reproducibility, and provenance;
- associated with a processing attempt or run;
- traceable to source, provider, model/version, configuration, request/job/result identifiers when available, and processing attempt;
- potentially retained temporarily or persistently depending on policy.

It is **not**:

- canonical;
- application data;
- Structured Content;
- Presentation;
- a stable contract for Reader, Smart Archive, or Knowledge features.

Atlas must prevent Raw Processing Result formats from leaking into application contracts. If a future provider changes its native output, normalization should absorb that provider change without requiring application-layer changes.

## 6. Normalization

Normalization converts Raw Processing Results into an Atlas-owned processing shape that is independent of any one provider.

MinerU-Popo, or an equivalent normalization engine, is responsible for work such as:

- reading order normalization;
- hierarchy normalization;
- table normalization;
- figure normalization;
- metadata normalization;
- cross-page repair;
- formula normalization when provider output includes formulas;
- provider cleanup;
- removal or isolation of provider-specific artifacts that should not reach downstream contracts.

Normalization may enrich structure enough for downstream content construction, but it still does **not** produce canonical Structured Content. M4 owns Structured Content / Structured Document, evidence-linkage use, content lifecycle, projection decisions, and shared durable content semantics.

## 7. Structured Processing Result

Structured Processing Result is the provider-independent output of the completed revised M3 boundary. Historical wording in this document treated normalized processing output as an M2/M3 handoff; Roadmap v3 now names the normalized boundary SPR and places it at M3 completion.

It is:

- normalized;
- provider-independent;
- processing output;
- ordered and structurally expressive;
- provenance-aware;
- evidence-capable;
- an input to M4 Structured Content / Structured Document decisions.

Structured Processing Result represents what Document Processing can responsibly say after provider execution and normalization. It is stable enough for M4 ingestion, but it is not the final Atlas document content model.

It is **not yet**:

- canonical Structured Content;
- Knowledge;
- Presentation;
- Reader stream text;
- Markdown;
- provider raw JSON;
- MinerU-specific JSON as an application contract;
- Smart Archive records;
- application-specific view data.

At minimum, Structured Processing Result should be able to carry processing-level block or node identity, structural type, order, text/content, hierarchy, table/figure/formula references, source/page evidence, and processing provenance. M4 may transform, merge, version, canonicalize, or assign durable canonical identity to this information after an approved M4 lifecycle decision.

## 8. Processing Boundary Summary

| Stage | Responsibility |
|---|---|
| Provider execution | Provider lifecycle and provider-native response |
| Raw Processing Result | Retain provider-specific result/evidence |
| SPR normalization | Produce provider-independent normalized result |
| Content assembly/canonicalization | M4 decision and implementation boundary |
| Projection | Derived application delivery forms |
| Reader/product behavior | M5 and downstream milestones |

Provider adapters must not decide canonical application content. Processing normalization must not silently perform M4 canonicalization. Applications should not use provider payloads as product truth.

## 9. Processing Ownership

Ownership boundaries keep Atlas layers replaceable and prevent early processing details from becoming platform contracts.

| Layer | Owns | Does not own |
|---|---|---|
| Storage | Source bytes, storage provider mechanics, byte retrieval, and byte deletion according to policy. | Processing interpretation, provider-native output, Structured Content, or presentation. |
| Document Processing | Processing runs conceptually, provider invocation boundaries, ingested Raw Processing Results, normalization, processing provenance, and Structured Processing Result. Atlas owns any Raw Processing Result it chooses to retain durably after ingestion. | Source byte ownership, provider-owned temporary execution artifacts before ingestion, canonical Structured Content, Knowledge, Reader presentation, or Smart Archive workflows. |
| M4 Structured Content / Structured Document | Content assembly/canonicalization decisions, accepted/current content lifecycle, evidence-backed content semantics, content versioning when approved, durable shared document structure, and projection decisions. | Provider execution, raw provider payloads as application contracts, SPR normalization, or Reader/product behavior. |
| Projection | Derived application delivery forms such as Reader/API compatible streams and indexes. | Canonical content ownership or provider payload ownership. |
| Reader/product behavior | M5 and downstream milestone behavior: presentation, workflows, user interactions, reader experiences, study tools, archive views, and other product-specific experiences. | Source bytes, processing outputs, provider payloads as product truth, or canonical shared content ownership. |

## 10. Processing Lifecycle

The processing lifecycle describes processing-run status boundaries only. It does not define database schema, queue implementation, API shape, worker behavior, or orchestration mechanics.

- **Queued:** Atlas has accepted that processing should occur, but provider execution has not started.
- **Running:** Source retrieval, provider execution, raw result handling, normalization, or output handoff is in progress.
- **Succeeded:** Structured Processing Result is available for the downstream M4 boundary.
- **Failed:** Processing cannot complete without a new attempt, changed input, changed provider behavior, or operator/user intervention.
- **Cancelled:** Processing was intentionally stopped before completion; cancellation is distinct from provider failure and timeout.
- **Retry:** A new attempt or repeated boundary operation may occur according to future idempotency and retry rules.

Lifecycle states must identify the boundary at which failure or cancellation occurred: Source Retrieval, Processing Provider, Raw Result, Normalization, or Structured Processing Result.

This lifecycle must remain distinct from:

- business `Document` status;
- provider-native job status;
- normalization sub-status;
- final SPR output availability;
- M4 Structured Content / Structured Document publication/status lifecycle.

A future implementation may map these states together for compatibility, but this contract does not collapse them into one database field or one state machine.

## 11. Current vs Future

| Dimension | Current local OCR implementation | Future provider-independent architecture |
|---|---|---|
| Provider shape | Local PyMuPDF page rendering and local PaddleOCR-VL execution path. | Explicit Processing Provider boundary supporting `paddle-vl-api` and future providers. |
| Source access | May be coupled to local processing assumptions. | Source retrieval occurs through `Storage.get()` and Storage-owned byte mechanics. |
| Intermediate storage | `PdfPage` image BLOBs and per-page OCR JSON support the local path. | Temporary transport files or page batches are processing details, not durable business Sources by default. |
| Raw output | `PdfPage.ocr_raw_json` captures local OCR JSON. | Raw Processing Result remains provider-specific, attempt-scoped, and isolated from applications. |
| Normalization | MinerU-Popo writes `MineruResult.result_json` for current Reader compatibility. | MinerU-Popo or equivalent normalization produces provider-independent Structured Processing Result. |
| Application coupling | Reader compatibility output may depend on `MineruResult` today. | Applications consume M4 Structured Content / Structured Document through derived presentation/application projections, not provider output or SPR as canonical truth. |
| Architecture role | Transitional validation path. | Stable processing boundary reference for future implementation tasks. |

The current implementation is transitional because it helped validate document extraction locally before Atlas had a complete Storage, Processing, and Structured Content boundary. Future implementation should move toward the Roadmap v3 architecture without treating current local OCR output, provider JSON, SPR, or Reader compatibility output as canonical application content.

## 12. Deferred

This document explicitly defers implementation and schema decisions, including:

- `ProcessingRun` schema;
- Observation schema;
- job database;
- queue implementation;
- API definitions;
- worker implementation;
- cloud execution;
- provider selection;
- streaming;
- large-document optimization;
- final Structured Content / Structured Document schema;
- application presentation;
- persistence layout for Raw Processing Results;
- persistence layout for Structured Processing Result;
- retention policy for raw provider output, normalization output, structured processing output, logs/diagnostics, and temporary files;
- retry/idempotency algorithms;
- monitoring and alerting details.

These topics may be addressed by later processing or downstream tasks, but they are not defined here.

## 13. Role and Roadmap v3 relationship

This architecture-contract document is documentation only. It is not the accepted normative SPR contract; the versioned SPR contract remains [structured-processing-result-v1.md](../contracts/structured-processing-result-v1.md). Roadmap v3 and the M3 revised-scope completion establish that M3 ends at provider-independent SPR, which is noncanonical. M4 begins above SPR and owns Structured Content / Structured Document lifecycle, canonicalization, and projection decisions.

This document defines architecture boundaries only. It is the reference for reviewing whether future processing work preserves provider independence, application independence, implementation independence, Storage ownership, processing ownership, and the boundary between SPR normalization and M4 Structured Content / Structured Document. It does not authorize implementation, schemas, APIs, providers, deployment, release, or production readiness.
