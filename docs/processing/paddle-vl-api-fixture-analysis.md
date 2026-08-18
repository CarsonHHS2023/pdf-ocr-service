# M2-003A paddle-vl-api Fixture Analysis

| Field | Value |
|---|---|
| Document Type | Fixture Analysis |
| Evidence Role | Offline provider-fixture analysis evidence |
| Reviewed Revisions | Provider reference `3a790e3e4c0ececef316bd2ca5aa03d84f6c6159`; provider implementation inventory revision `20b9ec9` |
| Authority Domain | Observed provider-fixture structure, provenance, and compatibility implications |
| Applies To | Static contract fixtures under `tests/fixtures/providers/paddle_vl_api/`; provider request, submission, status, result, artifact, error, page-remapping, and MinerU-Popo analysis fixture cases |

## Evidence boundary

This document analyzes static contract fixtures captured for Atlas planning. The fixture JSON represents provider protocol evidence only. It is not Atlas's future persistent Raw Processing Result schema. Atlas may later wrap an ingested provider result in an Atlas-owned provenance envelope, but this task does not define that envelope, storage keys, database tables, or retention periods.

No live provider call was made. Fixtures are reconstructed from the mounted provider inventory, response-building code, request models, and verified provider tests at provider reference commit `3a790e3e4c0ececef316bd2ca5aa03d84f6c6159`; the provider inventory records implementation revision `20b9ec9`.

## Fixture manifest structure

`tests/fixtures/providers/paddle_vl_api/manifest.json` is a simple manifest, not a public schema. It contains a manifest version, a short description, a structure note, and one entry per fixture with filename, category, provenance type, provider reference commit, provider implementation revision, source evidence, endpoint, result profile, implemented/synthetic classification, notes, and limitations.

Committed fixtures are implementation-grounded. Request, submission, and stable error fixtures are source-derived from provider models/routes; status/result fixtures are partially source-derived representative snapshots because their placeholder page text and deterministic timestamps are selected for Atlas testing while preserving provider field names and profile-specific nesting. No live-captured fixtures and no synthetic fixtures are included.

## Fixture inventory

The fixture set covers async request serialization, acceptance, status polling, terminal/error states, result profile retrieval, artifact metadata, page remapping, and a rich MinerU-Popo analysis sample:

- `job_submit_request.json` and `job_submit_response_accepted.json` cover `POST /ocr/jobs`.
- `job_status_queued.json`, `job_status_running.json`, `job_status_completed.json`, `job_status_partial_failed.json`, `job_status_failed.json`, and `job_status_expired.json` cover provider top-level statuses.
- `result_summary_completed.json`, `result_standard_completed.json`, `result_full_inline_completed.json`, `result_full_artifact_metadata.json`, and `result_partial_failed.json` cover result profiles.
- `error_validation.json`, `error_authentication.json`, `error_result_not_ready.json`, `error_job_missing.json`, `error_result_expired.json`, `error_artifact_missing_or_expired.json`, and `error_provider_failure.json` cover stable async error families.
- `result_page_mapping_multi_range.json` demonstrates one-based `page_number`, zero-based original `page_index`, zero-based range-local `local_page_index`, `source_page_range`, and merged ordering.
- `result_for_mineru_popo_analysis.json` is the richest available verified provider shape for adapter analysis.

## MinerU-Popo compatibility analysis

Current Atlas persistence stores `PdfPage.page_num` as one-based page number, optional `page_width` and `page_height`, and `ocr_raw_json` as a JSON string shaped like `{"page_num": N, "page_width": W, "page_height": H, "parsing_res_list": [...]}`. `PageOCRService` writes that shape after per-page OCR. `MineruPopoService` reads each page's `ocr_raw_json`, falls back to the ORM `page_num`, and iterates `parsing_res_list` entries as a list of dictionaries.

| Provider field/shape | Current MinerU-Popo assumption | Classification | Notes |
| --- | --- | --- | --- |
| `documents[].pages[].page_number` | `PdfPage.page_num` / payload `page_num` | Compatible after Atlas transformation | Provider uses `page_number`; MinerU-Popo reads `page_num`. |
| `documents[].pages[].page_index` | No direct field in `ocr_raw_json` | Not required | Useful for validation/remapping but not required by current MinerU-Popo. |
| `documents[].pages[].markdown` | No Markdown input path | Requires MinerU-Popo change | Current service reconstructs content from parsed blocks, not Markdown. |
| `documents[].pages[].blocks` | No direct normalized block input | Compatible after Atlas transformation | Provider normalized blocks must be converted to `parsing_res_list`-like entries or MinerU-Popo must change. |
| `documents[].raw_result[].parsing_res_list` | Required list of raw entries | Directly compatible when wrapped per page | Rich full-profile raw results include the closest shape. |
| `documents[].raw_result[].width` / `height` | `page_width` / `page_height` | Compatible after Atlas transformation | Names differ and Atlas must set/fallback page dimensions. |
| `layout_det_res.boxes` | Not read directly by MinerU-Popo | Not required | Provider uses it for normalization; current MinerU-Popo ignores it. |
| `table_res_list`, `image_res_list`, `formula_res_list` | No direct list readers | Unclear | Current service classifies visual/formula content through block labels/categories. |
| Block `type`, `text`, `bbox`, `confidence`, `order` | Raw entry `label/type`, `content/text`, `bbox` | Compatible after Atlas transformation | Label/content naming must be normalized carefully. |
| `source_page_range` and `local_page_index` | No direct fields | Not required | Important for Atlas remapping/provenance, not MinerU-Popo processing. |

Conclusion: the fixtures are sufficient to design an Atlas-side transformation from provider full/standard results into current `PdfPage.ocr_raw_json`-like payloads, but they are not sufficient to claim direct MinerU-Popo compatibility. A future adapter must explicitly map page fields, page dimensions, and block entry names.

## Result-profile comparison

| Profile | Raw preservation | Atlas adapter fields | MinerU-Popo fields | Page mapping | Payload / TTL risk | Complexity | Test suitability | Production ingestion suitability |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `summary` | No page/block raw result | Insufficient | Insufficient | Document only | Smallest; no artifact risk | Low | Good for polling smoke tests only | Not sufficient |
| `standard` | No raw result | Good normalized pages/blocks/markdown | Requires transformation; lacks raw `parsing_res_list` | Public pages have `page_number`/`page_index` only | Moderate; no artifact risk | Low-medium | Good for client and normalization tests | Good for normalized ingestion only |
| `full` inline | Preserves slimmed raw result inline | Best evidence for adapter and raw retention | Best available source for `parsing_res_list`-style transformation | Raw result includes range-local mapping in fixtures | Larger payload; inline limit can force artifact | Medium | Good with small fixtures | Strong candidate when payload fits |
| `full` artifact | Preserves raw result via temporary artifact | Same as full once downloaded | Same as full once downloaded | Artifact metadata does not contain pages itself | TTL and missing artifact risk | Highest | Good for artifact client tests | Useful for large results but requires prompt retrieval |

## Codex Recommendation — Human Confirmation Required

Initial Atlas implementations should preserve the richest provider evidence made available by the configured provider for each successful processing attempt. This is an Atlas architectural principle, not a provider requirement, and it is independent of provider profile names. For the currently verified `paddle-vl-api` fixtures, the provider `full` profile is the most appropriate initial candidate because `standard` is useful for normalized pages and blocks but does not preserve the richest raw `parsing_res_list` evidence needed to decide and implement the MinerU-Popo adapter. If a future provider names its richest representation `extended`, `complete`, or something else, Atlas should preserve that richest available evidence instead of requiring the name `full`.

Raw Processing Result retention and MinerU-Popo normalization input are related but not permanently coupled. The initial implementation may use the richest available provider result for both purposes; future implementations may retain one provider representation and normalize from another equivalent representation, provided no required processing evidence is lost. That remains an implementation optimization, not an architectural contract, and does not weaken Raw Processing Result ownership: Atlas owns any provider result it intentionally retains after ingestion.

Provider output never becomes Structured Processing Output directly. The transformation boundary remains: Provider Result → Atlas Transformation → MinerU-Popo, or equivalent normalization → Structured Processing Output. This recommendation is based on currently verified fixtures and may be revisited if future provider capabilities or verified fixtures change. Human confirmation and expanded fixture/live evidence are required before treating this as a production ingestion decision because artifact retrieval can introduce TTL and payload-size risks.

## Missing evidence and live-capture guidance

Missing or limited evidence:

- No live OCR payload was captured from an actual deployed provider.
- No committed fixture proves a large real document crossing the artifact threshold.
- No fixture proves every PaddleOCR-VL field variant that may appear in `table_res_list`, `image_res_list`, or `formula_res_list`.
- Status and result fixtures use deterministic representative timestamps/counters and manually selected safe page content rather than a captured provider state object.
- Provider results expose `build_tag` but not a stable top-level Git commit or model version.

If future live capture is approved, use a non-sensitive test PDF, test credentials, redacted auth, provider revision/build tag, request options, capture date, payload-size review, and checks confirming that no signed/private URLs are committed. Required Backend CI must never call the live provider.

## Implementation readiness decision

1. Provider-specific Atlas client: sufficient to begin mocked async client work.
2. Request serialization: sufficient; request fields and HTTPS/SHA-256 options are covered.
3. Status/error mapping: sufficient for stable async statuses and main error families, with adapter tests treating representative counters/timestamps as examples rather than exhaustive lifecycle captures.
4. Result retrieval: sufficient for summary, standard, full inline, full artifact metadata, and not-ready/expired cases.
5. Page remapping: sufficient for the initial one-document, multi-range mapping rules.
6. MinerU-Popo adapter: not sufficient to implement direct compatibility claims; sufficient to begin an Atlas transformation design with mocked fixtures.
7. Blocked areas: live OCR variety, full artifact download body shape at scale, comprehensive image/table/formula variants, exact captured lifecycle state objects, and final Atlas Raw Processing Result persistence envelope.

Recommended smallest next task: **M2-003B — Implement paddle-vl-api Async Client with Mocked Contract Tests**. The request/response/status/error fixtures are sufficient to authorize the client portion of that task; the MinerU-Popo adapter should remain a separate follow-on or explicitly limited transformation spike.
