"""Shared application-level admission policy for uploaded book sources.

Transport limits answer how bytes can reach Atlas. This policy answers how large
a retained source the current processing architecture is prepared to accept.
The two must not drift: resumable transport may technically move much larger
files, while PDF/TXT acceptance and canonical processing currently materialize
whole retained sources as bytes in process memory.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DEFAULT_BOOK_SOURCE_MAX_BYTES = 100 * 1024 * 1024


class BookSourceTooLarge(ValueError):
    """Raised before expensive transport/processing when a source exceeds policy."""


@dataclass(frozen=True, slots=True)
class BookSourceAdmission:
    byte_size: int
    max_bytes: int


def book_source_max_bytes(settings_obj: Any) -> int:
    value = getattr(settings_obj, "book_source_max_bytes", DEFAULT_BOOK_SOURCE_MAX_BYTES)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError("book source maximum must be a positive integer")
    return value


def validate_book_source_size(byte_size: int, settings_obj: Any) -> BookSourceAdmission:
    if not isinstance(byte_size, int) or isinstance(byte_size, bool) or byte_size < 0:
        raise ValueError("book source byte size must be a non-negative integer")
    maximum = book_source_max_bytes(settings_obj)
    if byte_size > maximum:
        raise BookSourceTooLarge(
            f"book source exceeds application limit of {maximum} bytes"
        )
    return BookSourceAdmission(byte_size=byte_size, max_bytes=maximum)


__all__ = [
    "BookSourceAdmission",
    "BookSourceTooLarge",
    "DEFAULT_BOOK_SOURCE_MAX_BYTES",
    "book_source_max_bytes",
    "validate_book_source_size",
]
