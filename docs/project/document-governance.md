# Atlas Documentation Governance

Authority, Lifecycle, Supersession, and Historical Record Policy

| Field | Value |
|---|---|
| Document Type | Project Governance |
| Approval Status | Accepted |
| Lifecycle Status | Active |
| Version | 0.1 |
| Date | 2026-07-18 |
| Effective Date | 2026-07-18 |
| Authority Domain | Documentation governance only |
| Applies To | Files under `docs/` |
| Supersedes | None |
| Related Milestones | None |
| Release Baseline | None |

This policy is the accepted documentation-governance policy for Atlas.
Approval Status and Lifecycle Status are separate dimensions: `Accepted` means
the policy is approved as authoritative within the documentation-governance
domain, while `Active` means it is currently maintained and applicable.

## Governance Principles

### Domain-specific authority

There is no single global document ranking. Authority depends on the question
being asked.

Examples:

- Contract governs verifiable behavior.
- Architecture governs conceptual boundaries.
- ADR governs a decision within declared scope.
- Release records what was actually released.
- Milestone governs delivery scope and declared state.
- Roadmap governs sequencing and dependency direction.
- Review preserves point-in-time evidence.
- Implementation and tests may describe current behavior but do not silently
  redefine normative intent.

### Status affects authority

Strong wording such as must, required, canonical, source of truth, or
authoritative does not by itself grant authority. Document Type, Approval
Status, Lifecycle Status, Release Status, authority domain, and explicit scope
must be considered.

### Released-baseline preservation

Later proposals, implementation drift, roadmap updates, or milestone wording
must not silently rewrite released behavior. Historical release facts remain
true even after later compatibility changes. A compatibility-significant
replacement requires an approved versioned contract, ADR, release, or other
explicit governance action. Absence of a locally verified tag must not be
represented as a verified tag.

### No implied supersession

Newer commit date, stronger wording, more links, or broader scope does not
supersede an existing document. Supersession must be explicit and directional.

### Semantic authority is not directory authority

Directory location improves discovery but does not create semantic authority. A
domain-local review remains a review. A contract-like file outside
`docs/contracts` does not automatically become an accepted contract.

### Preserve history

Reviews, audits, smoke results, preflight reports, release notes, and
current-state reviews preserve point-in-time evidence. Do not rewrite historical
findings merely to match later architecture.

## Authority Dimensions

### Normative authority

Normative authority describes what the system, project, process, or contract is
intended or required to do. Examples include an Accepted Contract, an Accepted
ADR, and Accepted Architecture within its domain. Accepted governance or process
guidance may have normative authority within its declared domain. Lifecycle
Status `Active` indicates current applicability but does not itself grant
approval or normative authority. A Proposed + Active document remains advisory.

### Descriptive authority

Descriptive authority describes what the repository or implementation currently
appears to do. Implementation, tests, fixtures, and reviews may provide
descriptive evidence. When no Accepted Contract or Accepted Architecture exists,
implementation may be the best available evidence of current behavior, but it
does not automatically become the normative specification.

### Historical authority

Historical authority describes what was observed, reviewed, accepted, completed,
or released at a particular time. Examples include a Release, review, audit,
smoke result, and milestone closeout evidence.

These authority dimensions answer different questions and must not be treated as
overriding one another globally.

## Document Types and Authority Domains

| Document Type | Primary Purpose | Normative Potential | Primary Authority Domain | Cannot Silently Override |
|---|---|---|---|---|
| Release | Record what was actually included and released. | Limited; records release facts and included baselines. | Historical identification of the released commit, verified tag when present, and the contracts, ADRs, tests, and evidence included or referenced by that release. | Contracts, ADRs, or architecture semantics merely by describing them. |
| Contract | Define verifiable behavior. | Yes, when Accepted and versioned. | Schemas, protocols, compatibility, conformance, and externally observable behavior. | Released baselines, accepted ADR decisions outside scope, or architecture ownership. |
| ADR | Record a decision. | Yes, when Accepted. | Explicit decision scope, rationale, consequences, and rejected alternatives. | Entire architecture or contract domains unless scope says so. |
| Architecture | Define conceptual boundaries. | Yes, when Accepted. | Semantic ownership, layers, responsibilities, and conceptual model. | Accepted Contract behavior or released history. |
| Milestone | Define delivery work. | Yes, for milestone scope and declared state. | Work scope, task relationships, acceptance evidence, and declared milestone state. | Contracts or architecture; they must be cited rather than redefined. |
| Roadmap | Sequence work. | Limited. | Sequencing, dependency rationale, and direction. | Milestone completion, contracts, ADRs, or release facts. |
| Planning | Explore options and future work. | No, unless promoted. | Advisory plans and proposals. | Accepted documents. |
| Review | Preserve findings. | No, except cited normative sources. | Point-in-time evidence and recommendations. | Current normative authority merely through must/required wording. |
| Historical Record | Preserve evidence. | No, except historical claims. | What was observed, reviewed, completed, or released at a time. | Current contracts, ADRs, architecture, or milestones. |
| Engineering Design | Guide engineering work. | Yes, when Accepted; Active indicates current applicability. | Workflow, development practice, and operational engineering guidance. | Contracts, accepted ADRs, released baselines, or technical domains outside scope. |
| Processing Design | Guide processing implementation. | Yes, when Accepted; Active indicates current applicability. | Internal processing design, procedures, fixtures, and evidence. | Contracts, accepted ADRs, released baselines, or conceptual ownership outside scope. |
| Database Design | Guide database implementation. | Yes, when Accepted; Active indicates current applicability. | Schema, migration, and persistence design. | Architecture ownership, contracts, or release facts. |
| Storage Design | Guide storage implementation. | Yes, when Accepted; Active indicates current applicability. | Storage mechanics, references, and storage design. | Semantic ownership, contracts, accepted ADRs, or released baselines. |
| Testing | Guide validation. | Yes, when Accepted; Active indicates current applicability. | Test/CI strategy, plans, compatibility evidence, and validation policy. | Contracts defining behavior or release history. |
| Product | Define product intent. | Limited. | Product goals and user-facing capability framing. | Technical protocol semantics. |
| Project Governance | Define process. | Yes, when Accepted; Active indicates current applicability. | Approval process, documentation governance, repository process, and decision procedure. | Technical contracts, ADR decisions, or release history. |
| Reference / Glossary | Aid navigation and vocabulary. | Limited. | Approved aliases, navigation, and concise definitions. | Architecture, Contracts, or ADRs. |

A Release records what was actually included and released. It does not create new
technical semantics merely by describing them. It should identify commit, tag
when verified, contracts, ADRs, tests, and evidence where available. Release
authority and Contract, ADR, and Architecture authority answer different
questions.

An Accepted, versioned Contract governs verifiable behavior, schemas, protocols,
compatibility, and conformance. Implementation drift does not silently update it.

An Accepted ADR governs only its explicit decision scope. It does not govern an
entire architecture or contract domain unless its scope says so.

Accepted Architecture governs conceptual boundaries, semantic ownership, layers,
and responsibilities. Proposed Architecture is advisory. Architecture must not
silently rewrite Accepted Contract behavior or released history.

Milestone documents govern work scope, task relationships, acceptance evidence,
and declared milestone state. They must cite rather than redefine contracts or
architecture.

Roadmap governs sequencing, dependency rationale, and direction. Roadmap must not
be the sole authority for milestone completion.

Planning is advisory unless promoted through an explicit approval process.

Reviews and historical records preserve evidence and recommendations. They do
not become permanent normative authority merely because they contain must or
required wording.

Engineering, Processing, Database, Storage, Testing, and Project Governance
documents may be normative within their operational or implementation domain
when Accepted. Lifecycle Status `Active` indicates current applicability but
does not by itself grant normative authority. They cannot override Contract,
accepted ADR, released baseline, or conceptual ownership outside their domain.

Product documents govern product intent and user-facing capability framing, not
technical protocol semantics.

Project Governance governs approval process, documentation governance,
repository process, and decision procedure.

Glossary documents provide approved aliases, navigation, and concise
definitions. They do not override Architecture, Contracts, or ADRs.

## Document State Dimensions

Do not use one overloaded status field for every lifecycle concept. Atlas
document governance distinguishes Approval Status, Lifecycle Status, and Release
Status.

### Approval Status

Allowed values:

- Draft: early work, not ready for reliance.
- Proposed: reviewable candidate, advisory only.
- Accepted: approved authority within declared type, domain, and scope.
- Rejected: reviewed and not adopted.

### Lifecycle Status

Allowed values:

- Active: currently maintained or operationally applicable.
- Deferred: valid topic postponed.
- Completed: scoped work or task has completed.
- Historical: point-in-time record, not current normative authority.
- Superseded: explicitly replaced by a named successor.
- Deprecated: still compatibility-relevant or supported but discouraged.
- Archived: preserved but no longer maintained.

Not every value applies to every document type. Accepted and Active are not
mutually exclusive because they belong to different dimensions. Completed and
Historical may both be relevant to a milestone review through different
dimensions. Superseded does not erase historical evidence.

### Release Status

Allowed values:

- Unreleased: not part of an identified release baseline.
- Released: included in or explicitly associated with a release baseline.

Released is historical release status, not automatic current authority. A
Released Contract may later also be Deprecated or Superseded while remaining
historically released.

Tooling and metadata linting may later encode these dimensions, but this
document does not define a machine schema.

## Minimum Document Metadata

| Field | Required For | Purpose |
|---|---|---|
| Document Type | All maintained documents. | Identifies document responsibility without relying on directory placement. |
| Approval Status | All maintained documents. | Identifies Draft, Proposed, Accepted, or Rejected approval state. |
| Lifecycle Status | All maintained documents. | Identifies Active, Deferred, Completed, Historical, Superseded, Deprecated, or Archived lifecycle state. |
| Date | All maintained documents. | Provides a stable reference date. |
| Applies To or Scope | All maintained documents. | Limits applicability and prevents accidental broad authority. |
| Authority Domain | Normative documents. | States what the document may govern. |
| Version | Normative documents where compatibility or external behavior matters. | Supports contract and compatibility evolution. |
| Owners or responsible team | Normative documents. | Identifies maintenance and approval responsibility. |
| Related Contracts | Normative documents discussing runtime behavior. | Connects behavior claims to contract authority. |
| Related ADRs | Normative documents relying on decisions. | Connects design claims to decision authority. |
| Evidence Date or Review Date | Historical records. | Establishes point-in-time evidence. |
| Baseline commit/tag/environment | Historical records where relevant. | Defines inspected or released baseline. |
| Limitations or known gaps | Historical records where relevant. | Prevents overclaiming evidence. |
| Release Status | Documents associated with release baselines. | Separates release history from current authority. |
| Release Baseline | Release-associated documents. | Identifies commit/tag/evidence when available. |
| Supersedes | Superseding documents. | Names predecessors explicitly. |
| Superseded By | Superseded documents where practical. | Provides successor navigation. |
| Related Milestones | Documents tied to delivery scope. | Connects evidence and design to milestone context. |

Use a compact Markdown table for now. YAML front matter is not required. Later
tooling may introduce machine-readable validation. Metadata describes authority
and lifecycle but does not itself create approval. Adding metadata to an old
document must not silently change its status. The H1 title is sufficient; a
separate Title metadata field is not required.

## Supersession and Change Policy

### Full supersession

An accepted successor fully replaces a named authority domain. The successor
names the predecessor. The predecessor should name the successor through a dated
annotation where practical. A proposed successor cannot supersede an accepted
document.

### Partial supersession

Partial supersession must name exact sections, concepts, versions, or authority
domains affected. Unaffected content retains its prior authority if otherwise
valid.

### Amendment

An amendment updates or extends an accepted document. It records date, reason,
scope, and compatibility impact. Material contract changes normally require a
new version.

### Clarification

A clarification resolves wording ambiguity without changing semantics. It must
state that authority or behavior did not change.

### Historical annotation

A historical annotation adds later context or successor navigation. It preserves
original findings and must be visibly dated.

### Compatibility replacement

A compatibility replacement explicitly replaces earlier behavior through
versioned Contract, ADR, and release governance. It defines compatibility,
migration, deprecation, or breaking-change treatment and never erases the
historical release baseline.

## Historical Records

Historical records include reviews, audits, smoke results, fixture analyses,
preflight reports, current-state reviews, milestone closeout reviews, and release
notes.

Rules:

- include a stable date or as-of baseline;
- distinguish observed result from approval or authorization;
- preserve original findings;
- recommendations do not become normative unless promoted;
- current-state filenames may remain initially when metadata clarifies the as-of
  date;
- avoid immediate large-scale renaming;
- later successor links may be added as dated annotations;
- release notes are not rewritten to reflect later implementation.

This policy does not declare existing review files Historical.

## Directory Responsibilities

| Directory | Responsibility |
|---|---|
| `docs/README.md` | Navigation entrypoint for the documentation system. |
| `docs/adr` | Preferred central discovery location for future ADRs. |
| `docs/architecture/adr` | Existing domain-local ADRs may remain and be indexed. |
| `docs/architecture` | Conceptual architecture, boundaries, semantic ownership, layers, and responsibilities. |
| `docs/contracts` | Preferred location for new versioned behavior contracts. |
| `docs/database` | Database schema, migration, and persistence design; separate from storage. |
| `docs/engineering` | Engineering workflow and development practice. |
| `docs/milestones` | Milestone scope, task relationships, acceptance evidence, and declared state. |
| `docs/planning` | Advisory plans and future-work proposals. |
| `docs/processing` | Internal processing designs, procedures, fixtures, and evidence. |
| `docs/product` | Product intent and user-facing capability framing. |
| `docs/project` | Governance and glossary/reference documents. |
| `docs/releases` | Release records and released-baseline evidence. |
| `docs/reviews` | Central reviews, while domain-local reviews may remain. |
| `docs/roadmap` | Sequencing and dependency direction. |
| `docs/storage` | Storage mechanics and storage design. |
| `docs/testing` | Test/CI strategy, plans, and evidence. |

Existing contract-like architecture files may remain temporarily but should later
be typed and indexed. No immediate relocation is required. Index and metadata
work should precede relocation. Relocation requires a separate approved plan.

## Terminology Governance

Terminology has two distinct ownership dimensions.

### Conceptual Owner

The Conceptual Owner owns semantic meaning, architectural role, responsibility,
and relationships. The Conceptual Owner is usually Architecture, ADR, Product,
or Project Governance depending on the term.

### Representation / Behavior Owner

The Representation / Behavior Owner owns exact fields, payloads, protocol
behavior, validation, compatibility, or storage representation. The
Representation / Behavior Owner is usually Contract, Database Design, Storage
Design, or another scoped normative document.

A term may have different conceptual and representation owners. This does not
create competing authority when domains are explicit. Glossary aliases provide
navigation, not silent redefinition. Abbreviations must be defined on first
material use unless the document is a local continuation that clearly defines its
vocabulary. State-qualified terms must be used where state changes meaning.
Unqualified SCV must not silently mean Accepted SCV or Canonical SCV. Metadata
should be qualified by domain when ambiguity matters. Asset should be qualified
by architectural role when ambiguity matters. Canonicalization should distinguish
construction/transformation from explicit canonical selection where applicable.

This policy does not define all Atlas technical terms, replace the project
glossary, or change existing terminology.

## Approval and Adoption

This policy has been explicitly reviewed and accepted, with an effective date of
2026-07-18. Its authority is limited to documentation governance only. The
policy governs future documentation review, indexing, metadata annotation,
supersession handling, and remediation planning.

Adoption does not retroactively reclassify existing documents. Existing document
statuses remain unchanged until separate approved remediation changes them.
Accepting this policy does not accept any technical Architecture, Contract, ADR,
Roadmap, Milestone, Planning, Product, or implementation decision.

Future amendments require explicit review and an approved commit or PR. Material
governance changes should update the policy version.

## Adoption and Remediation Boundary

This policy does not immediately require:

- metadata headers on all existing documents;
- relocation of ADRs, contracts, or reviews;
- renaming files containing current;
- reclassifying all historical records;
- changing milestone status;
- changing roadmap sequencing;
- changing contract status;
- fixing broken references;
- rewriting terminology.

Those actions require separate, focused remediation batches.

Recommended future order:

1. governance approval;
2. navigation and indexes;
3. broken-reference corrections;
4. metadata annotations for highest-authority documents;
5. historical annotations;
6. terminology and authority alignment;
7. optional relocation last.

## Adoption Decision

- Decision: Accepted.
- Effective date: 2026-07-18.
- Authority domain: documentation governance only.
- This adoption approves the governance rules in this document.
- This adoption does not:
  - reclassify any existing document;
  - change any existing Approval Status, Lifecycle Status, or Release Status;
  - change milestone state;
  - change roadmap sequencing;
  - accept or reject any Architecture, Contract, ADR, Planning, Product, or
    other technical document;
  - modify released Processing Core semantics;
  - supersede any existing technical document;
  - authorize implementation;
  - repair references;
  - relocate documents.
- Remediation remains incremental and requires separate focused tasks and PRs.

## Non-goals

This policy does not:

- define technical architecture;
- define SPR or SCV contracts;
- modify Processing Core semantics;
- accept or reject Document Core proposals;
- change milestone state;
- change roadmap sequencing;
- declare existing documents superseded;
- authorize implementation;
- prescribe YAML or a machine schema;
- require immediate relocation;
- repair links;
- change release history.
