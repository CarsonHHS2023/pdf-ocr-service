"""Composition-aware final wrapper for the 20 MiB Staging Provider overlay.

The native-text overlay already rewrites presentation accounting before this
wrapper runs in Staging CI.  This wrapper teaches the final 20 MiB overlay to
accept that composed source shape instead of assuming the pre-native source.
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


def _replace_once(source: str, old: str, new: str, *, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one source match, found {count}")
    return source.replace(old, new, 1)


def _patch_presentation_native_counts_composed() -> None:
    source = PREPROCESS_PATH.read_text(encoding="utf-8")

    # Production-equivalent Staging applies native text before this overlay.
    # Preserve its already-correct accounting and add the explicit Provider
    # exclusion alias used by sharding diagnostics.  Keep support for the older
    # pre-native source shape so the patch remains deterministic in focused tests.
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

    # Both local-result and explicit exclusion counts mean exactly the pages that
    # must not be sent to the Provider.  Use one name for the reuse decision.
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


def main() -> None:
    # v3 calls the v2 main function.  Replace only the one composition-sensitive
    # phase; all 20 MiB sharding, concurrency, diagnostics, test patches, and the
    # failed-shard identity fix continue through their existing reviewed path.
    v2._patch_presentation_native_counts = _patch_presentation_native_counts_composed
    v3.main()
    print("provider 20 MiB composition-aware overlay ready")


if __name__ == "__main__":
    main()
