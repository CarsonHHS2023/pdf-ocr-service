from pathlib import Path


def test_production_pdf_diagnostics_use_uvicorn_error_logger() -> None:
    source = Path("app/processing/pdf_ingestion.py").read_text(encoding="utf-8")

    assert 'logger = logging.getLogger("uvicorn.error")' in source
    assert "PDF canonicalization failed" in source
    assert "safe_reason=%s" in source
