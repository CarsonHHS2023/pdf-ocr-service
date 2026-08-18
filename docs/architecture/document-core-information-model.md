# Atlas Document Core Information Model

Conceptual Responsibilities of Document Information

| Field | Value |
|---|---|
| Document Type | Document-Core Information Model |
| Approval Status | Proposed |
| Authority Domain | Conceptual Document Core information entities, responsibilities, and relationships |
| Implementation Status | Architecture-only model; no schema, API, implementation, or release authorization |

## Status

**State:** Proposed.

This document is architecture-only. It defines conceptual semantic responsibilities for Atlas Document Core. It does not approve implementation work, milestone realignment, milestone closure, release-note changes, contract changes, runtime changes, tests, fixtures, tags, branches, or pull requests.

## Purpose

Atlas needs a shared information model for document semantics before choosing any physical representation. This document defines the conceptual information responsibilities managed across processing interpretation, evidence grounding, processing provenance, assessment, accepted content, version lineage, application projections, and presentation.

The central rule is: the information aspects in this model are conceptual semantic responsibilities, not mandatory primary attributes, object containers, implementation types, tables, services, externally exposed contracts, storage partitions, or pipeline stages.

The model must not require information to be represented as one document-wide container, one tree, one graph, one serialized payload, one relational design, one event stream, one file, one service, one external payload, or any fixed combination of these.

## Scope

This document applies to future architecture and review work that defines or extends Document Core concepts. It complements the existing Atlas Document Core and Structured Content Architecture. It does not replace that architecture and does not introduce a new processing layer.

This model is independent of serialization formats, programming languages, database design, object storage layout, service topology, interface design, user interfaces, and presentation frameworks.

This document must not rename or replace Raw Processing Result, ProviderObservation, NormalizedObservation, Structured Processing Result, Structured Content Version, Application Projection, or Presentation Cache.

## Relationship to Existing Architecture

The existing Atlas Document Core and Structured Content Architecture defines architectural layers, processing boundaries, authority, durability, rebuildability, normalization, canonicalization, application ownership, and presentation ownership.

This Information Model defines categories of information, semantic responsibility, primary ownership, cross-layer references, authority distinctions, versioning expectations, and lifecycle expectations.

Where terminology differs between older architecture documents and this model, the difference is a later alignment issue. This document does not silently resolve historical terminology drift and does not override released Processing Core authority.

## Released Processing Core Baseline

Atlas Processing Core v1.0 is the stable lower-level baseline for this model. The locally verified fallback release commit is `7a5a6917b2c4220df5045fbefb35a49a1938f732`. The local checkout cannot verify the tag `M3-Processing-Core-v1.0`; this document does not claim that the tag was locally verified.

The released boundary is retained provider-specific Raw Processing Result to provider-specific normalization to provider-independent Structured Processing Result.

The released baseline includes the Structured Processing Result contract, provider-independent Structured Processing Result semantics, deterministic semantic identity, schema-versioned Structured Processing Result, deterministic serialization, validation, Paddle-VL raw-result normalization, field-level recovery, block-level recovery, page-level recovery, result-level recovery, topology-preserving mixed multi-page recovery, usable-page semantics, no-usable-semantic-content page semantics, partial Structured Processing Result behavior, no-semantic-fabrication policy, Provider Conformance Profile, Block Recovery Contract, ADR-0001 Mixed Multi-page Recovery Policy, and related fixtures and tests.

Released Processing Core semantics include usable pages, no-usable-semantic-content pages, topology-preserving degraded pages, mixed partial Structured Processing Result behavior, preservation of mapped page topology when no semantic observations survive, and no Structured Processing Result when no usable semantic output exists anywhere.

Post-release implementation refinements include explicit runtime page-status representation, page-level diagnostic representations, document-level partial-recovery diagnostic representations, validation requiring degraded pages to contain no semantic content, validation requiring degraded-page documents to be partial, validation requiring at least one usable page, and validation requiring mixed recovery diagnostics.

Future Document Core architecture must preserve the distinction between released architecture-level semantics and later runtime representations. No single runtime representation defines the architecture-level concept unless a future compatibility decision says so explicitly.

## Foundational Principles

### Implementation Independence

Atlas must define concepts before choosing representations, storage, programming languages, or frameworks. A semantic responsibility may be carried by many future representations.

### Provider Independence

Atlas semantics must not depend on Paddle-VL, MinerU, Docling, Azure Document Intelligence, or any provider-specific payload model. Providers may produce evidence and assertions; Atlas owns the normalized semantics.

### Application Independence

Document Core must remain shared infrastructure for Smart Reading, Smart Archive, and future applications. Application-specific needs must not redefine shared accepted content.

### Evidence Grounding

Atlas interpretations and accepted content must remain traceable to submitted source evidence and retained processing evidence where available.

### Explicit Versioning

Source, processing, schema, normalizer, content, assessment, canonical selection, and application projection versions must not be collapsed into one generic version number.

### No Silent Mutation

Raw evidence, Structured Processing Result versions, assessments, and Structured Content Versions must not be silently overwritten. Reprocessing, correction, reassessment, and reselection must create explicit lineage or version history.

### Explicit Canonicalization

Canonical state results from acceptance and selection policy. Provider success or Structured Processing Result validity alone must not make content canonical.

### Derived Presentation

Application projections and presentation outputs are derived consumers, not canonical content. Presentation must not become the source of shared document truth.

### Semantic Ownership Before Schema

Every future schema element must first have a defined semantic responsibility and architectural owner.

### Semantic Ownership Is Not Physical Ownership

Architectural ownership defines meaning, authority, lifecycle, versioning, compatibility, and governance responsibility. Semantic ownership must not require exclusive physical ownership of a database table, storage object, package, repository module, service, process, or deployment boundary. Shared persistence may physically store information owned semantically by different layers. Physical co-location must not merge semantic ownership.

### Cross-Layer Reference Does Not Transfer Authority

A layer may reference information owned by another layer without acquiring its authority. Application Projection may display assessment results without owning assessment semantics. Structured Content Version may reference Original Source evidence without becoming source authority. Presentation may disclose processing diagnostics without owning Processing Core outcome facts. Shared persistence may retain ProcessingRun records without owning execution semantics. References preserve lineage and usability, not ownership transfer.

### Released-Baseline Immutability

Future Document Core architecture must build above Atlas Processing Core v1.0 and must not retroactively redefine released Structured Processing Result semantics.

## Conceptual Layer Context

A conceptual responsibility flow is:

Original Source → Raw Processing Result → Provider-specific normalization → Structured Processing Result → Document Core assessment, accepted-content construction, and lineage governance → Structured Content Version → Application Projection → Presentation.

This is a conceptual responsibility flow. Document Core is not one mandatory serial service. Some evidence and provenance responsibilities span multiple stages, including information first created before or during Structured Processing Result production. The flow does not prescribe storage design, interface design, object design, graph design, tree design, or service design.

### Original Source

Original Source is authoritative evidence of what was submitted or registered. It is not an Atlas interpretation of meaning.

### Raw Processing Result

Raw Processing Result is immutable retained evidence of what a provider returned. It preserves provider-return evidence without making provider output canonical Atlas content.

### ProviderObservation

ProviderObservation is a provider assertion extracted from provider output. It may preserve provider-native identity or labels for evidence and provenance, but those identifiers must not become Atlas business identity by default.

### NormalizedObservation

NormalizedObservation is an Atlas-normalized assertion independent of provider field naming. It connects provider assertions to Atlas interpretation without becoming accepted Structured Content by itself.

### Structured Processing Result

Structured Processing Result is a provider-independent Atlas interpretation of processing output. It is schema-versioned, rebuildable where retained evidence permits, partial-capable, and noncanonical.

Structured Processing Result is not canonical Structured Content, Reader projection, application projection, or presentation output.

### Structured Content Version

Structured Content Version is an immutable, versioned, application-independent content version produced under Document Core governance. It may be proposed, accepted, rejected, selected, superseded, or canonical. SCV identity does not require acceptance or canonical status. A proposed SCV may exist before acceptance. Acceptance and rejection are explicit. An Accepted SCV may remain noncanonical. Canonical selection is explicit. Multiple immutable SCVs may coexist for one lineage. Rejected SCVs may be retained for lineage and audit subject to future retention policy. Rejection, selection, supersession, and canonical state must not mutate prior immutable SCVs.

### Structured Content Version State Terminology

Structured Content Version, or SCV, is the general term for any immutable, versioned, application-independent content version governed by Document Core, regardless of governance state. A Proposed SCV is an SCV that has not yet passed explicit acceptance. An Accepted Structured Content Version, or Accepted SCV, is an SCV that has passed explicit acceptance. Acceptance does not imply canonical selection. A Rejected SCV is an SCV that did not pass acceptance or was explicitly rejected under Document Core governance. A Selected SCV is an SCV selected under an explicit governance decision. Selection terminology must not silently imply canonical status unless the selection is specifically canonical selection. A Canonical Structured Content Version, or Canonical SCV, is an Accepted SCV that has been explicitly selected as canonical for a lineage. A Superseded SCV is an SCV whose prior role has been replaced by a later explicit governance decision while the prior immutable version remains preserved according to lineage and retention policy.

Unless explicitly qualified, the term Structured Content Version or SCV does not imply proposed, accepted, rejected, selected, superseded, or canonical state. Where governance state materially affects meaning, use the state-qualified term. These terms describe governance state. They do not define separate entity types, schemas, storage objects, inheritance hierarchies, tables, services, or runtime representations. They do not define exact status terms or transition rules.

### Application Projection

Application Projection is a derived, application-owned representation built from an SCV, approved evidence references, assessment results, provenance, application-owned policy, and user or workspace state where applicable. SCV remains the shared content foundation. Applications may reference approved evidence and assessment, but Application Projection must not redefine SCV content, evidence truth, assessment authority, or canonical state. Application-owned state remains distinguishable from shared Document Core information, and projections remain rebuildable or explicitly versioned.

### Presentation

Presentation is user-facing rendering, interaction, disclosure, formatting, and cache behavior. Presentation must never become canonical document content.

## Information Aspects

The six information aspects are semantic responsibilities. They are not mandatory containers and do not prescribe physical representation.

### Identity and Versioning

**Responsibility:** identify information-bearing entities and distinguish independent version axes.

**Central question:** What entity or version is this, how is it related to prior or parallel versions, and what authority does the identity carry?

**Representative concepts:** Document, SourceFile, ProcessingRun, Raw Processing Result, ProviderObservation, NormalizedObservation, Structured Processing Result, Structured Content Version, ContentNode, Asset, schema version, provider profile version, model version, normalizer version, processing attempt, retry, content version, assessment version, projection version, supersession, proposal, selection, and canonical pointer.

**Explicit exclusions:** Semantic identity must not depend solely on provider IDs, storage paths, temporary artifact URLs, mutable text, source coordinates, or content hashes.

**Relationship to Raw Result or Observations:** Raw Result identity identifies retained provider-return evidence. ProviderObservation and NormalizedObservation identities support traceability from provider assertion to Atlas-normalized assertion.

**Relationship to Structured Processing Result:** Processing Core semantically owns ProcessingRun execution identity, provider execution status, request/job and attempt identity, retry lineage, Raw Processing Result association, normalizer identity and version, execution and normalization provenance, and Structured Processing Result identity. Structured Processing Result identity is not permanent accepted-content identity.

**Relationship to Structured Content Version:** Document Core owns Structured Content Version identity, content lineage, proposal, selection, supersession, and canonical state.

**Relationship to Application Projections:** Applications own projection identity and projection versions. Projection identity must not become canonical content identity.

**Authority considerations:** Atlas maintains multiple independent version axes. They must not be reduced to one version number. Storage references own location mechanics only.

**Lifecycle and versioning considerations:** Retries, reprocessing, reassessment, content correction, canonical reselection, and projection regeneration are distinct lifecycle events. The assessment lineage must be distinguishable when assessment affects acceptance, rejection, promotion eligibility, canonical selection, or user-visible governance decisions. This model does not require every transient assessment computation to become a durable standalone version. Persistence and granularity remain future contract decisions. Incompatible assessment semantics require explicit versioning or compatibility handling.

**Overlap risks:** Reusing Structured Processing Result node identifiers as permanent Structured Content Version node identifiers without explicit lineage rules can make processing candidates appear to be accepted content identity.

**Primary semantic ownership rules:** Processing Core owns processing-run and Structured Processing Result identity; Document Core owns Structured Content Version identity and content-lineage state; Applications own projection identity; Storage owns location mechanics only.

### Content

**Responsibility:** represent semantic information expressed by the source and recovered, interpreted, accepted, or derived by Atlas.

**Central question:** What does the document express?

**Representative concepts:** text, headings, paragraphs, list items, table values, formulas, figure-related semantic content, captions, source-authored notes, footnotes, endnotes, source marginal annotations, annotations present in the submitted source, language-bearing content, accepted structured values, application-derived summaries, translations, and flashcard content.

**Explicit exclusions:** Content excludes user-interface formatting, provider-native payload fields as field semantics, source coordinates, processing status, evidence location, quality judgment, and canonical-selection state.

**Relationship to Raw Result or Observations:** Raw Result contains provider-native content evidence. ProviderObservation expresses provider assertions about content. NormalizedObservation expresses Atlas-normalized candidate assertions.

**Relationship to Structured Processing Result:** Structured Processing Result contains normalized candidate content.

**Relationship to Structured Content Version:** Structured Content Version contains immutable, versioned, application-independent content governed by Document Core. Its content may remain proposed, may be accepted or rejected, and may later participate in explicit canonical selection.

**Relationship to Application Projections:** Applications may derive summaries, cards, reading text, translations, user-created study notes, private comments, collaborative notes, application annotations, and other application-specific content. User-created notes are application-owned by default and must not silently become SCV content. Any future promotion into shared accepted content requires a separate governed process with explicit authority, evidence, lineage, and versioning. This document does not design that process.

**Authority considerations:** Provider-native content evidence is not canonical. Atlas-normalized candidate content is not accepted content. Accepted shared content requires Document Core governance.

**Lifecycle and versioning considerations:** Source reprocessing may produce different candidate content. Accepted content changes require a new content version or explicit lineage event.

**Overlap risks:** Reader text, study cards, translations, or generated summaries may accidentally become treated as shared content if projection boundaries are not explicit.

**Primary semantic ownership rules:** Processing Core owns normalized candidate content; Document Core owns accepted shared content; Applications own derived content; Presentation owns rendering only.

### Structure

**Responsibility:** represent semantic organization and relationships among content.

**Central question:** How is content organized and related?

**Representative concepts:** document hierarchy, sections, headings, parent-child relationships, ordered siblings, list organization, table organization, page topology, reading-order edges, cross-page continuation, structural alternatives, and accepted semantic order.

**Explicit exclusions:** Structure excludes user-interface tree expansion state, visual graph coordinates, Reader scroll order as canonical structure, and provider order as automatically authoritative.

**Relationship to Raw Result or Observations:** Provider output may contain provider-detected order or layout relationships. ProviderObservation and NormalizedObservation may carry assertions about those relationships.

**Relationship to Structured Processing Result:** Structured Processing Result represents normalized candidate structure.

**Relationship to Structured Content Version:** Structured Content Version represents immutable, versioned, application-independent structure governed by Document Core. That structure may remain proposed, may be accepted or rejected, and may later participate in explicit canonical selection. Accepted SCV structure is accepted shared structure. Canonical SCV structure is the structure explicitly selected as canonical, and acceptance alone does not imply canonical selection.

**Relationship to Application Projections:** Applications may derive purpose-specific order, grouping, simplification, expansion, or navigation paths.

**Authority considerations:** Source-page order, provider-detected order, normalized order, accepted canonical order, and application-specific order must not be treated as interchangeable.

**Lifecycle and versioning considerations:** Normalized structure can change when evidence, provider behavior, or normalizer behavior changes. Accepted structure changes require Structured Content Version lineage.

**Overlap risks:** Presentation trees or graphs can become de facto canonical if shared structure ownership is not explicit.

**Primary semantic ownership rules:** Processing Core owns normalized candidate structure; Document Core owns accepted application-independent structure; Applications own purpose-specific organization; Presentation must not redefine canonical structure.

### Evidence and Grounding

**Responsibility:** connect Atlas assertions and accepted content to supporting source evidence.

**Central question:** What source evidence supports this assertion, content item, structural relationship, or acceptance decision?

**Representative concepts:** SourceFile, source checksum or source version, source page, page index, page number, source region, coordinate system, spans, excerpts, Raw Processing Result, ProviderObservation, NormalizedObservation, evidence references, evidence roles, ContentNode grounding, Asset grounding, and evidence confidence with provenance.

**Accepted-content lineage example:** SCV ContentNode → originating SPR node and/or NormalizedObservation → ProviderObservation → Raw Processing Result → ProcessingRun → SourceFile, page, region, span, or another source anchor.

**Processing-result lineage example:** SPR node → NormalizedObservation → ProviderObservation → Raw Processing Result → ProcessingRun → SourceFile, page, region, span, or another source anchor.

These are conceptual examples. Not every provider or content type must instantiate every intermediate concept. Implementations may use references, mappings, edges, indexes, lookup services, or other representations. They do not define an EvidenceReference schema. SCV content must preserve sufficient lineage to explain supporting evidence. Construction, summarization, and canonical selection must not sever grounding.

**Explicit exclusions:** Evidence identity excludes storage location mechanics, temporary artifact URLs, provider IDs as Atlas business identity, and presentation citation formatting.

**Relationship to Raw Result or Observations:** Raw Result is retained evidence of provider output. ProviderObservation is a provider assertion. NormalizedObservation is an Atlas-normalized assertion that should remain traceable to provider and source evidence where available.

**Relationship to Structured Processing Result:** Structured Processing Result may contain evidence links or references sufficient to preserve normalized processing traceability.

**Relationship to Structured Content Version:** Structured Content Version content must remain evidence-traceable. SCV construction may transform, consolidate, or summarize information, but it must not sever evidence lineage. Canonical selection may select among SCVs, but it must preserve the grounding and lineage of the selected version.

**Relationship to Application Projections:** Applications may cite evidence but do not own evidence truth.

**Authority considerations:** StorageReference is location mechanics, not evidence identity. Provider block IDs may be retained as provenance or evidence anchors but must not become Atlas business identity by default.

**Lifecycle and versioning considerations:** Evidence references may be resolved or enriched over time, but accepted content lineage must preserve what evidence supported the accepted version.

**Overlap risks:** Mixing evidence identity with storage location can make byte movement appear to change semantic grounding. Mixing provider identifiers with Atlas identity can make provider payload structure a hidden business contract.

**Primary semantic ownership rules:** Processing Core owns evidence needed for truthful normalized output; Document Core owns durable evidence semantics for accepted content and assessment; Storage owns byte mechanics; Applications own citation and disclosure behavior only.

### Processing Provenance

**Responsibility:** describe how information was produced, transformed, normalized, rebuilt, assessed, or canonicalized.

**Central question:** How, when, and through what process was this result produced?

**Representative concepts:** ProcessingRun, provider, provider profile, model or engine version, request or job identity, processing attempt, retry relationship, timestamps, normalizer name and version, transformation version, schema version, builder version, canonicalization operation, and projection generation version.

**Explicit exclusions:** Processing Provenance excludes source evidence identity, evidence grounding, accepted content authority, application disclosure, and generic everything-else metadata.

**Relationship to Raw Result or Observations:** Processing provenance records the process that produced Raw Result and observations. Evidence and Grounding answers what source material supports an assertion; Processing Provenance answers what process produced the assertion.

**Relationship to Structured Processing Result:** Processing Core owns execution and normalization provenance, including ProcessingRun identity, provider execution, Raw Result association, retry, and normalizer version.

**Relationship to Structured Content Version:** Document Core owns provenance for assessment, Structured Content Version construction, acceptance, and canonicalization.

**Relationship to Application Projections:** Applications own projection-generation provenance.

**Authority considerations:** Processing Core semantically owns ProcessingRun execution identity, provider execution status, request/job and attempt identity, retry lineage, Raw Processing Result association, normalizer identity and version, and execution and normalization provenance. Document Core owns assessment provenance, SCV construction provenance, acceptance and rejection provenance, canonical-selection provenance, and accepted-content lineage. A future shared-persistence or Document Core-related milestone may implement durable ProcessingRun and observation storage, but implementation location must not transfer semantic ownership. Document Core must not be described as the owner of all provider orchestration or execution lifecycle behavior.

**Lifecycle and versioning considerations:** A later processing attempt, normalizer version, assessment version, builder version, or projection version must be distinguishable from earlier ones.

**Overlap risks:** Combining evidence and provenance into a generic bucket can obscure whether a statement is supported by source material or merely produced by a process.

**Primary semantic ownership rules:** Processing Core owns execution and normalization provenance; Document Core owns accepted-content governance provenance; Applications own projection-generation provenance.

### Assessment and Acceptance

**Responsibility:** represent Atlas-added evaluation, diagnostics, review, acceptance, and governance information.

**Central question:** How does Atlas evaluate, diagnose, accept, reject, promote, or select information?

**Representative concepts:** processing outcome facts, diagnostics, warnings, errors, completeness, page coverage, page mapping validity, schema validity, confidence, quality signals, conflicts, alternatives, severity, review state, acceptance state, rejection, promotion eligibility, selected state, superseded state, and canonical state.

**Explicit exclusions:** Assessment and Acceptance excludes application disclosure text, visual warning badges, rendering policy, provider success as acceptance, and a required universal quality score.

**Relationship to Raw Result or Observations:** Provider and normalized observations may contain defects, alternatives, or uncertainty that inform assessment. Those facts do not by themselves accept or reject shared content.

**Relationship to Structured Processing Result:** Processing outcome facts are owned by Processing Core when required to truthfully represent processing behavior. Examples include normalization failure, malformed block, missing field, page with no usable semantic content, partial result, and no usable output.

**Relationship to Structured Content Version:** Document Core owns completeness assessment, structural confidence, mapping validity, recovery severity, quality model, promotion eligibility, acceptance or rejection, canonicalization readiness, and selected canonical state.

**Relationship to Application Projections:** Application disclosure is owned by Application Projection and Presentation. Examples include Reader warning, degraded-page badge, partial-document message, expanded diagnostic detail, and flashcard-quality disclosure.

**Authority considerations:** Assessment does not alter underlying evidence. Provider success does not imply acceptance. Structured Processing Result validity does not imply canonical selection. Quality need not be reduced to one universal score.

**Lifecycle and versioning considerations:** Reprocessing must not silently replace selected or user-corrected Structured Content Version content. Incompatible acceptance behavior requires explicit versioning.

**Overlap risks:** If application warnings or badges are treated as assessment authority, presentation may become a hidden governance layer.

**Primary semantic ownership rules:** Processing Core owns processing outcome facts; Document Core owns assessment and acceptance; Application Projection and Presentation own disclosure.

## Diagnostics and Quality Compatibility

Current and future diagnostics should coexist without redefining released Processing Core semantics.

The repository currently contains or anticipates normalization diagnostics, Structured Processing Result warnings, coarse quality summary, page-level degraded-page diagnostics, document-level partial-recovery diagnostics, and Recovery Presentation Architecture.

The compatibility-safe position is:

- Processing outcome facts required for truthful Structured Processing Result representation may remain in Processing Core.
- Post-release diagnostic runtime representations may remain if additive and semantically compatible.
- Document Core may consume those facts into a richer assessment model.
- Application disclosure must remain derived.
- Future incompatible diagnostic or validation semantics require a new version or explicit compatibility decision.

This document does not require removal of current post-release diagnostics and does not describe them as canonical content.

## Aspect Distribution Across Layers

This table is conceptual. It does not prescribe object nesting, fields, tables, services, external interfaces, or storage systems.

| Aspect | Raw Result / Observations | Structured Processing Result | Structured Content Version | Application Projection |
|---|---|---|---|---|
| Identity and Versioning | Provider-return identity, processing attempt identity, provider and normalized assertion identity | Processing-result identity, schema version, normalized entity identity, normalizer lineage | Content version identity, lineage, proposal, acceptance, selection, supersession, canonical pointer | Projection identity, projection version, application-specific lineage |
| Content | Provider-native content evidence and provider assertions | Normalized candidate content | Versioned, application-independent content governed by Document Core; an Accepted SCV contains accepted shared content, while canonical status requires explicit selection | Derived summaries, reading text, cards, translations, notes, or other application content |
| Structure | Provider-detected layout, order, and relationship assertions | Normalized candidate page topology, hierarchy, order, and alternatives | Versioned, application-independent structure and order governed by Document Core; an Accepted SCV contains accepted structure, while canonical structure or order belongs to the explicitly selected Canonical SCV | Purpose-specific order, grouping, navigation, and interaction structure |
| Evidence and Grounding | Source and provider-return evidence, provider assertions, source anchors | Evidence links or grounding for candidate interpretations | Preserved grounding for accepted content and structural decisions | Citations and disclosure references derived from approved grounding |
| Processing Provenance | Provider execution, model or engine version, request or job identity, processing attempt, retry | Normalization provenance and processing-run association | Assessment, construction, acceptance, and canonicalization provenance | Projection generation provenance |
| Assessment and Acceptance | Provider defects or uncertainty that may inform evaluation | Processing outcome facts, warnings, partial or invalid result facts, quality facts | Assessment, acceptance, rejection, promotion eligibility, selected or canonical state | Application disclosure, warning presentation, and application-specific quality messaging |

## Normalization and Canonicalization

Raw Result to Structured Processing Result is provider-specific normalization and Atlas interpretation. Structured Processing Result to Structured Content Version construction is distinct from canonical selection.

### SPR-to-SCV Construction

SPR-to-SCV construction may include assessment, content construction, structure construction, evidence-lineage preservation, creation of proposed SCVs, and acceptance or rejection decisions. Creating an SCV does not make it canonical. Accepting an SCV does not necessarily make it canonical. A valid Structured Processing Result does not imply an accepted or canonical Structured Content Version. A successful provider run does not make content canonical, and a valid Structured Processing Result may still be incomplete or unsuitable for promotion.

### Canonical Selection

Canonical selection is a separate explicit governance action over one or more SCVs. Canonical selection may occur later and may change through explicit reselection or supersession. Canonical selection must not mutate prior immutable SCVs. This document does not define a canonical-selection method.

Reprocessing creates new versions rather than silently mutating accepted history. User or system corrections create new Structured Content Versions rather than editing prior immutable versions in place.

## Authority, Durability, and Rebuildability

Authoritative does not mean absolute truth. It means authoritative for a specific responsibility.

Original Source is authoritative evidence of what was submitted. Raw Result is authoritative evidence of what the provider returned. ProviderObservation is a provider assertion. NormalizedObservation and Structured Processing Result are Atlas interpretations. Assessment is an Atlas evaluation. A Selected SCV is Atlas's current selected shared content for a lineage under an explicit selection decision. A Canonical SCV is the currently canonical shared version for a lineage, while SCV identity and acceptance can exist without canonical status. Application Projection is derived and rebuildable or explicitly versioned.

This document does not prescribe retention periods or storage implementation. Durability and rebuildability must be decided according to the authority and lifecycle of each information responsibility.

## Structured Document Terminology

Atlas preserves the product principle: Atlas = Structured Documents + Applications built on top of them.

Structured Document is a product and domain concept. It is not a commitment to one object, one tree, one graph, one serialized payload, one relational schema, one file format, or one external response.

Use Structured Processing Result for provider-independent normalized processing output. Use Structured Content Version for immutable, versioned, application-independent content governed by Document Core. Applications normally consume accepted SCVs or Application Projections derived from them. Do not rename Structured Processing Result. Do not rename Structured Content Version.

The word Asset must be qualified by architectural role whenever context is ambiguous. Source Asset belongs to submitted or registered evidence. Processing Asset is generated or retained during provider processing or normalization. SCV Asset is application-independent content, or a reference associated with an SCV, governed by Document Core. Its acceptance and canonical relevance follow the state and governance of the associated SCV. Application Asset supports an application-specific projection. Presentation Asset supports rendering or delivery. Different semantic assets may reference the same underlying bytes. Shared bytes do not imply shared semantic identity. Storage identity does not determine architectural role. Unqualified Asset is allowed only where its role is unambiguous. This document does not define Asset fields or storage.

## Metadata Terminology

Metadata is not a seventh top-level information aspect.

Local contracts and implementations may use fields called metadata. Every metadata item must have a primary semantic owner. Metadata must not become an everything-else category.

Examples:

- provider version belongs to Processing Provenance;
- page region belongs to Evidence and Grounding;
- node type belongs to Structure;
- quality warning belongs to Assessment or to a Processing Core outcome fact, depending context;
- canonical state belongs to Assessment and Acceptance;
- page language belongs to Content if observed, or Assessment if inferred or evaluated;
- schema version belongs to Identity and Versioning;
- storage path belongs to storage mechanics, not semantic metadata ownership.

Where ownership depends on context, future contracts must say so explicitly.

## Extension and Review Rules

Every new information concept should answer these architecture review questions before representation work begins:

1. Which information aspect is its primary semantic owner?
2. At which architectural layer is it first created?
3. Is it source evidence, provider assertion, Atlas interpretation, processing outcome fact, assessment, accepted content, canonical-selection state, or application projection?
4. What is its authority?
5. Is it immutable, versioned, replaceable, or rebuildable?
6. What evidence or lineage must it preserve?
7. Can it affect acceptance or canonical selection?
8. Is it application-independent?
9. Does it accidentally prescribe a physical representation?
10. Does it belong in Document Core at all?

Each concept must have one primary semantic owner. It does not need one physical container.

## Relationship to Future Milestones

This document does not approve, close, rename, renumber, or reassign milestones. Milestone realignment is a later approved task.

Processing Core v1.0 is the released lower-level baseline. Future Document Core work should define semantic ownership, evidence, provenance, assessment, and accepted-content governance. Future persistence work should preserve the ownership distinction between Processing Core execution provenance and Document Core evidence or accepted-content lineage. A future shared-persistence or Document Core-related milestone may implement durable ProcessingRun and observation storage without transferring provider execution semantics, retry authority, request/job authority, or orchestration lifecycle ownership away from Processing Core.

The SCV conceptual model is defined by this architecture document, while Structured Content Version contracts, persistence, construction, assessment, acceptance, and canonical-selection implementation remain future work. Smart Reading applications remain consumers of Accepted SCVs or Application Projections. Smart Archive remains dependent on evidence-backed accepted content and retrieval foundations.

## Historical Task and Document Status

Task completion status and current document treatment are separate dimensions. An architecture task may have completed its documentation deliverable, while the resulting document may later require amendment, splitting, or alignment.

Later document treatment must not retroactively mark the original task incomplete without evidence. This document does not update milestone status and does not describe M3-001A as incomplete merely because a related document may need later alignment.

## Relationship to Existing Documents

This model complements these existing documents and does not modify them:

- `docs/contracts/structured-processing-result-v1.md`;
- `docs/architecture/document-core-structured-content-architecture.md`;
- `docs/architecture/atlas-provider-conformance-profile-v1.md`;
- `docs/architecture/atlas-block-recovery-contract-v1.md`;
- `docs/adr/ADR-0001-mixed-multi-page-recovery-policy.md`;
- `docs/architecture/recovery-presentation-architecture.md`;
- `docs/architecture/document-processing-contract.md`;
- `docs/architecture/canonical-data-flow.md`;
- `docs/storage/digital-object-taxonomy.md`.

Later alignment may be needed where terminology, status labels, or scope assumptions differ. Such alignment must preserve released Processing Core authority unless a future versioned compatibility decision explicitly changes it.

## Non-goals

This document does not define serialization schemas, protobuf contracts, Python models, TypeScript types, object models, tables, migrations, repositories, storage paths, StorageReference format, service boundaries, external interfaces, routes, workers, provider adapters, exact diagnostic fields, exact quality formulas, detailed EvidenceReference attributes, detailed Structured Content Version attributes, canonical-selection methods, user interfaces, Reader Stream Text, Speed Reading presentation, Flashcard schema, Mind Map schema, Notes schema, archive user interfaces, search-index design, embedding design, retrieval-augmented generation implementation, authorization implementation, or final milestone numbering.

This document does not include implementation examples that imply a preferred schema.

## Decision Summary

This proposed model defines semantic responsibilities, not physical containers. Semantic ownership is distinct from physical ownership, and cross-layer references do not transfer authority. The six information aspects are Identity and Versioning, Content, Structure, Evidence and Grounding, Processing Provenance, and Assessment and Acceptance.

Document Core is not one mandatory sequential runtime stage. Metadata is not a catch-all top-level aspect. Evidence and Grounding is distinct from Processing Provenance. Processing execution provenance remains distinct from Document Core accepted-content governance. Assessment and Acceptance is distinct from application disclosure.

Structured Processing Result and Structured Content Version remain separate. SCVs may be proposed, accepted, rejected, selected, superseded, or canonical, and canonical status requires explicit selection. Atlas Processing Core v1.0 semantics remain unchanged. Applications consume Structured Content Versions or derived projections without taking ownership of SCV content, evidence truth, assessment authority, or canonical state. Implementation representations and milestone numbering remain deferred.
