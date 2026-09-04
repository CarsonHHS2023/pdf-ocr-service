# S0 visual-asset generation timing — implementation review, 2026-09-04

## Outcome

The implementation candidate measures the exact final PDF visual-enrichment
call and adds strict durable collector mapping for
`visual_asset_generation_seconds`. It does not broaden the value to full
canonicalization or infer it from existing timestamps.

The candidate is based on `staging@e06af64cb05cdf3b7ee7a0314528d9377953d729`,
the exact PR #42 merge/deployment revision. PR #42's upload-memory NO-GO remains
unchanged: `backend_upload_peak_memory_mb` is not filled by this work.

This record is implementation/CI evidence only. Staging runtime acceptance and a
numeric observed value require a later, explicitly authorized deployment and a
fresh eligible fixture run.

## Reviewed boundary

Source tracing found one authoritative operation inside
`PdfCanonicalizationService.canonicalize`: the call to the final composed
`enrich_candidate_with_pdf_visual_assets`. Existing compatibility modules wrap
that callable to perform visual crop rendering, OpenCV processing, rendition
persistence and lifecycle metadata attachment. Installing the S0 observer last
measures the complete active wrapper chain without changing its bytes, policy or
failure behavior.

The observer intentionally does not include the coordinate-aligned PDF storage
read, structure refinement, SPR write, candidate database transaction or Reader
open. `canonicalization_duration_seconds` remains a broader containing interval.

## Implementation shape

- `app/s0_visual_asset_generation_metrics.py` owns the exact two-event schema,
  duplicate-key JSON decoder and fail-closed collector.
- `app/s0_visual_asset_generation_observability.py` owns the Staging revision
  gate, worker-owned wall clock, generated identity counts and atomic event batch.
- `scripts/apply_s0_visual_asset_generation_observability.py` installs the
  observer after all existing PDF visual wrappers and composes the collector.
- focused unit/composed tests cover behavior preservation, identity, ordinals,
  persistence, privacy, malformed/oversized evidence and required-metric mapping.

No database migration is required; the existing bounded ProcessingEvent schema
is reused. No source contents or private fixture identifiers are committed.

## Open S0 status

Until Staging acceptance, all four previously recorded required gaps remain:

- `backend_upload_peak_memory_mb`;
- `preprocessing_cpu_seconds`;
- `visual_asset_generation_seconds`;
- `upload_to_reader_ready_seconds`.

If later acceptance passes, only the visual-asset row may move to `observed`.
The other three remain open, and neither S0 nor M5 may be marked complete.
