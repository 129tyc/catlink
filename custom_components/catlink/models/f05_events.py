"""Normalize the F05 feeder timeline without C07 image assumptions."""


def normalize_records(rows: list[dict]) -> list[dict]:
    """Keep API ordering, event details and the three F05 picture slots."""
    records = []
    seen = set()
    for row in rows:
        key = (row.get("type"), row.get("id"))
        if key in seen:
            continue
        seen.add(key)
        records.append({
            "event_id": row.get("id"),
            "event": row.get("event"),
            "type": row.get("type"),
            "sub_event": row.get("subEvent"),
            "time": row.get("time"),
            "event_start": row.get("createTime"),
            "first_section": row.get("firstSection"),
            "second_section": row.get("secondSection"),
            "pet_id": row.get("petId"),
            "pet_name": row.get("petName"),
            "video_start": row.get("startVideoTime"),
            "video_end": row.get("endVideoTime"),
            "media_display_flag": row.get("mediaDisplayFlag"),
            **{f"image_{slot}_id": row.get(f"picId{slot}") for slot in range(3)},
        })
    return records


def images_visible(record: dict) -> bool:
    """App flags 0/2 allow images; 1/3 close the camera and 4 expires media."""
    return record.get("media_display_flag") in (0, 2) and not str(
        record.get("sub_event") or ""
    ).endswith("_ERR")


def apply_images(records: list[dict], pictures: list[dict]) -> None:
    """Match resolved URLs by storageId, never by response ordering."""
    urls = {
        item["storageId"]: item["url"]
        for item in pictures
        if item.get("storageId") and isinstance(item.get("url"), str)
        and item["url"].startswith(("http://", "https://"))
    }
    for record in records:
        if images_visible(record):
            for slot in range(3):
                record[f"image_{slot}"] = urls.get(record.get(f"image_{slot}_id"))
