# S0 Benchmark Fixture Registry v1

| Field | Value |
|---|---|
| Document Type | Test / Benchmark Registry |
| Scalability Phase | S0 — Baseline and observability |
| Product Relationship | M5 Reader MVP reliability / horizontal scalability |
| Registry Version | v1 |
| Date | 2026-08-23 |
| Status | Active; representative reruns still required |

## Purpose

Define stable privacy-safe benchmark classes for Atlas S0 without committing book titles, filenames, document text, signed URLs, credentials, or storage references.

Exact source SHA-256 is read from `SourceFile.checksum_sha256` by the operator-side report tool and should be retained with private benchmark evidence when exact replay identity is required. It is intentionally not copied into this public repository registry.

## Registry

| Fixture id | Type | Size class | Expected pages | Reference byte size | Current evidence state | Intended use |
|---|---|---|---:|---:|---|---|
| `pdf-small-v1` | PDF | small | 1 | 784,772 | Historical retained ProcessingRun exists | Fast end-to-end control; route/timing sanity |
| `pdf-medium-v1` | PDF | medium | 11 | 4,558,903 | Historical retained ProcessingRun exists | Multi-page routing/Provider/Reader baseline |
| `pdf-large-v1` | PDF | large | 528 | 65,445,424 | Source retained; current Document is nonterminal and has no ProcessingRun | Large-memory/network/long-run baseline after explicit rerun approval |
| `txt-small-v1` | TXT | small | n/a | 89,396 | Historical run exists, but lifecycle timestamps are not suitable for timing baseline | TXT correctness/control baseline |
| `txt-medium-v1` | TXT | medium | n/a | 202,256 | Historical run exists, but lifecycle timestamps are not suitable for timing baseline | Larger TXT control baseline |

Reference byte size is a guardrail, not source identity. Before recording a new authoritative benchmark result, the operator should confirm the intended private source identity and record the actual source checksum in the private run evidence.

## Required run record

Each accepted S0 benchmark run should record at least:

- fixture id and registry version;
- backend Git revision / Staging runtime revision;
- processing run id and document id in private evidence;
- source SHA-256 in private evidence;
- source byte size and page count where applicable;
- generated `atlas.s0.baseline.v1` snapshot;
- whether the durable event window was complete;
- missing required metrics as explicit `not_instrumented` / `not_available` values;
- any manual log-derived metric, with its exact event name and field, kept separate from durable metrics.

## Privacy and safety rules

- Do not commit filenames, titles, text excerpts, signed URLs, bearer tokens, bucket credentials, request/response bodies, or raw Provider payloads.
- Do not treat client-supplied hash values as authoritative source identity.
- Do not rerun the large fixture merely to fill a table. Large-run execution remains an explicit Staging test action because it consumes significant CPU/GPU/provider resources.
- Historical lifecycle timestamps may be retained as preliminary evidence but must not be relabeled as measurements they do not represent.

## Versioning

Change this registry version when the source fixture set or benchmark class materially changes. A new pipeline/runtime version does not by itself require a new fixture-registry version; it should instead produce a new baseline result against the same fixture identities where possible.
