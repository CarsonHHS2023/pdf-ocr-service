# PDF visual asset enhancement rollout

1. Merge and deploy the backend PR.
2. Configure `PDF_VISUAL_ASSET_ENHANCEMENT_ENABLED=true`.
3. Configure the OpenAI image-edit model and API key.
4. Reprocess a small representative PDF containing diagrams, tables, and charts.
5. Verify Candidate asset metadata contains `visual_enhancement.status=applied`.
6. Verify each enhanced asset has `NORMALIZED` followed by `OCR_SOURCE` renditions.
7. Open Reader and compare the enhanced rendition against the retained original crop.
8. Reprocess larger books only after output fidelity and provider cost are accepted.

Do not delete the retained original crop. It is the evidence and fallback when enhancement fails or must be audited.
