# Atlas Roadmap v2 Review

| Field | Value |
|---|---|
| Document Type | Roadmap Review |
| Authority Domain | Roadmap analysis, findings, and recommendations for human confirmation |
| Evidence Role | Roadmap dependency analysis and recommendation evidence |
| Review Status | Pending human confirmation |
| Implementation Status | Review only; does not authorize implementation, roadmap status changes, milestone status changes, release, delivery, or commercial commitments |

## Status

Proposed roadmap realignment pending human confirmation.

This review does not authorize milestone renaming, milestone renumbering,
implementation, roadmap status changes, milestone status changes, database
schema changes, API changes, dependency changes, deployment changes, or runtime
behavior changes. It records a dependency analysis and recommendations for human
approval.

Optional supporting file status: no standalone M1 roadmap-audit document is present in
this repository's current tree or reachable Git history. `docs/reviews/M1-003-review.md` is present
and was used with the canonical roadmap, milestone, architecture, product,
storage, database, and visible Git history.

## Objective

The objective is to align Atlas roadmap order with actual product and
architecture dependencies. The issue is not merely that milestone names are
inconvenient. The current roadmap places Structured Reader before the processing
and structured-content capabilities it depends on, so execution order risks
building application presentation before the content contract exists.

The review evaluates whether the roadmap should be reordered and renamed so that
implementation follows this dependency direction:

```text
Source and retained evidence
  ↓
Document processing
  ↓
Structured content
  ↓
Document Core / canonical content
  ↓
Application presentation
  ↓
Smart Reading OS / Smart Archive
```

## Product structure

Human-confirmed product structure:

```text
Atlas
├── Smart Reading OS
│   ├── Speed Reading
│   ├── Flashcards
│   ├── Mind Map
│   └── Notes
└── Smart Archive
```

Atlas is one Document Intelligence Platform with multiple applications. Smart
Reading OS and Smart Archive are peer applications that share one Atlas Document
Intelligence Core. They must not be described as separate platforms.

Key product implications:

- both applications share one Document Intelligence Core;
- Stream Text is only one presentation format;
- Speed Reading is only one feature of Smart Reading OS;
- Smart Archive is a peer application, not an extension of Reader;
- future applications may share the same core without creating separate document
  systems.

## Current roadmap

The current canonical roadmap records this order exactly:

- M1 Foundation
- M2 Structured Reader
- M3 Document Core
- M4 OCR Integration
- M5 Archive Intelligence

### Current M1 Foundation

- **Intended purpose**: establish engineering governance, workflow,
  repository conventions, migration foundation, API regression posture, storage
  abstraction, original source retention, and compatibility-safe
  Document/SourceFile baseline.
- **Likely inputs**: current FastAPI service, current Reader API contract,
  existing SQLAlchemy models, current storage paths, roadmap documents,
  architecture principles, and CI constraints.
- **Likely outputs**: engineering foundation, Alembic baseline, Document and
  SourceFile foundation, Storage Adapter, Local provider, retained original
  TXT/PDF sources, and closeout evidence.
- **Dependencies**: existing service behavior, reader compatibility constraints,
  current schema, current storage implementation, and accepted service-boundary
  principles.
- **Known implementation already completed**: project engineering foundation,
  Required Backend CI baseline, Alembic, Document and SourceFile foundation,
  Storage Adapter, Local provider, and original TXT/PDF source retention are
  recorded as completed in current M1 status and M1-003 closeout history.
- **Mismatch with current Atlas architecture**: M1 still has an unclear boundary
  around M1-005 because durable Document/SourceFile foundation already exists,
  while the remaining persistence architecture and processing handoff are not yet
  fully designed.

### Current M2 Structured Reader

- **Intended purpose**: establish a structured reader experience that consumes
  stable reader-oriented content while preserving public Reader expectations.
- **Likely inputs**: structured or canonical document content, ordered blocks,
  image references, Reader navigation needs, and compatibility output such as
  Stream Text.
- **Likely outputs**: reader-oriented presentation, structured rendering,
  navigation behavior, and Speed Reading compatibility output.
- **Dependencies**: stable structured content, content ordering, source evidence
  linkage, image/asset relationships, and an application-facing serializer.
- **Known implementation already completed**: existing Reader/API behavior and a
  prototype content path exist, including current Bookshelf-shaped responses and
  MinerUResult-derived content assembly, but this is not a final structured
  content foundation.
- **Mismatch with current Atlas architecture**: M2 depends on structured content
  that should be produced by processing and normalized into provider-independent
  content before application presentation is finalized. As currently ordered,
  Structured Reader is asked to stabilize before its upstream content pipeline is
  stable.

### Current M3 Document Core

- **Intended purpose**: introduce durable Document Core concepts as the business
  system of record, including documents, source files, page records, processing
  runs, canonical content, observations, assets, and versioned domain records.
- **Likely inputs**: retained sources, processing outputs, observation metadata,
  provider-normalized content, and business lifecycle requirements.
- **Likely outputs**: durable provider-independent content model, evidence links,
  versioning boundaries, and application-consumable canonical content.
- **Dependencies**: Document and SourceFile foundation, storage persistence
  blueprint, processing output contract, and enough real processing output to
  avoid over-designing the model.
- **Known implementation already completed**: Document and SourceFile foundation
  exists from M1/Alembic work; current data still includes Bookshelf,
  PdfPage/BookImage BLOBs, OCR JSON text, MinerU JSON text, and processed TXT
  filesystem output.
- **Mismatch with current Atlas architecture**: part of Document Core already
  belongs in M1 as the durable aggregate/source foundation, while the structured
  content and canonical model should follow an initial processing contract rather
  than precede all knowledge of processing output.

### Current M4 OCR Integration

- **Intended purpose**: integrate OCR compute outputs into the durable system of
  record without moving business ownership into compute services.
- **Likely inputs**: retained source bytes, Storage retrieval, `paddle-vl-api`
  processing responses, MinerU-Popo normalization, and processing provenance.
- **Likely outputs**: processing runs, raw output handling, normalized
  observations, structured processing output, status/error/provenance records,
  and contract tests.
- **Dependencies**: retained source storage, processing handoff contract,
  external provider contract, and persistence placement decisions.
- **Known implementation already completed**: current implementation retains
  original TXT/PDF sources through Storage and includes existing local processing
  and MinerU-Popo behavior; `paddle-vl-api` has not replaced the old local path
  in `pdf-ocr-service`.
- **Mismatch with current Atlas architecture**: M4 is too late because its output
  is a prerequisite for M2 Structured Reader and for the M3 structured/canonical
  content model. The name “OCR Integration” is also too narrow for document
  understanding that includes layout, reading order, hierarchy, tables, figures,
  formulas, normalization, paragraph merging, and structural repair.

### Current M5 Archive Intelligence

- **Intended purpose**: build archive intelligence on canonical document data and
  evidence-backed facts.
- **Likely inputs**: canonical content, evidence links, provenance, structured
  facts, collections, search indexes, and cross-document retrieval capabilities.
- **Likely outputs**: archive organization, evidence-backed answers,
  cross-document knowledge, retrieval workflows, and policy/audit surfaces.
- **Dependencies**: stable Document Intelligence Core, canonical content,
  evidence/provenance model, and sufficient application-independent content
  representation.
- **Known implementation already completed**: product and architecture direction
  exists; implementation is not authorized by this review.
- **Mismatch with current Atlas architecture**: M5 generally belongs after the
  shared core, but parts of Smart Archive planning may proceed in parallel with
  Smart Reading OS after M3 is sufficiently stable.

## Dependency analysis

Actual dependency graph:

```text
Product and Engineering Foundation
  ↓
Source and Storage Foundation
  ↓
Document Processing
  ↓
Structured Content
  ↓
Canonical Document Core
  ↓
Smart Reading OS
  ↓
Smart Archive / cross-document intelligence
```

Hard prerequisites:

- source evidence must exist before reliable processing or reprocessing;
- Storage retrieval must exist before M2 can process retained original sources;
- processing output contracts must exist before structured content can be
  persisted or canonicalized safely;
- structured content must exist before Stream Text can be treated as a generated
  presentation artifact rather than an implicit source of truth;
- canonical/evidence boundaries must exist before archive intelligence can make
  evidence-backed claims.

Incremental or parallelizable work:

- product, architecture, governance, CI, and compatibility documentation can
  evolve in M1 while later implementation remains deferred;
- M3 can define narrow structured-content slices iteratively with M2 output,
  rather than wait for a perfect processing system;
- Smart Reading OS and Smart Archive may evolve partly in parallel after the
  shared core is sufficiently stable, because they are peer applications over the
  same Document Intelligence Core;
- application UX exploration can continue as prototype work, but committed
  milestone completion should not depend on unstable implicit content formats.

## Why the current order fails

### M2 Structured Reader before M4 OCR Integration

Structured Reader cannot be completed cleanly before the structured content
pipeline exists. A reader can prototype against existing MinerUResult JSON or
plain Stream Text, but it cannot be considered architecturally complete until the
upstream processing path defines ordered blocks, source/page evidence, visual
asset relationships, and provider-independent structure.

If M2 remains before M4, Atlas risks making a presentation format the de facto
canonical representation. That would invert the architecture: application needs
would shape the content source of truth before processing and canonicalization
boundaries are known.

### M3 Document Core before processing output is understood

Document Core has two different layers that should not be conflated:

- durable Document/SourceFile foundation, already implemented as M1 foundation;
- future structured/canonical content model, which should follow an initial
  processing contract and evolve iteratively with real output.

Document Core design should not wait until every processing feature is complete,
but it should not fully precede processing-output understanding either. The
recommended sequence is:

1. keep durable Document/SourceFile foundation in M1;
2. define an M1-to-M2 handoff contract;
3. implement M2 processing enough to produce normalized structured output;
4. use that output to design narrow M3 structured/canonical content slices;
5. expose application presentation formats from M3 content through M4 serializers.

This distinguishes durable aggregate identity, processing output contracts,
structured/canonical content, and application presentation formats.

### OCR Integration terminology

“OCR Integration” is too narrow if the work includes:

- OCR;
- layout;
- reading order;
- document hierarchy;
- tables;
- figures;
- formulas;
- normalization;
- paragraph merging;
- structural repair.

The clearer milestone name is **Document Processing Foundation**. That name
covers document understanding and downstream normalization without implying that
all work is text recognition only.

## Current and target processing pipelines

### Current transitional processing path

The current production code path must not be described as already removed. The
transitional path is:

```text
Uploaded PDF
  ↓
temporary local PDF / current upload handling
  ↓
PyMuPDF page rendering
  ↓
PdfPage image BLOBs
  ↓
local PaddleOCR-VL package execution inside pdf-ocr-service
  ↓
per-page OCR JSON text
  ↓
MinerU-Popo normalization
  ↓
MinerUResult JSON text
  ↓
Reader content assembly / current API compatibility
```

For TXT uploads, the current compatibility path retains original source bytes
through Storage and still writes processed TXT output for existing Reader
behavior.

### Target processing direction

Human-confirmed target direction:

```text
SourceFile / retained source
  ↓
Storage.get()
  ↓
paddle-vl-api
  ↓
processing response / document tree
  ↓
MinerU-Popo
  ↓
structured content
  ↓
application serializers
  ↓
Smart Reading OS / Smart Archive
```

Temporary transport files, provider job files, page-range files, and temporary
normalized files may still exist as implementation details. They should not
become business persistence or canonical content by accident.

## Structured Content vs Stream Text

### Structured Content

Structured Content is the provider-independent or application-independent
document representation with stable ordering and semantic structure. It is the
content layer applications should consume directly or through serializers.

Potential concepts include:

- heading;
- paragraph;
- list;
- table;
- figure;
- formula;
- page/source evidence;
- reading order;
- relationships;
- provenance.

This review does not define database tables, ORM models, migrations, APIs, or
storage keys for structured content.

### Stream Text

Stream Text is a generated presentation/compatibility format currently used by
Speed Reading.

```text
Structured Content is authoritative for content structure.
Stream Text is generated for a particular application experience.
```

Stream Text may be generated on demand or cached as a rebuildable presentation
artifact. This review does not decide the caching strategy.

## Proposed Roadmap v2

Candidate roadmap for human confirmation:

```text
M1 — Foundation
M2 — Document Processing Foundation
M3 — Document Core / Structured Content Foundation
M4 — Smart Reading OS
M5 — Smart Archive
```

This is a candidate, not an accepted roadmap.

### Candidate M1 — Foundation summary

- **Objective**: close engineering, governance, compatibility, durable source,
  storage, deployment-limitations, persistence-blueprint, and handoff-contract
  foundations.
- **Inputs**: current service behavior, current Reader compatibility, accepted
  product/architecture direction, Document/SourceFile foundation, Alembic,
  Storage Adapter, Local provider, and source-retention implementation.
- **Outputs**: foundation status, retained source mechanics, persistence
  architecture blueprint, M1-to-M2 processing handoff contract, and explicit
  deployment limitations.
- **Dependencies**: current code, CI, storage implementation, and human approval
  of milestone boundary.
- **Scope**: foundation, not full processing or application delivery.
- **Non-goals**: full `paddle-vl-api` integration, final structured-content
  schema, Stream Text behavior, Flashcards, Mind Map, Notes, and Smart Archive.
- **Definition of done**: see proposed M1 definition of done below.
- **Migration from old milestone**: mostly unchanged, with M1-005 clarified as a
  design/contract closeout rather than duplicate Document/SourceFile model work.
- **Existing work retained**: engineering foundation, CI, Alembic, Document,
  SourceFile, Storage Adapter, Local provider, original source retention, tests,
  and compatibility posture.
- **Risks**: expanding M1 indefinitely, treating design as implementation, or
  closing M1 without the blueprint needed for M2/M3.

### Candidate M2 — Document Processing Foundation summary

- **Objective**: replace or isolate the obsolete local PDF-processing path with a
  service-oriented document processing pipeline based on retained source,
  `paddle-vl-api`, MinerU-Popo, and normalized structured processing output.
- **Inputs**: retained source bytes via Storage, processing handoff contract,
  provider contract, and current MinerU-Popo behavior.
- **Outputs**: processing client/integration, job/result envelope handling,
  status/error/provenance behavior, normalized output contract, and tests.
- **Dependencies**: M1 retained source and handoff foundation.
- **Scope**: processing integration and normalized output, including whole
  document and page-range considerations where approved.
- **Non-goals**: final canonical content database design, Smart Reading OS
  delivery, and archive intelligence.
- **Definition of done**: source retrieval through Storage, `paddle-vl-api`
  contract integration, processing result ingestion, MinerU-Popo normalization,
  provenance/version capture, retry/idempotency boundaries, mocked CI contract
  tests, and external/manual smoke validation where required.
- **Migration from old milestone**: current M4 OCR Integration moves earlier and
  is renamed to Document Processing Foundation.
- **Existing work retained**: source retention, local processing knowledge,
  MinerU-Popo code, tests, and API compatibility safeguards.
- **Risks**: external service instability, unclear raw-output persistence,
  provider-specific output leaking into canonical data, and insufficient mocked
  CI coverage.

### Candidate M3 — Document Core / Structured Content Foundation summary

- **Objective**: create the durable, provider-independent content model consumed
  by applications.
- **Inputs**: M2 normalized structured processing output, retained source
  evidence, processing provenance, storage blueprint, and application needs.
- **Outputs**: structured document blocks/nodes, ordering, evidence links,
  asset relationships, versioning boundaries, provider-output isolation, and
  serializer inputs.
- **Dependencies**: M1 durable Document/SourceFile foundation and M2 processing
  output contract.
- **Scope**: ProcessingRun and observation metadata concepts as justified;
  structured content; canonicalization boundaries; database vs Object Storage
  persistence decisions.
- **Non-goals**: premature complete knowledge graph, all archive intelligence,
  and application-specific Stream Text as source of truth.
- **Definition of done**: a narrow durable structured-content slice exists with
  tests, migration coverage if schema changes are approved, provenance linkage,
  and provider-output isolation.
- **Migration from old milestone**: current M3 is split: already implemented
  Document/SourceFile foundation remains in M1; future structured/canonical
  content foundation remains in proposed M3.
- **Existing work retained**: Document/SourceFile, current schema review,
  canonical data-flow principles, and compatibility constraints.
- **Risks**: over-designing before M2 output is stable or under-designing so
  Stream Text becomes canonical by default.

### Candidate M4 — Smart Reading OS summary

- **Objective**: build Smart Reading OS on stable structured/canonical content.
- **Inputs**: M3 structured/canonical content, serializers, assets, source
  evidence links, and Reader compatibility constraints.
- **Outputs**: Smart Reading OS application capabilities such as Reader and
  navigation, Speed Reading serialization/playback, Notes, Flashcards, and Mind
  Map.
- **Dependencies**: sufficiently stable shared content core.
- **Scope**: one application containing Speed Reading, Flashcards, Mind Map, and
  Notes. Example phases could be M4A Reader/navigation, M4B Speed Reading,
  M4C Notes, M4D Flashcards, and M4E Mind Map, but this review does not approve
  sub-milestones.
- **Non-goals**: treating Stream Text as canonical content, building a separate
  platform, or duplicating Document Core.
- **Definition of done**: human-approved feature scope is delivered on top of
  structured/canonical content with compatibility tests and clear presentation
  artifacts.
- **Migration from old milestone**: current M2 Structured Reader moves after M3
  and broadens to the Smart Reading OS application boundary.
- **Existing work retained**: Reader prototype/API compatibility, content stream
  contract work, Speed Reading compatibility concepts, and existing tests.
- **Risks**: application work starting before content contracts stabilize or
  silently approving all learning features at once.

### Candidate M5 — Smart Archive summary

- **Objective**: apply the shared Document Intelligence Core to personal and
  organizational unstructured information.
- **Inputs**: canonical content, evidence links, provenance, indexes, facts,
  collections, and policy decisions.
- **Outputs**: collections and organization, cross-document search,
  evidence-backed answers, archive intelligence, enterprise policy, provenance,
  auditability, and cross-document knowledge.
- **Dependencies**: shared core stability and evidence-backed content model.
- **Scope**: committed scope must be separated from future ideas such as broad
  enterprise workflows, media/web ingestion, or advanced reasoning.
- **Non-goals**: implementing unapproved enterprise scope or bypassing evidence
  provenance.
- **Definition of done**: human-approved archive capabilities consume shared core
  content and maintain evidence/provenance constraints.
- **Migration from old milestone**: current M5 remains broadly aligned but should
  be framed as Smart Archive rather than Archive Intelligence alone.
- **Existing work retained**: product strategy and architecture philosophy.
- **Risks**: scope expansion, cross-document claims without sufficient evidence,
  or building archive-specific content separate from the shared core.

## Proposed M1 — Foundation

M1 should contain:

- project/product/architecture foundation;
- engineering governance;
- CI;
- Document and SourceFile;
- Alembic;
- Storage Adapter;
- Local provider;
- original source-retention mechanics;
- Storage Persistence Architecture and Schema Alignment blueprint;
- deployment limitations;
- interfaces/contracts required for M2.

M1 should not contain:

- full `paddle-vl-api` processing integration;
- final structured-content schema;
- Stream Text application behavior;
- Flashcards/Mind Map/Notes;
- Smart Archive intelligence.

## Proposed M2 — Document Processing Foundation

Candidate objective:

```text
retained source
  ↓
paddle-vl-api
  ↓
MinerU-Popo
  ↓
normalized structured processing output
```

Required work to evaluate for M2:

- `paddle-vl-api` client/integration contract;
- async job protocol where applicable;
- status/progress/error handling;
- source retrieval through Storage;
- whole-document and page-range processing;
- processing result ingestion;
- MinerU-Popo normalization;
- structured output contract;
- processing provenance/version;
- retry and idempotency;
- contract tests;
- mocked CI integration;
- external/manual smoke validation;
- removal or isolation of the legacy local PaddleOCR-VL path.

This review does not authorize implementation.

## Proposed M3 — Document Core / Structured Content Foundation

Candidate objective: create the durable, provider-independent content model
consumed by applications.

Likely responsibilities:

- ProcessingRun;
- Observation or processing output metadata;
- structured document blocks/nodes;
- ordering;
- source/page evidence linkage;
- Asset relationships;
- canonicalization boundaries;
- versioning;
- database vs Object Storage persistence;
- Stream serialization input;
- provider-output isolation.

This remains distinct from the already implemented Document/SourceFile
foundation. Document/SourceFile identity and source evidence are foundation; the
future structured/canonical content model is a later content layer.

## Proposed M4 — Smart Reading OS

Candidate objective: build Smart Reading OS on stable structured/canonical
content.

Smart Reading OS should be organized as one application containing:

- Speed Reading;
- Flashcards;
- Mind Map;
- Notes.

Example phased delivery could be:

- M4A Reader and navigation;
- M4B Speed Reading serialization/playback;
- M4C Notes;
- M4D Flashcards;
- M4E Mind Map.

These examples are not approved sub-milestones. Stream Text belongs here as
Speed Reading presentation output generated from structured content.

## Proposed M5 — Smart Archive

Candidate objective: apply the shared Document Intelligence Core to personal and
organizational unstructured information.

Directions to evaluate:

- collections and organization;
- cross-document search;
- evidence-backed answers;
- contracts, receipts, quality records, test records, manuals, media, and
  webpages;
- archive intelligence;
- enterprise policy;
- provenance and auditability;
- cross-document knowledge.

Committed scope should remain separate from future ideas.

## Old-to-new milestone mapping

| Current milestone | Existing scope | Proposed destination | Reason |
|---|---|---|---|
| M1 Foundation | Engineering foundation, CI, Alembic, Document/SourceFile foundation, Storage Adapter, Local provider, original TXT/PDF retention, compatibility posture | M1 Foundation, with boundary clarification | Mostly unchanged; add persistence blueprint and M1-to-M2 processing handoff as design closeout, not processing implementation. |
| M2 Structured Reader | Reader content stream usage, structured rendering, presentation compatibility | M4 Smart Reading OS | Reorder and broaden: reader presentation should follow structured/canonical content and belongs inside Smart Reading OS. |
| M3 Document Core | Documents, source files, page records, processing runs, canonical content, observations, assets, versioned records | Split between M1 and M3 | Document/SourceFile foundation already belongs to M1; structured/canonical content foundation should follow M2 processing output. |
| M4 OCR Integration | OCR output ingestion, processing runs, observations, temporary artifacts, durable assets, compute boundary | M2 Document Processing Foundation | Rename and move earlier because processing output is prerequisite for structured content and reader applications. |
| M5 Archive Intelligence | Evidence-backed archive facts, organization, retrieval, document knowledge surfaces | M5 Smart Archive | Scope clarification: Smart Archive is a peer Atlas application over the shared core. |

Mapping classifications:

- **Reorder**: M4 processing moves before current M2/M3 application/core work.
- **Rename**: OCR Integration becomes Document Processing Foundation.
- **Split**: current M3 Document Core divides into existing M1 foundation and
  future M3 structured/canonical content.
- **Scope clarification**: current M2 becomes part of Smart Reading OS; current
  M5 becomes Smart Archive.
- **Unchanged**: M1 remains Foundation, but requires closeout boundary
  clarification.
- **Deferred**: final tables, full application features, and archive intelligence
  implementation remain future work.

This review does not renumber canonical tasks.

## Impact on existing work

Preserved unchanged:

- product strategy;
- architecture philosophy;
- Document and SourceFile;
- Alembic;
- Storage;
- API compatibility;
- CI;
- Reader prototype;
- MinerU-Popo work;
- `paddle-vl-api` as target external service;
- existing tests.

Transitional:

- local PaddleOCR-VL processing;
- processed TXT file;
- PdfPage BLOB workflow;
- BookImage BLOB workflow;
- OCR JSON database text;
- MinerU JSON database text;
- MinerUResult direct Reader dependency;
- Stream Text as implicit canonical representation;
- old milestone labels.

## M1 completion analysis

Question: what exactly must still be completed before M1 may close?

### A. Storage Persistence Architecture Blueprint

M1 should require a documentation/design task for **Storage Persistence
Architecture and Schema Alignment** before closeout. The Storage Adapter
mechanics are implemented, but the complete persistence architecture is not yet
fully designed.

The blueprint should define or explicitly defer:

- which data belongs in the relational database;
- which data belongs in Object Storage;
- which data belongs in future derived indexes;
- current SourceFile-to-Storage linkage;
- future Artifact storage linkage;
- whether a StoredObject persistence model is needed now or deferred;
- storage of raw `paddle-vl-api` output;
- storage of MinerU-Popo output;
- storage of structured content;
- role of Stream Text as generated presentation;
- DB BLOB/Text migration direction;
- broken-reference detection;
- production durability requirements.

Recommendation: this is mandatory before M1 closure because M2 processing and M3
structured content need a clear persistence boundary. The blueprint should not
implement new schema by itself.

### B. Processing handoff contract

M1 should require a documented **M1-to-M2 Processing Handoff Contract**. M1 does
not need to implement processing, but it should make the M2 entry point explicit.

Contract topics:

- how M2 obtains original source bytes through Storage;
- how `paddle-vl-api` is called at the contract level;
- what result envelope is expected;
- where raw processing output is stored or temporarily staged;
- what MinerU-Popo receives;
- what minimum structured output M3 will later persist;
- status/error/provenance boundaries.

Recommendation: the handoff belongs in M1 closeout as a design contract or in a
small M1-closeout documentation PR. Detailed provider implementation belongs in
M2.

### C. End-to-end implementation

M1 should not need to run this end-to-end path:

```text
upload → storage → paddle-vl-api → MinerU-Popo → structured content
```

That path is the main objective of proposed M2 Document Processing Foundation.
Putting it in M1 would expand Foundation into implementation, delay closeout, and
blur milestone boundaries. M1 should define enough contract surface for M2 to
start safely.

### D. M1 closeout readiness

Recommendation: **M1 can close after one focused design/contract closeout task**,
provided human approval confirms Roadmap v2 direction.

The focused task should combine Storage Persistence Architecture and Schema
Alignment with the M1-to-M2 Processing Handoff Contract if it can remain concise
and reviewable. If it becomes large, split into two documentation PRs. M1 should
not wait for actual `paddle-vl-api` processing integration.

## Recommended M1 closeout plan

Smallest recommended plan:

1. Complete one documentation task: **Storage Persistence Architecture and M1-to-M2
   Processing Handoff**.
2. Obtain human confirmation of Roadmap v2 milestone boundaries.
3. Realign the canonical roadmap after human approval in a separate PR.
4. Complete M1 closeout and begin M2 Document Processing Foundation.

Recommended packaging:

- Prefer one documentation PR if the persistence blueprint and processing handoff
  are concise and share the same boundary decisions.
- Split into two PRs if the persistence blueprint needs substantial schema and
  storage tradeoff analysis.
- Defer actual `paddle-vl-api` integration, raw-output ingestion code, and
  structured-content persistence implementation to M2/M3.

## M1 definition of done

Proposed revised M1 definition of done:

- product direction accepted;
- architecture principles accepted;
- engineering workflow established;
- CI established;
- Document/SourceFile foundation implemented;
- Alembic established;
- Storage Adapter implemented;
- Local provider implemented;
- original source-retention mechanics implemented;
- persistence blueprint documented;
- M2 processing handoff documented;
- deployment limitations explicit;
- Reader compatibility remains protected;
- M1 closeout verified.

This definition does not include M2 processing implementation.

## Dependency graph

```text
M1 Foundation
  ├── Product / Architecture
  ├── Document / SourceFile
  ├── Database / Alembic
  ├── Storage
  └── Persistence + Processing Handoff
            ↓
M2 Document Processing Foundation
  ├── paddle-vl-api
  ├── MinerU-Popo
  └── Structured Processing Output
            ↓
M3 Document Core / Structured Content
            ↓
   ┌────────┴────────┐
   ↓                 ↓
M4 Smart Reading   M5 Smart Archive
```

M4 and M5 need not be strictly sequential after M3. They may proceed partly in
parallel once the shared Document Intelligence Core and structured/canonical
content contracts are stable enough for both applications.

## Alternatives considered

| Alternative | Benefits | Risks | Documentation churn | Migration cost | Dependency clarity |
|---|---|---|---|---|---|
| Keep current roadmap unchanged | Minimal churn; preserves labels | Keeps Structured Reader before its upstream content source; encourages Stream Text as implicit canonical data | Low now, higher later | Low now, higher later | Poor |
| Only move current M2 after current M4 | Fixes the most obvious ordering issue | Leaves narrow OCR name and unclear Document Core split | Medium | Medium | Medium |
| Swap M2 and M4 but preserve all names | Easy to explain as a reorder | “OCR Integration” remains too narrow and Smart Reading OS remains under-modeled | Medium | Medium | Medium-low |
| Adopt Roadmap v2 with reordered and renamed responsibilities | Aligns names with dependencies and product structure | Requires human approval and roadmap/document migration | Medium-high | Medium | High |
| Complete processing integration inside M1 | Produces a stronger end-to-end foundation | Expands M1 indefinitely and mixes foundation with M2 implementation | High | High | Medium |
| Close M1 before processing integration and make it M2 | Preserves milestone boundary and enables focused M2 | Requires clear handoff contract to avoid ambiguity | Medium | Medium | High if handoff is documented |

## Recommended roadmap

**Codex Recommendation — Human Confirmation Required**

Adopt Roadmap v2 as the dependency-aligned structure:

```text
M1 — Foundation
M2 — Document Processing Foundation
M3 — Document Core / Structured Content Foundation
M4 — Smart Reading OS
M5 — Smart Archive
```

Recommendation details:

- keep M1 as Foundation and close it after persistence/handoff design, not after
  processing implementation;
- move current M4 OCR Integration earlier and rename it Document Processing
  Foundation;
- split current M3 so Document/SourceFile foundation remains in M1 and future
  structured/canonical content becomes proposed M3;
- move current M2 Structured Reader after proposed M3 and place it inside Smart
  Reading OS;
- keep Smart Archive as a peer application over the shared core, with some
  planning possible in parallel after M3 stability.

This recommendation is not accepted until a human confirms it.

## Human decisions required

1. Whether Roadmap v2 is accepted.
2. Final milestone names.
3. Whether M3 is “Document Core,” “Structured Content Foundation,” or a combined
   name.
4. Whether M4 includes all Smart Reading OS features or only the initial
   application foundation.
5. Whether M4 and M5 may proceed partly in parallel after M3.
6. Whether Storage Persistence Architecture is required to close M1.
7. Whether a Processing Handoff Contract is required to close M1.
8. Whether actual `paddle-vl-api` integration belongs in M1 or proposed M2.
9. Whether the existing M1 closeout PR should remain paused until Roadmap v2 is
   accepted.
10. How current M1-004/M1-005 numbering should be treated after realignment.

## Roadmap migration strategy

After human approval, recommended documentation sequence:

1. Accept Roadmap v2 decision.
2. Update canonical roadmap.
3. Update milestone documents.
4. Reconcile current M1 tasks and progress.
5. Update M1 closeout review.
6. Add M2 milestone document.
7. Record an ADR or roadmap decision record if appropriate.

This review PR does not execute that migration.

## Risks

- roadmap churn;
- rewriting history rather than recording evolution;
- mixing product milestones and technical foundations;
- beginning Reader work before content contracts stabilize;
- over-designing Document Core before processing output is understood;
- allowing provider-specific OCR output to become canonical data;
- making Stream Text the only content representation;
- expanding M1 indefinitely;
- moving too much work into M2 without a clear handoff;
- treating Storage persistence design as Storage implementation;
- under-specifying production durability while current local/Hugging Face storage
  remains test-only or deployment-dependent;
- letting old milestone names continue to imply incorrect dependency order.

## Non-goals

This review does not:

- implement `paddle-vl-api` integration;
- implement MinerU-Popo changes;
- implement structured-content tables;
- implement Stream Text generation;
- implement Speed Reading;
- implement Flashcards;
- implement Mind Map;
- implement Notes;
- implement Smart Archive;
- change canonical milestone numbering;
- close M1;
- create M2 implementation tasks;
- change APIs;
- change database schema;
- change Storage implementation;
- modify production code;
- modify CI;
- modify dependencies;
- modify deployment configuration;
- modify runtime behavior.

## Decision summary

| Decision | Current status | Recommendation | Human confirmation required? |
|---|---|---|---|
| Current roadmap dependency problem | Structured Reader appears before processing and structured content | Recognize as a real dependency-order failure | Yes |
| Roadmap v2 | Candidate only | Adopt M1 Foundation, M2 Document Processing Foundation, M3 Document Core / Structured Content Foundation, M4 Smart Reading OS, M5 Smart Archive | Yes |
| M1 boundary | Foundation in progress; much implementation complete; M1-005 unclear | Close after persistence blueprint and processing handoff, not after full processing | Yes |
| M2 processing scope | Currently later as M4 OCR Integration | Move earlier and rename Document Processing Foundation | Yes |
| M3 structured-content scope | Mixed with already implemented Document/SourceFile foundation | Treat future M3 as structured/canonical content foundation, distinct from M1 Document/SourceFile | Yes |
| M4 Smart Reading OS scope | Current M2 is Structured Reader | Place Reader/Speed Reading/Notes/Flashcards/Mind Map under Smart Reading OS after content core | Yes |
| M5 Smart Archive scope | Current M5 is Archive Intelligence | Keep as peer Smart Archive application over shared core | Yes |
| Stream Text classification | Risk of implicit canonical representation | Classify as generated presentation/compatibility format for Speed Reading | Yes |
| Storage persistence blueprint | Not fully designed | Require before M1 closure as documentation/design | Yes |
| Processing handoff | Not fully explicit | Require M1-to-M2 handoff contract before M1 closure | Yes |
| Actual `paddle-vl-api` integration milestone | Not yet replacing local path in `pdf-ocr-service` | Put implementation in proposed M2, not M1 | Yes |
| M1 closeout readiness | Not ready while boundary/handoff remain unclear | M1 can close after one focused design/contract closeout task if approved | Yes |
