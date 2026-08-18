from typing import Any

from app.processing.errors import ProviderClientError, ProviderErrorCategory, ProviderErrorDetail
from app.processing.models import ProcessingPageIdentity, ProviderLifecycleStatus, ProviderProgress

STATUS_MAP = {
    "queued": ProviderLifecycleStatus.QUEUED,
    "running": ProviderLifecycleStatus.RUNNING,
    "completed": ProviderLifecycleStatus.PROVIDER_COMPLETED,
    "partial_failed": ProviderLifecycleStatus.PROVIDER_PARTIAL_FAILED,
    "failed": ProviderLifecycleStatus.FAILED,
    "expired": ProviderLifecycleStatus.EXPIRED,
}


def map_status(status: str) -> ProviderLifecycleStatus:
    try:
        return STATUS_MAP[status]
    except KeyError:
        raise ProviderClientError(
            ProviderErrorDetail(
                ProviderErrorCategory.MALFORMED_RESPONSE,
                f"unknown provider status: {status}",
            )
        )


def map_progress(payload: dict[str, Any]) -> ProviderProgress:
    pages_total = _optional_non_negative_int(payload.get("pages_total"), "pages_total")
    pages_completed = _optional_non_negative_int(payload.get("pages_completed"), "pages_completed")
    tasks_total = _optional_non_negative_int(payload.get("tasks_total"), "tasks_total")
    tasks_completed = _optional_non_negative_int(payload.get("tasks_completed"), "tasks_completed")
    percent_complete = payload.get("percent_complete")
    if percent_complete is not None and (not isinstance(percent_complete, (int, float)) or percent_complete < 0):
        raise ProviderClientError(
            ProviderErrorDetail(
                ProviderErrorCategory.MALFORMED_RESPONSE,
                "percent_complete must be a non-negative number when present",
            )
        )
    return ProviderProgress(
        pages_total,
        pages_completed,
        tasks_total,
        tasks_completed,
        float(percent_complete) if percent_complete is not None else None,
        payload.get("status") in {"completed", "partial_failed", "failed", "expired"},
    )


def map_pages(
    document_id: str,
    pages: list[dict[str, Any]],
    *,
    expected_pages_total: int | None = None,
) -> list[ProcessingPageIdentity]:
    identities = []
    seen_page_numbers = set()
    expected_from_ranges = set()
    for page in pages:
        page_number, page_index, local_page_index, range_start, range_end = _parse_page_metadata(page)
        expected_from_ranges.update(range(range_start, range_end + 1))
        if page_index != page_number - 1:
            raise _malformed("page_index must equal page_number - 1")
        if page_number < range_start or page_number > range_end:
            raise _malformed("page_number must fall within source_page_range")
        if local_page_index != page_number - range_start:
            raise _malformed("local_page_index inconsistent with source_page_range")
        if page_number in seen_page_numbers:
            raise _malformed(f"duplicate page_number {page_number}")
        seen_page_numbers.add(page_number)
        identities.append(
            ProcessingPageIdentity(
                document_id,
                page_number,
                page_index,
                local_page_index,
                (range_start, range_end),
            )
        )

    if expected_pages_total is not None:
        if expected_pages_total < 0:
            raise _malformed("expected_pages_total must be non-negative")
        expected_pages = set(range(1, expected_pages_total + 1))
    else:
        expected_pages = expected_from_ranges
    missing_pages = sorted(expected_pages - seen_page_numbers)
    if missing_pages:
        raise _malformed(f"missing page_number(s): {missing_pages}")
    return sorted(identities, key=lambda identity: identity.page_number)


def _parse_page_metadata(page: dict[str, Any]) -> tuple[int, int, int, int, int]:
    try:
        page_number = int(page["page_number"])
        page_index = int(page["page_index"])
        local_page_index = int(page["local_page_index"])
        source_page_range = page["source_page_range"]
        if isinstance(source_page_range, dict):
            range_start = int(source_page_range["page_start"])
            range_end = int(source_page_range["page_end"])
        else:
            range_start = int(source_page_range[0])
            range_end = int(source_page_range[1])
    except Exception as exc:
        raise _malformed(f"page metadata missing or malformed: {exc}")
    if page_number < 1 or page_index < 0 or local_page_index < 0 or range_start < 1 or range_end < range_start:
        raise _malformed("invalid page index/range values")
    return page_number, page_index, local_page_index, range_start, range_end


def _optional_non_negative_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or value < 0:
        raise ProviderClientError(
            ProviderErrorDetail(
                ProviderErrorCategory.MALFORMED_RESPONSE,
                f"{field_name} must be a non-negative integer when present",
            )
        )
    return value


def _malformed(message: str) -> ProviderClientError:
    return ProviderClientError(
        ProviderErrorDetail(ProviderErrorCategory.MALFORMED_RESPONSE, message)
    )
