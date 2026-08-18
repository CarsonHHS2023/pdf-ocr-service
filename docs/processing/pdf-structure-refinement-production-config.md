# PDF Structure Refinement Production Configuration

The PDF structure-refinement stage is optional. It remains disabled unless both provider settings are present:

- `PDF_STRUCTURE_REFINEMENT_OPENAI_API_KEY`
- `PDF_STRUCTURE_REFINEMENT_OPENAI_MODEL`

Never commit the API key or print it in logs, health responses, metrics, or diagnostics.

## Recommended starting configuration

```text
PDF_STRUCTURE_REFINEMENT_OPENAI_MODEL=gpt-5.6-sol
PDF_STRUCTURE_REFINEMENT_TIMEOUT_SECONDS=60
PDF_STRUCTURE_REFINEMENT_MAX_ATTEMPTS=3
PDF_STRUCTURE_REFINEMENT_INITIAL_BACKOFF_SECONDS=0.5
PDF_STRUCTURE_REFINEMENT_MAX_BACKOFF_SECONDS=8
PDF_STRUCTURE_REFINEMENT_MAX_CONCURRENT_BATCHES=2
PDF_STRUCTURE_REFINEMENT_GLOBAL_MAX_CONCURRENT_BATCHES=4
PDF_STRUCTURE_REFINEMENT_MAX_PAGES_PER_BATCH=16
PDF_STRUCTURE_REFINEMENT_MAX_IMAGE_DIMENSION_PIXELS=1400
PDF_STRUCTURE_REFINEMENT_JPEG_QUALITY=72
PDF_STRUCTURE_REFINEMENT_MAX_IMAGE_BYTES=1500000
```

Use the explicit `gpt-5.6-sol` model ID for the flagship GPT-5.6 tier. The shorter `gpt-5.6` alias currently routes to the same Sol tier, but the explicit ID makes production logs and configuration intent clearer. The provider uses the Responses API; GPT-5.6 defaults to medium reasoning effort when `reasoning.effort` is omitted, which is the recommended initial quality/latency balance for this bounded structure-review workload.

These values are conservative defaults, not universal capacity targets. Tune them using the emitted `PDF_STRUCTURE_REFINEMENT_DOCUMENT_METRICS` event and provider rate-limit behavior.

## Confidence policy

Confidence thresholds are operation-specific:

| Operation class | Default threshold | Rationale |
|---|---:|---|
| `set_toc_level` | `0.85` | TOC hierarchy is bounded, reversible presentation metadata; this accepts a supported `0.88` hierarchy decision without weakening unrelated operations. |
| Other structure operations | `0.90` | Reclassification, parent changes, and artifact suppression can alter document semantics more broadly. |
| `correct_text` | `0.97` | OCR text replacement requires the strongest visual evidence. |

A confidence exactly equal to the threshold is applied. Lower-confidence operations remain in `metadata.llm_structure_refinement` with `applied=false` for auditability.

## Configuration reference

| Variable | Default | Validation | Purpose |
|---|---:|---|---|
| `PDF_STRUCTURE_REFINEMENT_OPENAI_MODEL` | none | Non-empty model ID when API key is configured | OpenAI model used by the Responses API. Recommended: `gpt-5.6-sol`. |
| `PDF_STRUCTURE_REFINEMENT_TIMEOUT_SECONDS` | `60` | Positive number | Timeout applied to each provider batch attempt and the outer batch execution boundary. |
| `PDF_STRUCTURE_REFINEMENT_MAX_ATTEMPTS` | `3` | Positive integer | Maximum provider attempts for retryable network, 408, 409, 429, and selected 5xx failures. |
| `PDF_STRUCTURE_REFINEMENT_INITIAL_BACKOFF_SECONDS` | `0.5` | Non-negative number | Initial exponential retry delay. |
| `PDF_STRUCTURE_REFINEMENT_MAX_BACKOFF_SECONDS` | `8` | At least the initial backoff | Caps exponential delay and bounded `Retry-After` handling. |
| `PDF_STRUCTURE_REFINEMENT_MAX_CONCURRENT_BATCHES` | `2` | Positive integer | Maximum concurrent batches for one document. |
| `PDF_STRUCTURE_REFINEMENT_GLOBAL_MAX_CONCURRENT_BATCHES` | `4` | Positive integer | Process-wide limit across documents and event loops. It cannot change after first initialization. |
| `PDF_STRUCTURE_REFINEMENT_MAX_PAGES_PER_BATCH` | `16` | Positive integer | Maximum rendered pages included in one provider request. All selected pages are processed across multiple batches. |
| `PDF_STRUCTURE_REFINEMENT_MAX_IMAGE_DIMENSION_PIXELS` | `1400` | Integer at least `256` | Maximum longest edge for each rendered JPEG. Images are never enlarged above the source page size. |
| `PDF_STRUCTURE_REFINEMENT_JPEG_QUALITY` | `72` | Integer from `20` through `95` | Initial JPEG quality. Rendering lowers quality in bounded steps when necessary. |
| `PDF_STRUCTURE_REFINEMENT_MAX_IMAGE_BYTES` | `1500000` | Integer at least `32000` | Maximum encoded JPEG bytes per page before base64 conversion. |
| `PDF_STRUCTURE_REFINEMENT_OPENAI_ENDPOINT` | OpenAI Responses API endpoint | HTTPS URL | Optional provider endpoint override. |

## Tuning guidance

Increase `MAX_PAGES_PER_BATCH` only when the provider request-size limit and latency remain acceptable. More pages per request reduce request count but increase payload size, model latency, and failure blast radius.

Reduce `MAX_IMAGE_DIMENSION_PIXELS`, `JPEG_QUALITY`, or `MAX_IMAGE_BYTES` when requests are too large. Lower image fidelity can reduce the model's ability to distinguish faint OCR artifacts, indentation, and small heading text, so change one setting at a time.

Keep per-document concurrency lower than or equal to the process-wide limit. For example, with `2` per document and `4` process-wide, two documents can normally use two batches each without exceeding the process budget.

Treat repeated 429s as a capacity signal. Prefer reducing process-wide concurrency before increasing retries or backoff. Retries consume the same provider quota and remain bounded by the outer batch timeout.

## Failure behavior

The default canonicalization path is fail-open. A failed batch is omitted while successful batch patches are merged, conflict-checked, applied deterministically, and validated as SPR v2. If every batch fails, the original recovered document remains available.

No configuration allows the model to replace the complete document. The provider may only propose bounded operations against existing node IDs.

## Observability

Use `PDF_STRUCTURE_REFINEMENT_DOCUMENT_METRICS` to track:

- total and successful/failed batch counts;
- provider failures and retries;
- 429, 5xx, and provider-unavailable counts;
- final operation count;
- total document-refinement duration.

The event intentionally excludes API keys, endpoint URLs, document IDs, node IDs, OCR text, images, and provider response bodies.
