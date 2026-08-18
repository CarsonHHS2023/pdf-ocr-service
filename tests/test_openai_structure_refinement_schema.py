from __future__ import annotations

from collections.abc import Mapping

from app.processing.openai_structure_refinement_provider import _PATCH_SCHEMA


def _assert_strict_object_contract(schema: object) -> None:
    if isinstance(schema, Mapping):
        if schema.get("type") == "object":
            properties = schema.get("properties")
            assert isinstance(properties, Mapping)
            required = schema.get("required")
            assert isinstance(required, list)
            assert set(required) == set(properties)
            assert schema.get("additionalProperties") is False
        for value in schema.values():
            _assert_strict_object_contract(value)
    elif isinstance(schema, list):
        for value in schema:
            _assert_strict_object_contract(value)


def test_patch_schema_satisfies_openai_strict_object_contract() -> None:
    _assert_strict_object_contract(_PATCH_SCHEMA)


def test_nullable_operation_fields_are_required() -> None:
    operation_schema = _PATCH_SCHEMA["properties"]["operations"]["items"]
    required = set(operation_schema["required"])

    assert {
        "target_kind",
        "heading_level",
        "toc_level",
        "parent_id",
        "original_text",
        "corrected_text",
        "warning",
    } <= required
