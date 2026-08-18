from __future__ import annotations
from .types import ReaderContentStreamEntry, ReaderContentStreamEntryType
IMAGE_MARKER_PREFIX = "$%$%$%"
IMAGE_MARKER_SUFFIX = "$%$%$%"

def make_heading_line(text: str, level: int) -> str:
    return "#" * max(1, min(level, 6)) + " " + text.strip()

def make_image_marker(image_id: object) -> str:
    return f"{IMAGE_MARKER_PREFIX}{image_id}{IMAGE_MARKER_SUFFIX}"

def serialize_reader_content_stream_v2(entries: tuple[ReaderContentStreamEntry, ...]) -> str:
    lines = [entry.text.strip() if entry.entry_type is not ReaderContentStreamEntryType.IMAGE_MARKER else entry.text for entry in entries if entry.text.strip()]
    return "\n".join(lines)
