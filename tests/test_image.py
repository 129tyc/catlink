"""Tests for CATLINK event image entities."""

from types import SimpleNamespace

from homeassistant.util import dt as dt_util

from custom_components.catlink.entities.image import CatlinkImageEntity


def image_entity(record: dict) -> CatlinkImageEntity:
    """Create an image entity with only the state needed by _event_time."""
    entity = object.__new__(CatlinkImageEntity)
    entity._device = SimpleNamespace(event_data={"last_event": record})
    entity.account = SimpleNamespace(
        hass=SimpleNamespace(config=SimpleNamespace(time_zone="UTC"))
    )
    return entity


def test_event_time_parses_unix_seconds() -> None:
    """Parse CATLINK's numeric eventStart as Unix seconds."""
    entity = image_entity(
        {
            "event_start": "1789347255",
            "time": "20:55",
            "event_date": "2026-09-13",
        }
    )

    assert entity._event_time() == dt_util.utc_from_timestamp(1789347255)


def test_event_time_falls_back_to_local_time_field() -> None:
    """Use the event time field when eventStart is absent."""
    entity = image_entity(
        {
            "event_start": "not-a-date",
            "time": "21:04",
            "event_date": "2026-09-13",
        }
    )

    assert entity._event_time().isoformat() == "2026-09-13T21:04:00+00:00"
