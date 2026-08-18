# Production promotion summary

This promotion lifts the fully tested `deploy/ocrmypdf-test` baseline into the production release path.

The promoted flow includes:

- stable OpenCV v4 page preprocessing;
- Modal/Paddle provider integration;
- presentation-page routing and original-page remapping;
- high-resolution confirmation before non-zero rotation or OCR skipping;
- provider-result diagnostics and safe provenance rebuilding;
- bounded semantic retry for incomplete mandatory heading review;
- aligned page-role review scope;
- native PDF text and embedded-figure recovery;
- raster fallback for rejected native text layers;
- orientation-safe provider page dimensions and composed geometry/analysis fail-open state.

The production deployment workflow applies the same seven overlays and focused validation used by the test-Space deployment before uploading to `carsonhhs/pdf-ocr-service`.

No new feature development is allowed in this promotion PR. Production acceptance with the existing `OpenCV-Test.pdf` is required after deployment before the next test-environment issue branch is created.
