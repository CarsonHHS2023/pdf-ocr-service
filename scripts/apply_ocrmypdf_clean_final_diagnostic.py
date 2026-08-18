from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label} anchor not found")
    return text.replace(old, new, 1)


def main() -> None:
    dockerfile_path = Path("Dockerfile")
    dockerfile = dockerfile_path.read_text(encoding="utf-8")
    dockerfile = replace_once(
        dockerfile,
        "    tesseract-ocr-osd \\\n    && rm -rf /var/lib/apt/lists/*",
        "    tesseract-ocr-osd \\\n    unpaper \\\n    && rm -rf /var/lib/apt/lists/*",
        "Dockerfile package",
    )
    dockerfile_path.write_text(dockerfile, encoding="utf-8")

    preprocessing_path = Path("app/processing/pdf_geometry_preprocessing.py")
    preprocessing = preprocessing_path.read_text(encoding="utf-8")
    preprocessing = replace_once(
        preprocessing,
        'GEOMETRY_PREPROCESSING_VERSION = "ocrmypdf_provider_preprocess_force_v1"',
        'GEOMETRY_PREPROCESSING_VERSION = "ocrmypdf_provider_preprocess_none_clean_final_diagnostic_v4"',
        "version",
    )
    preprocessing = replace_once(
        preprocessing,
        '        "--ocr-engine",\n        "tesseract",\n        "--tesseract-timeout",\n        "0",',
        '        "--ocr-engine",\n        "none",',
        "engine",
    )
    preprocessing = replace_once(
        preprocessing,
        '        "--remove-background",\n',
        '        "--clean-final",\n',
        "background option",
    )
    preprocessing = replace_once(
        preprocessing,
        '        "--optimize",\n        "0",\n        "--jobs",',
        '        "--optimize",\n        "0",\n        "-v",\n        "1",\n        "--jobs",',
        "verbosity",
    )
    preprocessing = replace_once(
        preprocessing,
        "        try:\n            _, stderr = process.communicate(timeout=timeout_seconds)\n        except subprocess.TimeoutExpired as exc:",
        "        try:\n            stdout, stderr = process.communicate(timeout=timeout_seconds)\n        except subprocess.TimeoutExpired as exc:",
        "communicate",
    )
    preprocessing = replace_once(
        preprocessing,
        '''        if process.returncode != 0:\n            logger.warning(\n                "OCRmyPDF exited unsuccessfully returncode=%s stderr_tail=%r",\n                process.returncode,\n                (stderr or "")[-1000:],\n            )\n            raise OcrmypdfPreprocessingError(\n                f"ocrmypdf_exit_{process.returncode}"\n            )''',
        '''        if process.returncode != 0:\n            print(\n                "OCRMY_PDF_RUNNER_FAILED "\n                f"returncode={process.returncode} command={command!r} "\n                f"stdout_tail={(stdout or '')[-4000:]!r} "\n                f"stderr_tail={(stderr or '')[-12000:]!r}",\n                flush=True,\n            )\n            logger.warning(\n                "OCRmyPDF exited unsuccessfully returncode=%s stderr_tail=%r",\n                process.returncode,\n                (stderr or "")[-4000:],\n            )\n            raise OcrmypdfPreprocessingError(\n                f"ocrmypdf_exit_{process.returncode}"\n            )\n\n        print(\n            "OCRMY_PDF_RUNNER_COMPLETED "\n            f"returncode=0 command={command!r} "\n            f"stdout_tail={(stdout or '')[-4000:]!r} "\n            f"stderr_tail={(stderr or '')[-12000:]!r}",\n            flush=True,\n        )''',
        "runner diagnostics",
    )
    preprocessing_path.write_text(preprocessing, encoding="utf-8")

    bounded_path = Path("app/processing/pdf_geometry_bounded.py")
    bounded = bounded_path.read_text(encoding="utf-8")
    bounded = replace_once(
        bounded,
        '''    changed = tuple(\n        source.render_sha256 != output.render_sha256\n        for source, output in zip(source_pages, output_pages, strict=True)\n    )\n    if not any(changed):\n        return _unchanged_result(pdf_bytes, source_pages)\n\n    page_results = tuple(''',
        '''    source_checksum = hashlib.sha256(pdf_bytes).hexdigest()\n    processed_checksum = hashlib.sha256(processed_bytes).hexdigest()\n    changed = tuple(\n        source.render_sha256 != output.render_sha256\n        for source, output in zip(source_pages, output_pages, strict=True)\n    )\n    print(\n        "OCRMY_PDF_DIAGNOSTIC "\n        f"disposition={'processed_visual_change' if any(changed) else 'processed_no_visual_change'} "\n        f"source_size_bytes={len(pdf_bytes)} "\n        f"output_size_bytes={len(processed_bytes)} "\n        f"source_sha256={source_checksum} "\n        f"output_sha256={processed_checksum} "\n        f"byte_identical={source_checksum == processed_checksum} "\n        f"visual_changed_page_count={sum(changed)}",\n        flush=True,\n    )\n\n    page_results = tuple(''',
        "bounded no-change",
    )
    bounded = replace_once(
        bounded,
        "    checksum = hashlib.sha256(processed_bytes).hexdigest()\n",
        "    checksum = processed_checksum\n",
        "bounded checksum",
    )
    bounded_path.write_text(bounded, encoding="utf-8")

    integration_path = Path("app/processing/pdf_geometry_integration.py")
    integration = integration_path.read_text(encoding="utf-8")
    integration = replace_once(
        integration,
        '''    processed = preprocess_pdf_geometry(\n        source_pdf_bytes,\n        expected_page_count=expected_page_count,\n    )\n    reference = _geometry_pdf_reference(''',
        '''    processed = preprocess_pdf_geometry(\n        source_pdf_bytes,\n        expected_page_count=expected_page_count,\n    )\n    source_checksum = hashlib.sha256(source_pdf_bytes).hexdigest()\n    fallback_reasons = sorted(\n        {page.safe_reason for page in processed.pages if page.safe_reason}\n    )\n    diagnostic_dir = Path("/data/output/ocrmypdf-diagnostics")\n    diagnostic_dir.mkdir(parents=True, exist_ok=True)\n    diagnostic_path = diagnostic_dir / (\n        f"{processing_attempt_id}-{processed.checksum_sha256[:16]}.pdf"\n    )\n    temporary_diagnostic_path = diagnostic_path.with_suffix(".pdf.tmp")\n    temporary_diagnostic_path.write_bytes(processed.pdf_bytes)\n    temporary_diagnostic_path.replace(diagnostic_path)\n    print(\n        "PDF_OCRMYPDF_DIAGNOSTIC_RETAINED "\n        f"processing_attempt_id={processing_attempt_id} "\n        f"path={diagnostic_path} "\n        f"source_size_bytes={len(source_pdf_bytes)} "\n        f"output_size_bytes={processed.byte_size} "\n        f"source_sha256={source_checksum} "\n        f"output_sha256={processed.checksum_sha256} "\n        f"byte_identical={source_checksum == processed.checksum_sha256} "\n        f"changed_page_count={processed.changed_page_count} "\n        f"fallback_used={any(page.fallback_used for page in processed.pages)} "\n        f"fallback_reasons={fallback_reasons!r}",\n        flush=True,\n    )\n    reference = _geometry_pdf_reference(''',
        "integration retention",
    )
    integration_path.write_text(integration, encoding="utf-8")


if __name__ == "__main__":
    main()
