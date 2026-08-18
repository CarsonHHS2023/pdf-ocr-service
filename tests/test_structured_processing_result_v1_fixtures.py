"""Offline safety and internal-consistency checks for the M3-001C fixture corpus."""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

BASE = Path(__file__).parent / "fixtures" / "processing" / "structured_processing_result_v1"
FORBIDDEN = re.compile(r"(?:https?://|bearer\s+|authorization|/home/|/tmp/|[a-z]:\\\\)", re.I)
REQUIRED_MANIFEST_KEYS = {
    "fixture_id", "file_path", "fixture_category", "source_type", "provider_name",
    "provider_contract_revision", "provider_profile", "content_is_synthetic", "safe_to_commit",
    "origin_document_type", "pages_represented", "expected_result_state",
    "contract_behaviors_exercised", "known_limitations", "paired_expected_spr_fixture",
    "m3_001d_must_support", "rejection_only",
}

def load(path: Path): return json.loads(path.read_text(encoding="utf-8"))
def canonical(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
def strings(value):
    if isinstance(value, str): yield value
    elif isinstance(value, dict):
        for key, child in value.items(): yield key; yield from strings(child)
    elif isinstance(value, list):
        for child in value: yield from strings(child)

def test_manifest_is_complete_safe_and_references_each_fixture_once():
    manifest = load(BASE / "manifest.json"); entries = manifest["fixtures"]
    assert manifest["manifest_version"] == "1"
    assert len({entry["fixture_id"] for entry in entries}) == len(entries)
    paths = {entry["file_path"] for entry in entries}
    actual = {path.relative_to(BASE).as_posix() for path in BASE.rglob("*.json") if path.name != "manifest.json"}
    assert paths == actual
    for entry in entries:
        assert REQUIRED_MANIFEST_KEYS <= set(entry)
        assert entry["content_is_synthetic"] is True and entry["safe_to_commit"] is True
        assert entry["source_type"] in {"synthetic_provider_shape", "synthetic_raw_result_envelope", "synthetic_expected_spr"}
        assert (BASE / entry["file_path"]).is_file()

def test_all_fixtures_parse_and_exclude_transport_secrets_urls_and_local_paths():
    for path in BASE.rglob("*.json"):
        value = load(path)
        found = [text for text in strings(value) if FORBIDDEN.search(text)]
        # The unsafe case uses an inert non-URL marker; its unsafe key must not weaken scans elsewhere.
        assert not found, (path, found)
    unsafe = load(BASE / "raw_results" / "unsafe_metadata.json")["retained_payload"]
    assert unsafe["artifact_url"] == "REJECTED_TRANSPORT_URL_PLACEHOLDER"

def test_raw_envelopes_have_exact_retained_payload_checksums_and_sizes():
    for path in (BASE / "raw_results").glob("*.json"):
        fixture = load(path)
        if path.name == "malformed_raw_result.json":
            raw = fixture["raw_result"]["ingestion"]; payload = fixture["retained_payload_text"].encode()
        else:
            raw = fixture["raw_result"]["ingestion"]; payload = canonical(fixture["retained_payload"])
        assert raw["payload_size_bytes"] == len(payload)
        assert raw["payload_sha256"] == hashlib.sha256(payload).hexdigest()
        assert re.fullmatch(r"src_[0-9a-f]{32}", raw["storage_reference"])

def test_expected_spr_oracles_are_deterministic_and_linked_to_positive_raw_fixtures():
    for path in (BASE / "expected").glob("*.spr.json"):
        spr = load(path); expected_bytes = canonical(spr)
        assert path.read_bytes() == expected_bytes + b"\n"
        assert spr["schema_id"] == "atlas.structured-processing-result" and spr["schema_version"] == 1
        assert spr["state"] in {"complete", "partial", "invalid"}
        assert spr["state"] != "invalid" or spr["quality_summary"]["schema_validation_state"] == "invalid"
        _validate_spr_references(spr)
        _validate_oracle_correspondence(spr, path)
        raw_name = path.name.removesuffix(".spr.json") + ".json"
        raw = load(BASE / "raw_results" / raw_name)
        assert spr["raw_result"]["payload_checksum_sha256"] == raw["raw_result"]["ingestion"]["payload_sha256"]

def _validate_oracle_correspondence(spr, path):
    raw = load(BASE / "raw_results" / (path.name.removesuffix(".spr.json") + ".json"))["retained_payload"]
    input_pages = raw["documents"][0]["pages"]
    assert [p["page_index"] for p in spr["pages"]] == [p["page_index"] for p in input_pages]
    input_text = {b["text"] for page in input_pages for b in page.get("blocks", []) if "text" in b}
    output_text = {node["text"] for node in spr["nodes"] if "text" in node}
    assert input_text <= output_text
    for page in input_pages:
        for block in page.get("blocks", []):
            if "bbox" in block:
                assert any(link.get("provider_block_id") == block["id"] and "geometry" in link for link in spr["evidence_links"])

def _validate_spr_references(spr):
    pages, nodes, observations = spr["pages"], spr["nodes"], spr["normalized_observations"]
    page_ids, node_ids, observation_ids = ({x[k] for x in xs} for xs, k in ((pages,"page_id"),(nodes,"node_id"),(observations,"observation_id")))
    assert len(page_ids) == len(pages) and len(node_ids) == len(nodes) and len(observation_ids) == len(observations)
    assert [p["page_index"] for p in pages] == sorted(p["page_index"] for p in pages)
    for page in pages:
        assert page["width"] > 0 and page["height"] > 0
        assert page["rotation_degrees"] in {0, 90, 180, 270}
        assert set(page["root_node_ids"]) <= node_ids
    evidence = {x["evidence_link_id"]: x for x in spr["evidence_links"]}
    for observation in observations:
        assert observation["page_id"] in page_ids
        assert set(observation["evidence_link_ids"]) <= set(evidence)
    for node in nodes:
        assert set(node["observation_ids"]) <= observation_ids and set(node["page_ids"]) <= page_ids
        assert set(node["evidence_link_ids"]) <= set(evidence)
        for bbox in [node.get("geometry", {}).get("normalized_bbox")]:
            if bbox is not None:
                assert all(math.isfinite(float(x)) and 0 <= float(x) <= 1 for x in bbox)
                assert float(bbox[0]) < float(bbox[2]) and float(bbox[1]) < float(bbox[3])
    for link in evidence.values():
        assert link["target_kind"] == "observation" and link["target_id"] in observation_ids

def test_rejection_cases_are_explicit_and_never_paired_with_an_expected_spr():
    entries = load(BASE / "manifest.json")["fixtures"]
    rejected = {e["fixture_id"] for e in entries if e["rejection_only"]}
    assert {"malformed_raw_result", "unsafe_metadata", "duplicate_page_mapping", "missing_page", "rejection_cases"} <= rejected
    assert all(e["paired_expected_spr_fixture"] is None for e in entries if e["rejection_only"])
    cases = load(BASE / "fragments" / "rejection_cases.json")["rejection_cases"]
    assert len(cases) == 14 and all(case["rejection_layer"] for case in cases)
