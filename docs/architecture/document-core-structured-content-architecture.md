# Atlas Document Core & Structured Content Architecture

| Field | Value |
|---|---|
| Document Type | Document-Core Structured Content Architecture |
| Approval Status | Proposed |
| Authority Domain | Conceptual structured-content hierarchy, evidence, provenance, and source-anchoring architecture |
| Implementation Status | Architecture proposal only; no schema, Contract, implementation, milestone-completion, or release authorization |

## Status

**State:** Proposed M3 architecture based on real M2 Raw Processing Result output.

- Architecture date: 2026-07-16; Atlas commit inspected: `aecdce156a67a741a5f503a9ddd0ad6893a48d96`.
- Provider reference commit: `3a790e3e4c0ececef316bd2ca5aa03d84f6c6159`; fixture-inventory provider implementation revision: `20b9ec9`.
- Evidence: [M2 controlled live-provider smoke result](../processing/controlled-live-provider-smoke-result.md) and [fixture analysis](../processing/paddle-vl-api-fixture-analysis.md). The smoke verified raw retention but did **not** capture its returned checksum or size.
- The provider reference was read-only and clean before/after this work. This documentation-only task made no runtime change, provider call, job submission, operator invocation, or private-result retrieval.

## Executive decision

The real M2 boundary is a retained Source plus a provider job/outcome and an immutable `RawProcessingResultEnvelope` whose exact payload is stored through an opaque `StorageReference`. M3's target is two distinct Atlas-owned layers: a provider-independent, rebuildable **Structured Processing Result** (SPR), then selected durable **Structured Content Version** (SCV). Canonical data starts only at a selected SCV; Reader and Archive consume SCV, approved Assets, and evidence metadata, never provider JSON.

The historical blueprint said M2 produces normalized output, but the implemented and live-tested path stops at raw retention. Recommend **Option B, with the normalization service treated as a shared technical sublayer**: formally scope Raw Result → SPR and SCV canonicalization into M3. This is a documented ownership correction, not a claim that M2 normalization exists.

## Current real M2 output

M2 currently provides retained source bytes, provider job/request identity and terminal status, a provider-independent raw envelope, opaque Raw Result storage location, provider/source provenance, artifact metadata, optional page summary, exact retained-payload SHA-256 and byte size, orchestration outcome, and temporary source-transport grant creation/revocation. The envelope distinguishes deterministic inline JSON from exact artifact bytes; it validates metadata and retains no unsafe transport metadata.

**Implemented and live-tested:** Source transport, asynchronous `paddle-vl-api` processing, polling/result retrieval, Raw Result retention, and grant revocation. **Not implemented:** MinerU-Popo normalization in the M2 path, SPR, durable `ProcessingRun`, durable observation records, SCV, or Reader publication. The smoke established `raw_result_retained`, but its transient operator evidence did not record Raw Result checksum, size, or StorageReference.

## Historical blueprint reconciliation

| Option | Milestone clarity / isolation | Persistence, retry, and testability | Risk | Assessment |
| --- | --- | --- | --- | --- |
| A — finish normalization in M2 | Preserves old wording, but extends a completed raw-ingestion path | Adds a new durable/fixture contract to a provider-integration milestone | Blurs evidence and canonical-transition ownership | Not recommended |
| B — M3 begins at normalization | Makes actual M2 end explicit; adapters remain provider-isolated | M3 can version, rebuild, persist, and fixture-test SPR with its content model | Requires an explicit roadmap correction | **Recommended** |
| C — shared normalization sublayer | Good technical boundary, but ambiguous milestone owner alone | Reusable service and future-provider support | Can become an ownerless layer | Adopt as B's implementation rule, not as separate ownership |

M2's earlier “normalized structured processing output” is now an intended-but-unimplemented downstream capability. M2 remains evidence ingestion; M3 owns the first Atlas interpretation and canonicalization boundary. Provider adapters only produce raw evidence; application layers do not normalize it.

## Layered information model

| Layer | Purpose / owner | Authority, durability, rebuildability, evidence | Location / lifecycle | Consumers / forbidden consumers |
| --- | --- | --- | --- | --- |
| Original Source | Submitted source; Document/Source ownership | Authoritative original; durable by retention policy; not rebuilt | SourceFile record + object storage | Processing; not Reader as parsed content |
| Raw Processing Result | Exact provider evidence; processing ingestion | Authoritative evidence, provider-specific, durable; never mutated or rebuilt | Raw envelope metadata + object storage bytes; retain/delete with evidence policy | Normalizers/audit; not Reader/Archive |
| ProcessingRun | Execution/provenance owner | Durable execution record; not canonical; may reference retained failure evidence | Relational lifecycle rows | Processing/audit; not applications as content |
| ProviderObservation | Direct provider assertion; provider-normalization boundary | Derived/indexed evidence, provider-specific; durable when retained; can be regenerated from raw as a new indexed version | Relational records plus optional provider-payload artifact | Normalizers/audit; not SCV or applications |
| NormalizedObservation | Atlas assertion produced from provider observations; normalization owner | Derived interpretation, provider-independent; durable with an SPR version; rebuildable from raw/provider observations | Relational records plus optional normalized-payload artifact | SPR/canonicalizer; not direct application business model |
| SPR | Atlas normalized interpretation; normalization owner | Provider-independent, versioned, durable as required; rebuildable from raw | Relational index + optional canonical JSON artifact | Canonicalizer/quality tools; not M4/M5 contract |
| SCV | Accepted shared document content; Document Core owner | Durable canonical candidate; immutable version, explicitly selected | Relational hierarchy/evidence + Assets | M4/M5/projections; not provider adapters |
| Application Projection | Reader/Archive-specific materialization; application owner | Derived, optional, rebuildable | Index/object store/cache | Owning application only; not canonical source |
| Presentation Cache | HTML/Markdown/thumbnails/rendered pages; presentation owner | Ephemeral derived data | Cache/object storage | UI only; never canonical |

## Raw Processing Result

A Raw Processing Result is immutable retained provider evidence: exact bytes, actual checksum and size, provider/result-profile/version metadata, provider job/request identity, Source identity/checksum, and Atlas attempt/correlation identity. It has no application semantics, Reader dependency, or in-place mutation. One Source or Document can have many Raw Results across attempts, retries, providers, profiles, or model/pipeline versions. Normally one completed run references one selected retained result, but a run may retain multiple evidence artifacts (for example inline result and separately retained provider artifact) only with explicit roles; retries are new runs/results.

## ProcessingRun boundary

`ProcessingRun` is conceptual durable execution/provenance state, not content. It needs an ID; Document and SourceFile IDs; attempt/correlation ID; provider and provider job/request IDs; requested profile/options; start/completion timestamps; terminal state; source checksum/version; provider/model/pipeline versions; Raw Result reference(s); normalization version; warnings/errors; and parent/retry/supersession relation. A Document has many runs; a failed run may retain evidence; success merely makes a result eligible for normalization and never selects canonical content automatically. Exact SQL columns are deferred to M3-002A.

## Observation boundary

`Observation` is a collective term only; persistence/design must say which of two layers is meant. A **ProviderObservation** is an evidence-backed provider assertion: provider block identity/type, provider coordinates and coordinate system, provider confidence/payload, source page/index mapping, direct Raw Result provenance, and provider-only fields when necessary. A **NormalizedObservation** is an Atlas assertion—normalized type, geometry and coordinate system, order/content, confidence, transformation provenance, and links to one or more ProviderObservations. Either can represent a page, region, text block, title candidate, paragraph, table, figure, formula, header/footer, language, warning, or reading-order edge; both have Atlas identities and rejected/superseded state.

| Choice | Benefit | Cost | Recommendation |
| --- | --- | --- | --- |
| Single flexible Observation | Fewer tables and an easy first migration | Provider fields can leak into normalized semantics | No |
| ProviderObservation + NormalizedObservation | Preserves exact-provider assertions separately from Atlas interpretation | More identity/linking work | **Yes**; use shared evidence-link conventions |

Provider observations are optional indexed interpretations of raw evidence, not substitutes for retained bytes. Normalized observations are provider-independent and belong to an SPR version. This separation permits future normalizer changes without rewriting provider assertions. It is a **contract distinction first**: M3-002A must decide whether initial persistence uses two tables, a shared table with an explicit immutable `layer` discriminator, or artifact-only provider observations with normalized relational links. No final SQL shape is required by this architecture.

## Structured Processing Result

SPR is the versioned output of provider-specific normalization, not canonical publication. It supports document/page order; normalized block types and coordinates; text; structured and rendered table references; figures/images; formulas; lists; headings/title alternatives; page metadata; reading-order edges; source-evidence links; warnings; partial output; normalization provenance; and explicit schema ID/version. It is provider-independent, deterministic where practical, rebuildable from Raw Result, and may retain alternatives/conflicts. It contains no Reader formatting or provider field names as its contract.

## Structured Content

An SCV is durable, application-independent accepted document content for M4/M5: `DocumentContentVersion`, hierarchical `ContentNode`s, semantic node type/role, ordered children, stable node IDs, text, Assets, evidence spans/page-region anchors, provenance, confidence/acceptance state, revision/supersession, canonical selection, and content schema version. Recommend multiple immutable candidate versions per Document, with one explicit canonical pointer per Document content lineage. A normalization result creates a **proposed** SCV only after validation; it is not automatically canonical merely because a provider run succeeded.

## Structured Processing Result versus Structured Content

| Dimension | SPR | SCV |
| --- | --- | --- |
| Owner / purpose | Normalization; provider-independent interpretation | Document Core; accepted shared content |
| Stability / durability | Versioned durable record/artifact; rebuildable from raw | Immutable durable version; retained as document history |
| Canonical status | Never canonical by itself | Candidate; one explicitly selected version is canonical |
| Alternatives/conflicts | Expected and retained | Resolved/accepted choices, with lineage to alternatives |
| Editing / correction | New normalizer output version | New content version, never mutation |
| Application dependency | None; not M4/M5 contract | Application-independent M4/M5 contract |
| Evidence | Detailed raw/observation links required | Links to selected SPR observations and raw evidence required |
| Versioning / deletion | Schema + normalizer versions; may rebuild after retention review | Content schema + document version; preserve canonical/superseded history by policy |

## Canonicalization boundary

Canonicalization creates an SCV from a specific SPR through deterministic mapping plus schema and quality validation. Initially recommend automatic *proposal* creation, and automatic canonical selection only for an explicitly approved low-risk policy with complete page mapping, required schema validity, no blocking warnings, and no existing user-corrected canonical version. Human review, correction, or explicit service selection can choose another candidate. “Canonical” means Atlas's selected shared content version for a Document, not absolute truth; it is evidence-traceable, replaceable only by explicit selection, and never silently overwritten by reprocessing.

## Evidence linkage

`ContentNode → SPR node/NormalizedObservation → ProviderObservation → Raw Processing Result → ProcessingRun → SourceFile/page/region`. Each durable semantic link records page **index** (zero-based source position where supplied) and page **number** (one-based human/source label where supplied) separately; region/coordinate-system/unit/page-dimension metadata; provider block ID only as provenance; normalized observation ID; raw reference identity; source checksum/version; role; excerpt/span; confidence; and transformation version. `StorageReference` remains byte-location mechanics, not evidence/business identity.

## Ordering model

Keep source-page order, provider-detected order, normalized order, canonical content order, and application order distinct. Use ordered parent-child hierarchy plus integer `sequence` for initial page and sibling serialization; retain explicit directed reading-order edges for ambiguity/cross-page flow. Use a stable sortable token/fractional key only when editing needs insertion without bulk renumbering. This supports hierarchy, cross-page paragraphs, tables/figures, deterministic serialization, and later edits without prematurely implementing collaborative ordering.

## Node identity

| Strategy | Result |
| --- | --- |
| Random immutable IDs | Stable within a version but weak automatic comparison |
| Content hashes | Change on edits and cannot carry semantic identity alone |
| Source-coordinate IDs | Leak provider/source layout and break on reprocessing |
| **Hybrid** | **Recommended:** random immutable node IDs, version-scoped; a separate lineage mapping/key and evidence anchors compare versions; new IDs only for genuine semantic splits/merges |

The hybrid survives projection regeneration, supports evidence and version comparison, avoids provider IDs, and does not make mutable text the identifier. A canonical node ID is stable only within its SCV; cross-version stability is represented by the explicit lineage relation, not by reusing an ID by assumption.

## Asset model

An **Asset** is business metadata/identity, media role, owning content/evidence relation, and source page/region anchors; an optional immutable **AssetVersion/Rendition** records a particular crop, structured payload, or rendering with media type, checksum, byte size, derivation/version, and StorageReference(s). Bytes live in object storage. A SourceFile is original input; Raw Result may reference provider-delivered bytes; observations/SPR identify source crops or structured table/formula payloads; SCV nodes reference approved Assets. Preserve original crop and derived renditions as distinct relationships. Tables support a structured representation and optional rendered asset, not image-only treatment; formulas likewise may retain source/structured notation and a rendered rendition. Thumbnails and Reader renditions are derived, access-controlled, rebuildable, and cleaned independently; canonical/source assets follow their owning evidence/content retention rules.

## Versioning model

Keep independent immutable axes: provider output/profile/build/model/pipeline version; Raw Result/provider-schema revision; SPR schema version; normalizer implementation version; SCV schema version; Document content version; and projection version. Records carry supersession and current/canonical pointers rather than one overloaded `version`. Reprocessing creates a new run/SPR and possibly proposed SCV; compatibility reads known prior schemas, migrations change durable canonical schema where necessary, rebuild recreates derived SPR/projections when raw evidence permits, and rollback selects an earlier accepted SCV. Projection versions become stale when their SCV changes.

## Persistence architecture

| System | Durable responsibility |
| --- | --- |
| Relational database | IDs, lifecycle, ordering, evidence links, canonical pointer, versions, metadata, quality states, searchable normalized fields |
| Object Storage | Source/Raw bytes, large SPR artifacts, crops, rendered tables, formula/other binaries |
| Search/index/cache | Full text, embeddings, Reader/Archive projections, HTML/Markdown, thumbnails—all rebuildable |

Do not embed large provider JSON in rows for convenience. Object paths are not business identity; durable business records own identity and access policy.

## Provider isolation

Adapters produce Raw Results; provider-specific normalizers consume them; SPR is Atlas provider-independent; SCV and applications never depend on `paddle-vl-api` fields. Provider IDs stay as provenance only. The same normalizer contract admits paddle-vl-api, another OCR/layout system, native digital-PDF parsing, text import, audio transcription, and web extraction without changing M4/M5.

## MinerU-Popo role

The existing `MineruPopoService` is legacy/transitional code, not the Atlas canonical model. It consumes ORM `PdfPage.ocr_raw_json` shaped around `parsing_res_list`, mutates/reconstructs blocks in memory, may crop images through the legacy image service, and returns a `MineruResult.result_json` array; optional `magic-pdf` is detected but its runner raises `NotImplementedError`. Fixture analysis says paddle-vl results require an explicit mapper before this input shape and does not prove direct compatibility. It is therefore neither production-ready for M2's retained Raw Result path nor an SPR contract. Recommend treating it as a replaceable, provider-specific normalization reference/adapter candidate in M3-001D, behind the new SPR contract—not as canonical content and not as a generic builder.

## Partial and conflicting results

Retain partial-failed evidence and warnings. SPR validation identifies missing/duplicate pages, invalid mappings, low confidence, alternate titles, conflicting reading orders, unstructured tables, image-without-crop, and OCR-versus-embedded-text disagreement as observations/candidates rather than silently choosing. Block canonical promotion for missing/invalid required page mapping, schema failure, or policy-defined severity; permit explicitly reviewed partial SCVs with clear coverage. Evidence retention never implies canonical publication.

## Quality and acceptance

Track completeness, page coverage/mapping validity, OCR/structural/reading-order confidence, warning count/severity, table/figure quality, language detection, and schema validity. No final scoring formula is chosen. Schema failure, invalid mapping, missing required coverage, or high-severity unresolved warnings may block promotion; other signals inform review/selection.

## Correction and reprocessing

Raw bytes never change. A normalizer fix makes a new SPR version; a user/system canonical correction creates a new SCV; links preserve ancestry. Reprocessing cannot silently replace user-corrected canonical content. Earlier selected versions remain selectable subject to retention.

## Deletion and retention

Source, Raw Result, ProcessingRun, observations, SPR, SCVs, Assets, and projections have separate policies. Source deletion must decide whether dependent evidence/content is deleted, tombstoned, or legally retained; Raw Result expiration at the provider is irrelevant once Atlas retention succeeds. Runs/observations remain audit evidence as policy permits; rebuildable SPR/projections and derived assets may be evicted/cleaned after orphan checks. Preserve selected/superseded SCVs and necessary evidence links according to legal/business decisions; do not set durations here.

## Application contracts

M4 Smart Reading OS and M5 Smart Archive may consume selected SCV, its evidence links, approved Assets, content/version metadata, and needed quality/provenance metadata. They must not consume paddle response JSON, job status, Raw Result URLs, provider block IDs as business IDs, temporary transport URLs, local storage paths, or Reader Stream Text as canonical content.

## API boundary implications

Future internal services are Raw Result and ProcessingRun repositories, normalization service, SPR repository, canonicalization service, Structured Content repository, Asset service, and application-projection builder. Raw ingestion/orchestration remains asynchronous in execution; normalization/canonicalization may run synchronously for bounded artifacts or asynchronously for large work, but expose durable versioned outcomes. This task defines no public routes.

## Security and privacy

Raw Results may contain full sensitive content and provider provenance. Apply per-document authorization, audit access/deletion, safe logging, and redaction; persist no credentials, signed URLs, transport tokens, or local paths. Derivatives/Assets/projections inherit document access policy and deletion controls. This proposal does not claim current production authorization is complete.

## Schema evolution

Use explicit namespaced schema IDs plus compatible integer/semantic versions at each SPR/SCV boundary. Adapters declare supported provider revision/profile shapes. Prefer additive/read-compatible changes; migrate durable SCV only where necessary, rebuild SPR/projections from retained raw evidence when possible, and invalidate projections on SCV schema/content changes. Keep adapters for older raw provider revisions until evidence-retention policy allows removal.

## Initial M3 scope

The smallest useful slice is: accept this architecture; define an SPR contract; inventory safe fixtures; implement a mocked paddle Raw Result mapper; define then implement SQLite-compatible ProcessingRun/Observation/evidence persistence; define SCV/canonicalization; implement a builder; then Asset/ordering linkage and independent retained-raw-to-SCV verification. Do not add Reader until the shared contract is stable.

## Proposed M3 task breakdown

| Task | Goal, inputs, outputs | Runtime / persistence / tests | Decisions, blockers, and explicit non-goals |
| --- | --- | --- | --- |
| **M3-001A** Architecture | This document; M2 code, fixtures, smoke evidence → accepted boundaries/decisions | Docs only; link/check validation | Human decisions below; no code, data access, or normalization |
| **M3-001B** SPR Contract | Architecture + fixture shapes → provider-independent schema and compatibility rules | Docs/contract fixtures only; schema serialization tests if agreed | Blocked by field/coordinate decisions; no provider call or persistence |
| **M3-001C** Raw inventory fixtures | Retained-safe fixture inventory → normalization fixture matrix and gaps | Fixture/docs changes only; validation tests | Need data/privacy approval for any new capture; no private live raw retrieval |
| **M3-001D** Provider normalizer | Raw envelope + fixtures → versioned paddle mapper to SPR | New service/tests; no canonical publication | Depends on 001B/C; no MinerU-Popo cutover, jobs, routes, or Reader |
| **M3-002A** Persistence design | SPR/evidence decisions → ProcessingRun/dual-observation/evidence model | Docs/design and migration plan tests | Blocks 002B; no final DB implementation |
| **M3-002B** Persistence models | Accepted 002A → relational models/migrations/repos | Runtime persistence + SQLite-compatible migration/tests | Depends on DB review; no public API or worker |
| **M3-003A** SCV/canonicalization contract | SPR + evidence model → node types, acceptance/selection contract | Docs/schema fixtures | Requires human selection policy; no user editor |
| **M3-003B** SCV builder | Valid SPR → proposed SCV with lineage | Builder/persistence/tests | Depends on 002B/003A; no Reader projection or auto-selection unless approved |
| **M3-004** Assets/order/evidence | SCV + source regions → assets, order, durable linkage | Storage metadata/persistence/tests | Depends on storage/retention decisions; no storage-provider rewrite |
| **M3-005** Independent verification | Retained safe fixture + persisted pipeline → auditable Raw→SCV proof | Mocked end-to-end tests, manual review of safe artifacts | Depends on prior tasks; no live provider/job/operator and no production-readiness claim |

## Human decisions required

| Decision | Recommendation | Blocking follow-up |
| --- | --- | --- |
| Normalization owner | Move M2 Raw→SPR ownership to M3 (Option B) | M3-001B |
| Observation split | Separate provider and normalized observations | M3-002A |
| SPR storage | Rows for index/relations plus versioned artifact for large payload | M3-002A/B |
| Initial promotion | Create proposals automatically; explicit canonical selection | M3-003A |
| Multiple SCVs | Yes, immutable competing/superseded versions | M3-003A |
| Initial node types | document, section, heading, paragraph, list, list-item, table, figure, formula, page-break, note | M3-003A |
| Ordering | Parent-child integer sequence plus explicit reading-order edges | M3-003A/M3-004 |
| Node identity | Hybrid random immutable IDs plus lineage/evidence anchors | M3-003A |
| Asset boundary | Metadata/relations in DB, bytes in Storage, derived renditions rebuildable | M3-004 |
| Schema versions | Namespaced schema ID + compatible integer versions | M3-001B/003A |
| User correction scope | Defer UI/editing; model immutable correction versions now | M3-003A |
| MinerU-Popo | Transitional first adapter/reference, not required canonical normalizer | M3-001D |
| Database compatibility | Start SQLite-compatible relational design while keeping PostgreSQL/object-store portability | M3-002A |

## Non-goals

This task does not normalize the live-smoke result, retrieve private raw bytes, implement MinerU-Popo, define final SQL tables, add migrations/APIs, publish Reader data/Stream Text, add search/embeddings/user editing, or declare production readiness.

## Decision summary

| Decision | Options | Recommendation | Evidence | Human confirmation required |
| --- | --- | --- | --- | --- |
| Actual M2 boundary | Raw only / normalized output | Raw Result retention only | M2 orchestration and smoke | No factual dispute; acknowledge roadmap correction |
| Normalization ownership | A / B / C | B, using C as technical sublayer | No M2 normalization exists | Yes — M3-001B |
| Observation model | Single / split | Split provider and normalized | Provider shapes differ from Atlas semantics | Yes — M3-002A |
| Canonicality | Automatic / proposal + selection | Proposal + explicit selection | Reprocessing/correction safety | Yes — M3-003A |
| Content versioning | One mutable / immutable many | Immutable many, one selected | Evidence/audit/rollback needs | Yes — M3-003A |
| Storage split | DB blobs / object storage + relations | Relations in DB, bytes in storage | Existing Storage Raw boundary | Yes — M3-002A/004 |
| MinerU-Popo | Canonical / transitional adapter | Transitional replaceable adapter | Current legacy ORM input and unimplemented magic-pdf runner | Yes — M3-001D |
