"""C07 event timeline normalization helpers."""

from __future__ import annotations

from typing import Any


def _code(value: Any) -> int | None:
    """Read integer API codes without treating booleans as event types."""
    if type(value) is int:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def event_image_layout(record: dict[str, Any]) -> str:
    """Follow the App's C07UltraDailyRecordAdapter event view selection."""
    event_type = _code(record.get("type"))
    if event_type in (0, 1, 2):
        return "cleaning"
    if event_type in (7, 99):
        return "camera_views"
    return "unknown"


def event_image_role(record: dict[str, Any], slot: str) -> str:
    """Describe reused pre/next slots according to the event's App view."""
    layout = event_image_layout(record)
    if slot == "before_image":
        return {"cleaning": "before_cleaning", "camera_views": "exterior_camera"}.get(
            layout, "image_1"
        )
    if slot == "after_image":
        return {"cleaning": "after_cleaning", "camera_views": "interior_camera"}.get(
            layout, "image_2"
        )
    return "on_site" if slot == "on_site_image" else "thumbnail"


def event_image_visible(record: dict[str, Any], slot: str) -> bool:
    """Honor the App's media flag even when an old picture URL is cached."""
    if slot not in ("before_image", "after_image"):
        return True
    flag = _code(record.get("media_display_flag"))
    if flag in (4, 5, 10):  # Expired media or both cameras closed.
        return False
    layout = event_image_layout(record)
    if layout == "cleaning":
        # Both cleaning pictures come from the interior (second) camera.
        return flag not in (7, 8)
    if layout == "camera_views":
        # 6/9 close the exterior camera; 7/8 close the interior camera.
        return flag not in ((6, 9) if slot == "before_image" else (7, 8))
    return True


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
    """Normalize one C07 timeline record and its App-defined image semantics."""
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
        "image_layout": event_image_layout(record),
        "before_image_role": event_image_role(record, "before_image"),
        "after_image_role": event_image_role(record, "after_image"),
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
