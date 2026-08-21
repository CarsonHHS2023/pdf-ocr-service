"""Composition-aware final wrapper for the 20 MiB Staging Provider overlay.

The native-text and provider-input-access overlays run before this wrapper in
Staging CI. This wrapper preserves their composed contracts while applying the
20 MiB concurrent Provider runner.
"""
from __future__ import annotations

from pathlib import Path

try:
    from scripts import apply_provider_20mib_observability_v2 as v2
    from scripts import apply_provider_20mib_observability_v3 as v3
except ImportError:
    import apply_provider_20mib_observability_v2 as v2  # type: ignore[no-redef]
    import apply_provider_20mib_observability_v3 as v3  # type: ignore[no-redef]


PREPROCESS_PATH = Path("app/processing/pdf_page_presentation_preprocess_compat.py")
SHARDING_PATH = Path("app/processing/pdf_provider_sharding.py")
TEST_COMPAT_PATH = Path("tests/test_pdf_provider_sharding_compat.py")


def _replace_once(source: str, old: str, new: str, *, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one source match, found {count}")
    return source.replace(old, new, 1)


def _patch_presentation_native_counts_composed() -> None:
    source = PREPROCESS_PATH.read_text(encoding="utf-8")

    native_accounting = (
        "        local_result_count = page_count - provider_page_count\n"
        "        native_text_count = sum(\n"
        "            1 for item in decisions if item.get(\"native_text_accepted\")\n"
        "        )\n"
        "        presentation_count = local_result_count - native_text_count\n"
    )
    original_accounting = (
        "        provider_page_count = len(provider_map)\n"
        "        presentation_count = page_count - provider_page_count"
    )

    if native_accounting in source:
        source = _replace_once(
            source,
            native_accounting,
            native_accounting
            + "        excluded_from_provider_count = local_result_count\n"
            + "        if provider_page_count + excluded_from_provider_count != page_count:\n"
            + "            raise RuntimeError(\"page route counts do not cover the document\")\n",
            label="composed native/provider route accounting",
        )
    elif original_accounting in source:
        source = _replace_once(
            source,
            original_accounting,
            "        provider_page_count = len(provider_map)\n"
            "        native_text_count = sum(\n"
            "            1 for decision in decisions\n"
            "            if bool(decision.get(\"native_text_accepted\"))\n"
            "        )\n"
            "        presentation_count = sum(\n"
            "            1 for decision in decisions\n"
            "            if bool(decision.get(\"skip_ocr\"))\n"
            "            and not bool(decision.get(\"native_text_accepted\"))\n"
            "        )\n"
            "        excluded_from_provider_count = presentation_count + native_text_count\n"
            "        if provider_page_count + excluded_from_provider_count != page_count:\n"
            "            raise RuntimeError(\"page route counts do not cover the document\")",
            label="legacy presentation/native route accounting",
        )
    elif "excluded_from_provider_count =" not in source:
        raise RuntimeError("presentation/native route accounting shape is unsupported")

    if "        elif local_result_count == 0:\n            provider_put = render_put" in source:
        source = source.replace(
            "        elif local_result_count == 0:\n            provider_put = render_put",
            "        elif excluded_from_provider_count == 0:\n            provider_put = render_put",
            1,
        )
    elif "        elif presentation_count == 0:\n            provider_put = render_put" in source:
        source = source.replace(
            "        elif presentation_count == 0:\n            provider_put = render_put",
            "        elif excluded_from_provider_count == 0:\n            provider_put = render_put",
            1,
        )
    elif "        elif excluded_from_provider_count == 0:\n            provider_put = render_put" not in source:
        raise RuntimeError("provider subset reuse accounting shape is unsupported")

    if '            "provider_excluded_page_count": excluded_from_provider_count,\n' not in source:
        if '            "local_result_page_count": local_result_count,\n' in source:
            source = source.replace(
                '            "local_result_page_count": local_result_count,\n',
                '            "local_result_page_count": local_result_count,\n'
                '            "provider_excluded_page_count": excluded_from_provider_count,\n',
                1,
            )
        else:
            source = _replace_once(
                source,
                '            "native_text_page_count": native_text_count,\n',
                '            "native_text_page_count": native_text_count,\n'
                '            "provider_excluded_page_count": excluded_from_provider_count,\n',
                label="provider exclusion manifest counter",
            )

    diagnostic_marker = "            provider_excluded_page_count=excluded_from_provider_count,\n"
    if diagnostic_marker not in source:
        if "            local_result_page_count=local_result_count,\n" in source:
            source = source.replace(
                "            local_result_page_count=local_result_count,\n",
                "            local_result_page_count=local_result_count,\n"
                + diagnostic_marker,
                1,
            )
        else:
            source = _replace_once(
                source,
                "            native_text_page_count=native_text_count,\n",
                "            native_text_page_count=native_text_count,\n"
                + diagnostic_marker,
                label="provider exclusion diagnostic counter",
            )

    PREPROCESS_PATH.write_text(source, encoding="utf-8")


def _restore_concurrent_shard_source_access() -> None:
    """Restore remote-first source access erased by replacing the shard runner."""
    source = SHARDING_PATH.read_text(encoding="utf-8")
    required_imports = (
        "build_provider_input_source_url_factory",
        "PROVIDER_SOURCE_ACCESS_TTL_SECONDS",
        "from datetime import timedelta",
    )
    missing = [marker for marker in required_imports if marker not in source]
    if missing:
        raise RuntimeError(f"concurrent shard source-access imports are missing: {missing}")

    old = '''                grant_service = integration.ProviderInputGrantService(
                    get_transport_grant_service(),
                    shard_input,
                )
                service = EndToEndProcessingIntegrationService(
                    grant_service=grant_service,
                    orchestrator=orchestrator,
                    canonicalizer=None,
                    public_origin=public_origin,
                    polling_policy=polling_policy,
                )
'''
    new = '''                grant_service = integration.ProviderInputGrantService(
                    get_transport_grant_service(),
                    shard_input,
                )
                shard_delivery = integration.provider_delivery_descriptor(shard_input)
                shard_source_url_factory = build_provider_input_source_url_factory(
                    storage=storage,
                    reference=shard_delivery.storage_reference,
                    byte_size=shard_delivery.byte_size,
                )
                service = EndToEndProcessingIntegrationService(
                    grant_service=grant_service,
                    orchestrator=orchestrator,
                    canonicalizer=None,
                    public_origin=public_origin,
                    source_transport_url_factory=shard_source_url_factory,
                    source_access_ttl=timedelta(
                        seconds=PROVIDER_SOURCE_ACCESS_TTL_SECONDS,
                    ),
                    polling_policy=polling_policy,
                )
'''
    source = _replace_once(
        source,
        old,
        new,
        label="concurrent per-shard provider source URL factory",
    )
    SHARDING_PATH.write_text(source, encoding="utf-8")


def _patch_composed_test_thresholds() -> None:
    source = TEST_COMPAT_PATH.read_text(encoding="utf-8")
    start_marker = "def test_real_geometry_provider_input_above_target_enters_sharding(monkeypatch) -> None:\n"
    end_marker = "\n\ndef test_sharding_integration_falls_back_for_production_input_at_target"
    if source.count(start_marker) != 1 or source.count(end_marker) != 1:
        raise RuntimeError("geometry sharding regression block is not unique")
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    block = source[start:end]
    block = _replace_once(
        block,
        '    assert decision["provider_input_size_bytes"] == 81 * _MIB',
        '    assert decision["provider_input_size_bytes"] == 21 * _MIB',
        label="geometry sharding threshold assertion",
    )
    source = source[:start] + block + source[end:]
    TEST_COMPAT_PATH.write_text(source, encoding="utf-8")


def main() -> None:
    v2._patch_presentation_native_counts = _patch_presentation_native_counts_composed
    v3.main()
    _restore_concurrent_shard_source_access()
    _patch_composed_test_thresholds()
    print(
        "provider 20 MiB composition-aware overlay ready: "
        "per_shard_source_access=remote_first"
    )


if __name__ == "__main__":
    main()
