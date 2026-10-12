"""App-derived C07 image meanings, visibility, and HA state transitions."""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.components.image import DATA_COMPONENT
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.setup import async_setup_component

from custom_components.catlink.devices.c07 import C07Device
from custom_components.catlink.entities.image import CatlinkImageEntity
from custom_components.catlink.models.c07_events import normalize_record


@pytest.fixture
def device(hass):
    """Build a C07 with independent device and event coordinators."""
    coordinator = DataUpdateCoordinator(
        hass, logging.getLogger(__name__), name="c07-test", config_entry=None
    )
    coordinator.account = MagicMock()
    coordinator.account.hass = hass
    coordinator.account.uid = "test-account"
    device = C07Device(
        {
            "id": "test-device",
            "mac": "AA:BB:CC:DD:EE:07",
            "deviceName": "C07",
            "deviceType": "VISUAL_C07",
        },
        coordinator,
    )
    device.event_coordinator = DataUpdateCoordinator(
        hass, logging.getLogger(__name__), name="c07-images-test", config_entry=None
    )
    device.event_coordinator.account = coordinator.account
    return device


def event(event_type, flag=0):
    """Use both slots even when the App says one must be hidden."""
    return normalize_record(
        {
            "id": "event-1",
            "type": event_type,
            "mediaDisplayFlag": flag,
            "time": "2026-10-13 10:00:00",
            "eventPicBefore": "https://example.invalid/pre.jpg",
            "eventPicAfter": "https://example.invalid/next.jpg",
            "picOnSite": "https://example.invalid/site.jpg",
        }
    )


@pytest.mark.parametrize(
    ("event_type", "layout", "roles"),
    [
        (0, "cleaning", ("before_cleaning", "after_cleaning")),
        (1, "cleaning", ("before_cleaning", "after_cleaning")),
        (2, "cleaning", ("before_cleaning", "after_cleaning")),
        ("1", "cleaning", ("before_cleaning", "after_cleaning")),
        (7, "camera_views", ("exterior_camera", "interior_camera")),
        ("7", "camera_views", ("exterior_camera", "interior_camera")),
        (99, "camera_views", ("exterior_camera", "interior_camera")),
        (3, "unknown", ("image_1", "image_2")),
        (None, "unknown", ("image_1", "image_2")),
        (True, "unknown", ("image_1", "image_2")),
    ],
)
def test_image_roles_follow_app_event_views(device, event_type, layout, roles):
    """Distinguish cleaning, camera views, and unknown types without event text."""
    record = event(event_type)
    device.event_data = {"last_event": record}
    assert record["image_layout"] == layout
    assert (record["before_image_role"], record["after_image_role"]) == roles
    assert device.event_image_attrs("last_event_before")["image_role"] == roles[0]
    assert device.event_image_attrs("last_event_after")["image_role"] == roles[1]
    assert device.event_image_attrs("last_event_on_site")["image_role"] == "on_site"


@pytest.mark.parametrize("event_type", [1, 7, 99])
@pytest.mark.parametrize("as_string", [False, True])
@pytest.mark.parametrize("flag", [0, 4, 5, 6, 7, 8, 9, 10])
def test_media_flags_hide_closed_or_expired_pictures(
    device, event_type, as_string, flag
):
    """Never serve retained URLs for a camera the App marks closed."""
    record = event(event_type, str(flag) if as_string else flag)
    device.event_data = {"last_event": record}
    if event_type == 1:
        expected = (False, False) if flag in (4, 5, 7, 8, 10) else (True, True)
    else:
        expected = (
            flag not in (4, 5, 6, 9, 10),
            flag not in (4, 5, 7, 8, 10),
        )
    assert bool(device.event_image_url("last_event_before")) == expected[0]
    assert bool(device.event_image_url("last_event_after")) == expected[1]
    # On-site pictures have their own field; the App pre/next rules do not label it.
    assert device.event_image_url("last_event_on_site") == record["on_site_image"]


async def test_closed_camera_skips_picture_lookup(device):
    """Skip URL lookup for the closed exterior camera but still resolve interior."""
    record = normalize_record(
        {"type": 7, "mediaDisplayFlag": "9", "picIdOfPre": "pre", "picIdOfNext": "next"}
    )
    device.account.request = AsyncMock(
        return_value={"data": {"picUrl": "https://example.invalid/next.jpg"}}
    )
    await device._resolve_event_image(record)
    device.account.request.assert_awaited_once_with(
        "token/cameraLitterbox/getPicUrl", {"deviceId": device.id, "picId": "next"}
    )


async def test_image_semantics_and_names_transition_in_ha(hass, device):
    """Reuse the same registered images across cleaning and camera events."""
    device.event_data = {"last_event": event(1)}
    before = CatlinkImageEntity(
        "last_event_before", device, device.hass_image["last_event_before"]
    )
    after = CatlinkImageEntity(
        "last_event_after", device, device.hass_image["last_event_after"]
    )
    await async_setup_component(hass, "image", {})
    await hass.data[DATA_COMPONENT].async_add_entities([before, after])
    identities = [(entity.entity_id, entity.unique_id) for entity in (before, after)]

    for event_type, suffixes, roles in [
        (1, ("before cleaning", "after cleaning"), ("before_cleaning", "after_cleaning")),
        (7, ("exterior camera", "interior camera"), ("exterior_camera", "interior_camera")),
        (99, ("exterior camera", "interior camera"), ("exterior_camera", "interior_camera")),
        (None, ("image 1", "image 2"), ("image_1", "image_2")),
        (2, ("before cleaning", "after cleaning"), ("before_cleaning", "after_cleaning")),
    ]:
        device.event_data = {"last_event": event(event_type)}
        for entity, suffix, role in zip((before, after), suffixes, roles, strict=True):
            entity._handle_coordinator_update()
            state = hass.states.get(entity.entity_id)
            assert state.state != "unavailable"
            assert state.attributes["friendly_name"] == f"C07 Last event {suffix}"
            assert state.attributes["image_role"] == role
            assert "before_image" not in state.attributes
        assert [(entity.entity_id, entity.unique_id) for entity in (before, after)] == identities

    # An explicit user name must remain authoritative over automatic event labels.
    er.async_get(hass).async_update_entity(before.entity_id, name="My event image")
    await hass.async_block_till_done()
    device.event_data = {"last_event": event(7, 8)}
    for entity in (before, after):
        entity._handle_coordinator_update()
    assert hass.states.get(before.entity_id).attributes["friendly_name"] == "My event image"
    assert hass.states.get(after.entity_id).state == "unavailable"

    # Expiry must hide both existing pictures, not retain a previous visible URL.
    device.event_data = {"last_event": event(7, 4)}
    for entity in (before, after):
        entity._handle_coordinator_update()
        assert hass.states.get(entity.entity_id).state == "unavailable"

    device.event_data = {"last_event": event(7)}
    device.event_coordinator.last_update_success = False
    for entity in (before, after):
        entity._handle_coordinator_update()
        assert hass.states.get(entity.entity_id).state == "unavailable"

    device.event_coordinator.last_update_success = True
    device.event_data = {"last_event": None}
    for entity in (before, after):
        entity._handle_coordinator_update()
        assert hass.states.get(entity.entity_id).state == "unavailable"
