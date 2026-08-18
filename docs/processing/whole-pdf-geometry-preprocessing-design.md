# Whole-PDF Geometry Preprocessing Design

This design defines the geometry-preprocessed PDF path used before Modal OCR.

- The retained `SourceFile` remains the original user-uploaded PDF.
- A derived, temporary PDF is generated before provider submission.
- Only conservative planar perspective correction and small-angle deskew are permitted.
- Tonal enhancement, denoise, CLAHE, sharpening, binarization, and generative cleanup are excluded.
- Modal remains unchanged and receives the derived PDF through the existing HTTPS transport grant.
- Original Source provenance and provider-input provenance remain distinct.
- Structured Content visual crops must be rendered from the same derived PDF used by Modal so normalized OCR coordinates remain aligned.
- The derived PDF is deleted after a terminal provider result and canonicalization. It is retained when submission outcome is uncertain or orchestration times out.
- LLM background cleanup of individual visual crops is deferred to a separate, auditable rendition step.
