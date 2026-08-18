from __future__ import annotations

import copy
import importlib
import json
import pkgutil
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import MappingProxyType

import pytest

from app.processing.structured_result import StructuredProcessingResult
from app.structured_content.transformation import (
    DEFAULT_TRANSFORMATION_POLICY,
    SUPPORTED_MAPPING_VERSION,
    SUPPORTED_SPR_SCHEMA_VERSION,
    SUPPORTED_TRANSFORMATION_POLICY_VERSION,
    CandidateIdentityInput,
    InvalidStructuredProcessingResult,
    InvalidTransformationContext,
    MissingTransformationContext,
    StructuredContentTransformationError,
    TextNormalizationPolicy,
    TransformationContext,
    TransformationPolicy,
    UnknownNodePolicy,
    UnsupportedMappingVersion,
    UnsupportedStructuredProcessingResultVersion,
    UnsupportedTransformationPolicyVersion,
    transform_spr_to_candidate,
)

FIXTURE_ROOT = Path("tests/fixtures/processing/structured_processing_result_v1/expected")


def load_spr(name: str = "no_geometry.spr.json") -> StructuredProcessingResult:
    return StructuredProcessingResult(json.loads((FIXTURE_ROOT / name).read_text()))


def context() -> TransformationContext:
    return TransformationContext(
        document_ref="doc_synthetic_no_geometry",
        identity=CandidateIdentityInput(
            candidate_id="candidate-slice-3a",
            candidate_lineage_seed="lineage-seed-slice-3a",
        ),
        processing_run_ref="run_no_geometry",
        source_file_ref="srcfile_synthetic_no_geometry",
    )


def test_transformation_context_is_immutable() -> None:
    c = context()
    with pytest.raises(FrozenInstanceError):
        c.document_ref = "other"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        c.identity.candidate_id = "other"  # type: ignore[misc]


def test_transformation_context_equality_is_deterministic() -> None:
    assert context() == context()


@pytest.mark.parametrize(
    ("field", "kwargs"),
    [
        ("document_ref", {"document_ref": " "}),
        ("candidate_id", {"identity_args": (" ", "lineage")}),
        ("candidate_lineage_seed", {"identity_args": ("candidate", " ")}),
    ],
)
def test_transformation_context_rejects_blank_required_identifiers(field: str, kwargs: dict[str, object]) -> None:
    base = {
        "document_ref": "doc-1",
        "identity": CandidateIdentityInput("candidate", "lineage"),
    }
    if "identity_args" in kwargs:
        with pytest.raises(ValueError, match=field):
            CandidateIdentityInput(*kwargs["identity_args"])  # type: ignore[arg-type]
        return
    base.update(kwargs)
    with pytest.raises(ValueError, match=field):
        TransformationContext(**base)  # type: ignore[arg-type]


def test_transformation_context_allows_optional_provenance_fields() -> None:
    c = TransformationContext("doc-1", CandidateIdentityInput("candidate", "lineage"))
    assert c.processing_run_ref is None
    assert c.source_file_ref is None


@pytest.mark.parametrize("field", ["processing_run_ref", "source_file_ref"])
def test_transformation_context_rejects_blank_optional_provenance_fields(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        TransformationContext("doc-1", CandidateIdentityInput("candidate", "lineage"), **{field: " "})


def test_candidate_identity_input_keeps_identity_and_lineage_distinct() -> None:
    identity = CandidateIdentityInput("candidate-a", "lineage-seed-a")
    assert identity.candidate_id == "candidate-a"
    assert identity.candidate_lineage_seed == "lineage-seed-a"


def test_default_transformation_policy_is_deterministic() -> None:
    assert DEFAULT_TRANSFORMATION_POLICY == TransformationPolicy()
    assert DEFAULT_TRANSFORMATION_POLICY.spr_schema_version == SUPPORTED_SPR_SCHEMA_VERSION
    assert DEFAULT_TRANSFORMATION_POLICY.transformation_policy_version == SUPPORTED_TRANSFORMATION_POLICY_VERSION
    assert DEFAULT_TRANSFORMATION_POLICY.mapping_version == SUPPORTED_MAPPING_VERSION
    assert DEFAULT_TRANSFORMATION_POLICY.extensions == MappingProxyType({})


def test_transformation_policy_is_immutable_and_has_no_extension_leakage() -> None:
    extensions = {"org.atlas.test": "value"}
    policy = TransformationPolicy(extensions=extensions)
    extensions["org.atlas.test"] = "changed"
    assert policy.extensions["org.atlas.test"] == "value"
    with pytest.raises(TypeError):
        policy.extensions["org.atlas.other"] = "blocked"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        policy.mapping_version = 2  # type: ignore[misc]


def test_transformation_policy_bounds_enum_values() -> None:
    assert TransformationPolicy(unknown_node_policy="preserve").unknown_node_policy is UnknownNodePolicy.PRESERVE
    assert TransformationPolicy(text_normalization_policy="preserve_spr_text").text_normalization_policy is TextNormalizationPolicy.PRESERVE_SPR_TEXT
    with pytest.raises(ValueError):
        TransformationPolicy(unknown_node_policy="drop")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        TransformationPolicy(text_normalization_policy="normalize")  # type: ignore[arg-type]


def test_error_hierarchy_and_safe_messages() -> None:
    errors = [
        InvalidStructuredProcessingResult(),
        MissingTransformationContext(),
        InvalidTransformationContext("document_ref is required"),
        UnsupportedStructuredProcessingResultVersion(schema_version=2, supported_schema_version=1),
        UnsupportedTransformationPolicyVersion(policy_version=2, supported_policy_version=1),
        UnsupportedMappingVersion(mapping_version=2, supported_mapping_version=1),
    ]
    assert all(isinstance(error, StructuredContentTransformationError) for error in errors)
    for error in errors:
        message = str(error)
        assert "secret" not in message
        assert "payload" not in message
        assert "{\"pages\"" not in message
        assert message == str(error)


def test_transform_rejects_non_spr_input() -> None:
    with pytest.raises(InvalidStructuredProcessingResult, match="expected StructuredProcessingResult"):
        transform_spr_to_candidate({"schema_version": 1}, context=context())  # type: ignore[arg-type]


def test_transform_wraps_invalid_spr_with_bounded_error() -> None:
    spr = object.__new__(StructuredProcessingResult)
    object.__setattr__(spr, "data", {"schema_id": "atlas.structured-processing-result", "schema_version": 1})
    with pytest.raises(InvalidStructuredProcessingResult, match="invalid structured processing result") as exc:
        transform_spr_to_candidate(spr, context=context())
    assert exc.value.__cause__ is not None
    assert "schema_id" not in str(exc.value)


def test_transform_rejects_unsupported_spr_version() -> None:
    spr = object.__new__(StructuredProcessingResult)
    data = copy.deepcopy(load_spr().to_dict())
    data["schema_version"] = 2
    object.__setattr__(spr, "data", data)
    with pytest.raises(UnsupportedStructuredProcessingResultVersion):
        transform_spr_to_candidate(spr, context=context())


def test_transform_rejects_missing_and_invalid_context() -> None:
    spr = load_spr()
    with pytest.raises(MissingTransformationContext):
        transform_spr_to_candidate(spr, context=None)  # type: ignore[arg-type]
    with pytest.raises(InvalidTransformationContext):
        transform_spr_to_candidate(spr, context="ctx")  # type: ignore[arg-type]


def test_transform_rejects_unsupported_policy_version() -> None:
    with pytest.raises(UnsupportedTransformationPolicyVersion):
        transform_spr_to_candidate(
            load_spr(),
            context=context(),
            policy=TransformationPolicy(transformation_policy_version=2),
        )


def test_transform_rejects_unsupported_mapping_version() -> None:
    with pytest.raises(UnsupportedMappingVersion):
        transform_spr_to_candidate(load_spr(), context=context(), policy=TransformationPolicy(mapping_version=2))


def test_transform_rejects_unsupported_policy_spr_version() -> None:
    with pytest.raises(UnsupportedStructuredProcessingResultVersion):
        transform_spr_to_candidate(load_spr(), context=context(), policy=TransformationPolicy(spr_schema_version=2))


def test_valid_core_spr_reaches_successful_slice_3b_boundary() -> None:
    candidate = transform_spr_to_candidate(load_spr(), context=context())
    assert candidate.candidate_id.value == "candidate-slice-3a"


def test_valid_degraded_spr_maps_to_partial_no_usable_candidate() -> None:
    degraded = load_spr("partial_failed_page.spr.json")
    candidate = transform_spr_to_candidate(degraded, context=context())
    assert candidate.recovery_summary.no_usable_semantic_content_pages == 1


def test_repeated_contract_calls_are_deterministic_and_inputs_unchanged() -> None:
    spr = load_spr()
    c = context()
    p = DEFAULT_TRANSFORMATION_POLICY
    before = (copy.deepcopy(spr.to_dict()), c, p)
    results = []
    for _ in range(2):
        candidate = transform_spr_to_candidate(spr, context=c, policy=p)
        results.append((candidate.candidate_id.value, tuple(n.node_id.value for n in candidate.nodes)))
    assert results[0] == results[1]
    assert spr.to_dict() == before[0]
    assert c == before[1]
    assert p == before[2]


def test_transformer_module_has_no_persistence_or_provider_imports() -> None:
    package = importlib.import_module("app.structured_content.transformation")
    modules = [package]
    for module_info in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
        modules.append(importlib.import_module(module_info.name))
    forbidden = (
        "sqlalchemy",
        "app.models",
        "app.structured_content.repository",
        "app.structured_content.selection_repository",
        "app.structured_content.selection_service",
        "app.processing.paddle_vl",
        "fastapi",
        "modal",
        "requests",
        "httpx",
        "boto3",
    )
    for module in modules:
        assert module.__name__.startswith("app.structured_content.transformation")
        assert not any(name in module.__dict__ for name in forbidden)
    source = "\n".join(Path(module.__file__).read_text() for module in modules if module.__file__)
    assert not any(term in source for term in forbidden)
