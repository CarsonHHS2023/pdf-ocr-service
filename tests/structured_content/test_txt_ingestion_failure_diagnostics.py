from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy.exc import DatabaseError as SQLAlchemyDatabaseError

from app.processing.txt.analyzer_client import TxtStructureAnalyzerClientError
from app.processing.txt.canonicalization import TxtCanonicalizationError
from app.processing.txt.ingestion import _safe_failure_fields, _safe_failure_message


def _wrapped_provider_error(*, status_code=None, stage="provider_http", retryable=False, contract_reason=None):
    provider = TxtStructureAnalyzerClientError(
        "bounded provider failure",
        status_code=status_code,
        retryable=retryable,
        stage=stage,
        contract_reason=contract_reason,
    )
    try:
        raise provider
    except TxtStructureAnalyzerClientError as exc:
        try:
            raise TxtCanonicalizationError(
                "retained TXT canonicalization failed",
                stage="local_analysis",
            ) from exc
        except TxtCanonicalizationError as wrapped:
            return wrapped


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (401, "TXT structure analysis provider authentication failed"),
        (403, "TXT structure analysis provider authentication failed"),
        (404, "TXT structure analysis model or endpoint was not found"),
        (429, "TXT structure analysis provider rate limit exceeded"),
        (503, "TXT structure analysis provider is temporarily unavailable"),
        (400, "TXT structure analysis provider rejected the request (HTTP 400)"),
    ],
)
def test_safe_provider_http_category_survives_canonicalization_wrapper(status_code, expected) -> None:
    wrapped = _wrapped_provider_error(status_code=status_code, retryable=status_code in {429, 503})
    assert _safe_failure_message(wrapped) == expected
    fields = _safe_failure_fields(wrapped)
    assert fields["outer_error_type"] == "TxtCanonicalizationError"
    assert fields["canonical_stage"] == "local_analysis"
    assert fields["provider_error_type"] == "TxtStructureAnalyzerClientError"
    assert fields["provider_status_code"] == status_code
    assert fields["provider_stage"] == "provider_http"
    assert fields["provider_contract_reason"] is None


@pytest.mark.parametrize(
    "stage",
    [
        "provider_json",
        "provider_output",
        "provider_output_json",
        "provider_output_contract",
        "local_structure_contract",
        "outline_contract",
    ],
)
def test_structured_output_failures_have_bounded_safe_message(stage) -> None:
    wrapped = _wrapped_provider_error(stage=stage)
    assert _safe_failure_message(wrapped) == "TXT structure analysis provider returned invalid structured output"


def test_contract_reason_is_logged_as_bounded_category_without_changing_user_message() -> None:
    wrapped = _wrapped_provider_error(
        stage="local_structure_contract",
        contract_reason="identity_set_mismatch",
    )
    assert _safe_failure_message(wrapped) == "TXT structure analysis provider returned invalid structured output"
    fields = _safe_failure_fields(wrapped)
    assert fields["provider_contract_reason"] == "identity_set_mismatch"


@pytest.mark.parametrize(
    ("stage", "expected"),
    [
        ("source_validation", "TXT retained source validation failed [source_validation]"),
        ("local_reconciliation", "TXT local structure reconciliation failed [local_reconciliation]"),
        ("spr_recovery", "TXT structured result recovery failed [spr_recovery]"),
        ("write_session_open", "TXT canonical write session could not be opened [write_session_open]"),
        ("write_identity_validation", "TXT retained source changed before canonical persistence [write_identity_validation]"),
        ("candidate_persistence", "TXT canonical candidate persistence failed [candidate_persistence]"),
        ("selection", "TXT Reader v2 candidate selection failed [selection]"),
        ("commit", "TXT canonical database commit failed [commit]"),
    ],
)
def test_canonicalization_stage_has_bounded_safe_message(stage, expected) -> None:
    error = TxtCanonicalizationError("internal details must not escape", stage=stage)
    assert _safe_failure_message(error) == expected
    fields = _safe_failure_fields(error)
    assert fields["canonical_stage"] == stage
    assert fields["canonical_error_type"] == "TxtCanonicalizationError"
    assert fields["root_error_type"] == "TxtCanonicalizationError"


def test_safe_failure_message_never_echoes_provider_exception_text() -> None:
    provider = TxtStructureAnalyzerClientError(
        "secret=sk-never-echo raw-provider-body=do-not-expose",
        status_code=400,
        stage="provider_http",
    )
    message = _safe_failure_message(provider)
    assert message == "TXT structure analysis provider rejected the request (HTTP 400)"
    assert "sk-never-echo" not in message
    assert "raw-provider-body" not in message


def test_safe_failure_message_never_echoes_canonical_exception_text() -> None:
    error = TxtCanonicalizationError(
        "database=secret-host raw-sql=do-not-expose",
        stage="candidate_persistence",
    )
    message = _safe_failure_message(error)
    assert message == "TXT canonical candidate persistence failed [candidate_persistence]"
    assert "secret-host" not in message
    assert "raw-sql" not in message


def test_sqlite_error_code_and_name_are_logged_without_sql_or_exception_text() -> None:
    class _SqliteCorrupt(sqlite3.DatabaseError):
        sqlite_errorcode = 11
        sqlite_errorname = "SQLITE_CORRUPT"

    raw = _SqliteCorrupt("database disk image is malformed; secret path must not escape")
    sqlalchemy_error = SQLAlchemyDatabaseError(
        "INSERT INTO structured_content_nodes_v2(text) VALUES (?)",
        ("secret document text",),
        raw,
    )
    try:
        raise sqlalchemy_error from raw
    except SQLAlchemyDatabaseError as db_exc:
        try:
            raise TxtCanonicalizationError(
                "retained TXT canonicalization failed",
                stage="candidate_persistence",
            ) from db_exc
        except TxtCanonicalizationError as wrapped:
            fields = _safe_failure_fields(wrapped)

    assert fields["sqlalchemy_error_type"] == "DatabaseError"
    assert fields["dbapi_error_type"] == "_SqliteCorrupt"
    assert fields["sqlite_error_code"] == 11
    assert fields["sqlite_error_name"] == "SQLITE_CORRUPT"
    serialized = " ".join(str(value) for value in fields.values())
    assert "secret document text" not in serialized
    assert "secret path" not in serialized
    assert "INSERT INTO" not in serialized
