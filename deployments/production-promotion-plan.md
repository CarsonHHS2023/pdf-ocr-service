# Production promotion acceptance plan

## Source and target

- Promoted source branch: `deploy/ocrmypdf-test`
- Promotion branch: `release/promote-ocrmypdf-test-to-production`
- Production branch: `main`
- Production Space: `carsonhhs/pdf-ocr-service`

## Deployment contract

The production GitHub Actions workflow must apply the same validated overlays, in the same order, as the test-Space workflow before uploading the integrated workspace:

1. `apply_opencv_v4_modal_bridge.py`
2. `apply_provider_result_diagnostics.py`
3. `apply_presentation_provenance_fix.py`
4. `apply_heading_review_semantic_retry.py`
5. `apply_page_role_scope_alignment.py`
6. `apply_high_resolution_page_confirmation.py`
7. `apply_native_pdf_text_recovery.py`

The final native-text overlay installs the native/orientation/page-dimension preservation compatibility layer validated by PR #267.

## Required pre-merge gates

- Required Backend CI passes.
- Production workflow overlay application, compilation, focused pytest, validators, and scope-boundary checks pass.
- Codex reviews the exact latest promotion head and reports no unresolved actionable findings.
- All inline review threads are resolved.
- The PR remains a pure promotion; no new feature work is added.

## Required production acceptance

After merge and production Space rebuild:

1. Confirm a new production `Application Startup` after the merge.
2. Reprocess the same `OpenCV-Test.pdf` used in the test Space.
3. Confirm final document status is completed and canonicalization is ready.
4. Verify page 3 reading order and embedded figure orientation.
5. Verify page 8 chart direction, aspect ratio, page dimensions, width usage, and caption proximity.
6. Verify page 10 native text, embedded figure placement, text copyability, and no duplicated chart-internal text.
7. Verify page 12 is not incorrectly retained as an upside-down `full_page_chart` when substantial prose is present.
8. Confirm provider grants are revoked and temporary provider inputs are deleted.

Only after production acceptance should a new issue branch be created from the current test deployment baseline.
