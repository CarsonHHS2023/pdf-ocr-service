# Paddle-VL Structured Result Normalizer

| Field | Value |
|---|---|
| Document Type | Normalizer Design |
| Authority Domain | Paddle-VL Raw Result normalization into provider-independent structured processing output |
| Applies To | `normalize_paddle_vl_raw_result`, `RawProcessingResultEnvelope`, retained Paddle-VL result bytes, `NormalizationOutcome`, SPR v1 runtime objects, recovery behavior, warnings, evidence, and validation scope |

## Scope

`app.processing.paddle_vl.normalizer.normalize_paddle_vl_raw_result` is the first
provider-specific retained-raw-result mapper.  It accepts an already hydrated
`RawProcessingResultEnvelope` plus the exact retained bytes and returns a
`NormalizationOutcome`: either a persistence-neutral SPR v1 runtime object or
safe, typed diagnostics. It does not retrieve Storage, call Paddle-VL, mutate
the raw result, persist anything, or select canonical content.

## Supported boundary and validation

The mapper supports the Paddle-VL `full` terminal profile and pipeline revision
`v1.6`. It validates provider identity and profile, unsafe metadata, exact byte
size and SHA-256, finite UTF-8 JSON, root shape, revision, terminal status,
page mappings, blocks, and the produced SPR references in that order. Any
failure before a valid result returns no SPR. Unknown revisions and profiles
are deliberately rejected rather than guessed.

## Mapping behavior

Pages use zero-based Atlas indexes and retain source page number, dimensions,
and right-angle rotation. Rectangles are normalized to displayed page-space;
only a one-millionth rounding excursion is clipped. Non-finite, degenerate,
and materially out-of-range geometry is rejected. Missing page coverage after
usable mapped blocks produces `partial` with a page-failure warning; duplicate
or invalid mappings produce no SPR.

The mapper emits observations, nodes, page roots, centralized evidence links,
and local ordinals for titles/headings, text, lists/list items, tables, figures,
formulas, captions, headers, footers, footnotes, and unknown blocks. Unknown
classes receive an `unknown` node, evidence, warning, and a minimal namespaced
extension. Tables are unstructured unless cells are retained. Figures never
create an asset from crop metadata and warn when no retained crop asset exists.
Formulas retain supplied text and LaTex only. Confidence and geometry remain
absent when absent.

## Determinism and security

Callers inject an ID factory and clock; production defaults are opaque UUID-like
IDs and UTC time. Serialization is UTF-8 NFC, sorted-key compact JSON with a
single trailing newline and rejects non-finite values. The normalizer never
copies provider payloads, URLs, local paths, credentials, or unsafe metadata
into SPR output.

## Deferred and verification

Structured Content, canonical selection, Reader integration, persistence,
asset retrieval, embedded-text alternatives, MinerU-Popo, and synchronous
no-job-provider generalization remain out of scope. Tests use committed
synthetic fixtures only; no live provider or private raw result verification
was performed.
