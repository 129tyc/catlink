"""C07 event timeline normalization helpers."""

from __future__ import annotations

from typing import Any


def _image_url(value: Any) -> str | None:
    """Return a direct image URL from an API value."""
    if isinstance(value, dict):
        for key in ("url", "picUrl", "imageUrl", "thumbnailUrl"):
            result = value.get(key)
            if isinstance(result, str) and result.startswith(("http://", "https://")):
                return result
        return None
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return value
    return None


def _image_id(value: Any) -> str | None:
    """Return a picture/storage ID when a field is not already a URL."""
    if isinstance(value, str) and value and not value.startswith(("http://", "https://")):
        return value
    return None


def normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    """Normalize one C07 timeline record without guessing image semantics."""
    return {
        "event_id": record.get("id"),
        "event": record.get("event"),
        "subtitle": record.get("subTitle"),
        "time": record.get("time"),
        "event_start": record.get("eventStart"),
        "event_end": record.get("eventEnd"),
        "type": record.get("type"),
        "biz_type": record.get("bizType"),
        "pet_id": record.get("petId"),
        "pet_avatar": record.get("petAvatar"),
        "before_image": _image_url(record.get("eventPicBefore")),
        "after_image": _image_url(record.get("eventPicAfter")),
        "on_site_image": _image_url(record.get("picOnSite")),
        "on_site_image_id": _image_id(record.get("picOnSite")),
        "thumbnail": _image_url(record.get("eventPicThumbUrl")),
        "before_image_id": record.get("picIdOfPre"),
        "after_image_id": record.get("picIdOfNext"),
        "video_url": _image_url(record.get("videoUrl")),
        "move_detect_id": record.get("moveDetectId"),
        "media_display_flag": record.get("mediaDisplayFlag"),
    }


def normalize_records(records: Any, limit: int = 10) -> list[dict[str, Any]]:
    """Normalize and de-duplicate timeline records."""
    if not isinstance(records, list):
        return []
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in records:
        if not isinstance(raw, dict):
            continue
        item = normalize_record(raw)
        key = str(item.get("event_id") or "")
        if not key:
            key = "|".join(
                str(item.get(field) or "")
                for field in ("time", "event", "event_start", "pet_id")
            )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def empty_event_data() -> dict[str, Any]:
    """Return the stable empty event coordinator payload."""
    return {
        "records": [],
        "last_event": None,
        "total": 0,
        "current": None,
        "pages": None,
    }
