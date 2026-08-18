"""Patch presentation provenance rebuilding to thaw frozen metadata safely."""
from __future__ import annotations

from pathlib import Path


def _replace_once(path: Path, old: str, new: str, *, label: str) -> None:
    source = path.read_text(encoding="utf-8")
    if new in source:
        return
    if source.count(old) != 1:
        raise RuntimeError(f"Could not find unique {label} in {path}")
    path.write_text(source.replace(old, new, 1), encoding="utf-8")


def _patch_presentation_provenance_rebuild() -> None:
    path = Path("app/processing/pdf_page_presentation_lifecycle_compat.py")
    import_anchor = (
        "from app.storage.models import PutResult, StorageReference\n"
    )
    import_replacement = (
        "from app.processing.raw_result import RawResultProviderProvenance\n"
        "from app.storage.models import PutResult, StorageReference\n"
    )
    _replace_once(
        path,
        import_anchor,
        import_replacement,
        label="presentation provenance import anchor",
    )

    helper_anchor = '''def _usable_pre_ocr_boundary_review(page: Mapping[str, object]) -> bool:
'''
    helper_replacement = '''def _rebuild_presentation_provider_provenance(
    provider: RawResultProviderProvenance,
    configuration: Mapping[str, Any],
) -> RawResultProviderProvenance:
    """Rebuild provenance without deepcopying frozen MappingProxyType values."""

    from app.processing import pdf_geometry_integration as integration

    return RawResultProviderProvenance(
        build_tag=provider.build_tag,
        model_version=provider.model_version,
        pipeline_version=provider.pipeline_version,
        configuration=integration._thaw_metadata(configuration),
        capabilities=integration._thaw_metadata(provider.capabilities),
        timestamps=integration._thaw_metadata(provider.timestamps),
        warnings=tuple(integration._thaw_metadata(provider.warnings)),
        errors=tuple(integration._thaw_metadata(provider.errors)),
    )


def _usable_pre_ocr_boundary_review(page: Mapping[str, object]) -> bool:
'''
    _replace_once(
        path,
        helper_anchor,
        helper_replacement,
        label="presentation provenance helper anchor",
    )

    unsafe_rebuild = '''        return replace(
            envelope,
            provider=replace(
                envelope.provider,
                configuration=configuration,
            ),
        )
'''
    safe_rebuild = '''        return replace(
            envelope,
            provider=_rebuild_presentation_provider_provenance(
                envelope.provider,
                configuration,
            ),
        )
'''
    _replace_once(
        path,
        unsafe_rebuild,
        safe_rebuild,
        label="unsafe frozen presentation provenance rebuild",
    )


def main() -> None:
    _patch_presentation_provenance_rebuild()


if __name__ == "__main__":
    main()
