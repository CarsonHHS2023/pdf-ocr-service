# PDF visual asset LLM enhancement

This optional post-crop stage evaluates eligible non-cover PDF `figure` and `table` crops for conservative image-model cleanup before the Structured Content v2 Candidate is persisted.

## Eligibility and resolution protection

A crop is sent to the image-editing provider only when all of the following are true:

- the node is a non-cover `figure` or `table`;
- visual enhancement is explicitly enabled and configured;
- the crop can fit one of the supported provider canvases without reducing its native pixel dimensions:
  - `1024x1024`;
  - `1536x1024`;
  - `1024x1536`.

If a dense table or large figure exceeds every supported canvas, enhancement is skipped before any provider request. The original high-resolution crop remains the available `NORMALIZED` rendition used by Reader. This prevents fine text and table detail from being downsampled for the provider and then enlarged again.

## Processing contract

For each eligible crop, the provider is instructed to:

- neutralize gray or pale-yellow paper tint caused by scanning, photography, aging, or exposure;
- remove reverse-side bleed-through/show-through;
- remove scan speckles, dust, stains, smudges, and isolated noise;
- apply restrained contrast, sharpness, and edge cleanup;
- preserve all real text, Chinese characters, numbers, decimal points, table values, axes, arrows, lines, curves, symbols, legends, layout, geometry, and framing;
- never redesign, translate, infer, invent, omit, crop, or rearrange source content.

Cover pages are excluded. They continue to use the existing full-page source rendering, with a local raw-crop fallback if full-page cover rendering cannot be persisted.

## Persistence and Reader delivery

The enhanced PNG bytes are stored through the configured `StorageProvider`. The immutable Structured Content v2 Candidate stores the asset and rendition records in the database, including the enhanced storage reference, checksum, model ID, provider, prompt version, and cleanup audit metadata.

A successfully enhanced asset contains:

- a `NORMALIZED` rendition for the enhanced PNG;
- an `OCR_SOURCE` rendition for the original unedited PDF crop retained as evidence and fallback.

Database reconstruction does not guarantee that rendition IDs retain their originally declared order. Reader v2 therefore selects eligible renditions by semantic role rather than ID or persistence order:

1. `NORMALIZED`;
2. `ORIGINAL`;
3. `OCR_SOURCE`;
4. `THUMBNAIL`.

Within the same role, the asset's declared order is used as a stable tie-breaker. This keeps the enhanced `NORMALIZED` rendition Reader-preferred after a database round trip without changing the Reader API.

At byte-delivery time, Reader tries the eligible renditions in that same order. If the preferred storage object is missing, Reader continues to the next eligible rendition, such as the retained `OCR_SOURCE`. A 409 is returned only when no eligible rendition object can be read. Provider-wide storage failures remain temporary 503 responses.

If the image-editing provider fails or returns invalid output, canonicalization records the failure and keeps the original crop as the available `NORMALIZED` rendition. A single failed image does not fail the entire book.

## Configuration

The feature is explicitly opt-in to prevent unexpected per-image cost:

```text
PDF_VISUAL_ASSET_ENHANCEMENT_ENABLED=true
PDF_VISUAL_ASSET_ENHANCEMENT_OPENAI_MODEL=gpt-image-1.5
```

API key lookup order:

1. `PDF_VISUAL_ASSET_ENHANCEMENT_OPENAI_API_KEY`;
2. existing `PDF_STRUCTURE_REFINEMENT_OPENAI_API_KEY`.

Optional settings:

```text
PDF_VISUAL_ASSET_ENHANCEMENT_OPENAI_BASE_URL=https://api.openai.com/v1
PDF_VISUAL_ASSET_ENHANCEMENT_OPENAI_QUALITY=high
PDF_VISUAL_ASSET_ENHANCEMENT_OPENAI_TIMEOUT_SECONDS=120
PDF_VISUAL_ASSET_ENHANCEMENT_OPENAI_MAX_ATTEMPTS=3
PDF_VISUAL_ASSET_ENHANCEMENT_OPENAI_RETRY_BASE_SECONDS=0.5
```

When `PDF_VISUAL_ASSET_ENHANCEMENT_ENABLED` is absent or false, PDF crops keep the existing unedited rendering behavior.

## Reprocessing

Existing Candidates are immutable. Reprocess the PDF after deployment to create a new Candidate whose eligible non-cover figures and tables contain enhanced renditions. System-owned Reader selections promote to the new successful Candidate under the existing selection policy; manually selected Candidates remain preserved.