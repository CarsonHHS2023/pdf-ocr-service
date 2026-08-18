import json
import re
from pathlib import Path

BASE = Path(__file__).parent / "fixtures" / "providers" / "paddle_vl_api"
MANIFEST = BASE / "manifest.json"
STATUSES = {"queued", "running", "completed", "partial_failed", "failed", "expired"}
SECRET_PATTERNS = [re.compile(p, re.I) for p in [r"authorization", r"x-amz-", r"signature=", r"secret", r"password"]]


def load(path):
    return json.loads(path.read_text())


def walk_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk_strings(item)


def manifest():
    return load(MANIFEST)


def test_manifest_entries_point_to_existing_json_fixtures():
    names = {entry["filename"] for entry in manifest()["fixtures"]}
    assert names
    for name in names:
        assert (BASE / name).is_file()
    assert names == {p.name for p in BASE.glob("*.json") if p.name != "manifest.json"}


def test_every_json_fixture_parses_and_has_no_obvious_secrets_or_credential_urls():
    for path in BASE.rglob("*.json"):
        data = load(path)
        text_values = list(walk_strings(data))
        assert not any(pattern.search(value) for pattern in SECRET_PATTERNS for value in text_values), path


def test_required_async_fixture_categories_are_present():
    names = {entry["filename"] for entry in manifest()["fixtures"]}
    required = {"job_submit_request.json", "job_submit_response_accepted.json", "job_status_queued.json", "job_status_running.json", "job_status_completed.json", "job_status_partial_failed.json", "job_status_failed.json", "job_status_expired.json", "result_standard_completed.json", "result_full_inline_completed.json", "result_full_artifact_metadata.json"}
    assert required <= names


def test_status_fixtures_use_only_verified_provider_status_names():
    for path in BASE.glob("job_status_*.json"):
        assert load(path)["status"] in STATUSES


def test_request_fixture_preserves_provider_request_field_names():
    body = load(BASE / "job_submit_request.json")
    assert set(body) == {"schema_version", "job_id", "request_id", "documents", "options"}
    assert set(body["documents"][0]) == {"document_id", "pdf_source_url", "pdf_source_etag", "pdf_source_sha256"}
    assert re.fullmatch(r"[a-f0-9]{64}", body["documents"][0]["pdf_source_sha256"])


def test_page_mapping_fixture_has_internally_consistent_numbering():
    body = load(BASE / "result_page_mapping_multi_range.json")
    pages = body["documents"][0]["raw_result"]
    assert [page["page_number"] for page in pages] == [1, 2, 3]
    for page in pages:
        source_range = page["source_page_range"]
        assert page["page_index"] == page["page_number"] - 1
        assert page["page_number"] == source_range["page_start"] + page["local_page_index"]
        assert source_range["page_start"] <= page["page_number"] <= source_range["page_end"]


def test_artifact_metadata_fixture_contains_verified_public_fields():
    artifact = load(BASE / "result_full_artifact_metadata.json")["result_artifact"]
    assert {"format", "compression", "size_bytes", "sha256", "created_at", "expires_at", "artifact_id", "download_endpoint"} <= set(artifact)
    assert "cache_key" not in artifact


def test_synthetic_fixtures_are_clearly_labeled_if_present():
    synthetic = BASE / "synthetic"
    if synthetic.exists():
        manifest_entries = {entry["filename"]: entry for entry in manifest()["fixtures"]}
        for path in synthetic.glob("*.json"):
            entry = manifest_entries[path.relative_to(BASE).as_posix()]
            assert entry["implemented_vs_synthetic"] == "synthetic"
            assert "Synthetic" in entry["provenance_type"]


def test_implementation_grounded_fixtures_record_source_provenance():
    for entry in manifest()["fixtures"]:
        if entry["implemented_vs_synthetic"] == "implemented":
            assert entry["source_evidence"]
            assert entry["provider_reference_commit"]
            assert entry["provider_implementation_revision"]


def test_result_profile_field_exclusions_match_provider_projection():
    summary = load(BASE / "result_summary_completed.json")
    summary_doc = summary["documents"][0]
    assert "pages" not in summary_doc
    assert "markdown" not in summary_doc
    assert "blocks" not in summary_doc
    assert "raw_result" not in json.dumps(summary)

    standard = load(BASE / "result_standard_completed.json")
    standard_doc = standard["documents"][0]
    assert standard["status"] == "completed"
    assert standard_doc["status"] == "completed"
    assert standard_doc["pages_completed"] == standard_doc["pages_total"]
    assert "markdown" in standard_doc
    assert "blocks" in standard_doc
    assert "pages" in standard_doc
    assert "raw_result" not in json.dumps(standard)
    assert set(standard_doc["pages"][0]) == {"page_number", "page_index", "markdown", "blocks"}

    full_inline = load(BASE / "result_full_inline_completed.json")
    assert "raw_result" in full_inline["documents"][0]
    assert full_inline["result_artifact"] is None

    full_artifact = load(BASE / "result_full_artifact_metadata.json")
    assert full_artifact["documents"][0]["status"] == "completed"
    assert full_artifact["documents"][0]["pages_completed"] == full_artifact["documents"][0]["pages_total"]
    assert "raw_result" not in json.dumps(full_artifact["documents"])
    assert full_artifact["result_artifact"] is not None


def test_public_status_and_artifact_fixtures_exclude_internal_fields():
    forbidden = {"expires_at_epoch", "mock_step_delay_seconds", "source_documents", "options", "cache_key"}
    for path in BASE.glob("job_status_*.json"):
        text = json.dumps(load(path))
        assert not any(field in text for field in forbidden), path
    artifact_text = json.dumps(load(BASE / "result_full_artifact_metadata.json")["result_artifact"])
    assert "cache_key" not in artifact_text
    assert "expires_at_epoch" not in artifact_text
