"""F05 event/media contracts using hand-authored synthetic records."""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

from custom_components.catlink.devices.f05 import F05Device
from custom_components.catlink.entities.image import CatlinkImageEntity
from custom_components.catlink.entities.sensor import CatlinkSensorEntity
from custom_components.catlink.models.f05_events import apply_images, images_visible, normalize_records


@pytest.fixture
def device(hass):
    coordinator = DataUpdateCoordinator(hass, logging.getLogger(__name__), name="f05-events-parent", config_entry=None)
    coordinator.account = MagicMock()
    coordinator.account.hass = hass
    coordinator.account.request = AsyncMock()
    return F05Device({"id": "test-f05", "deviceType": "VISUAL_F05", "deviceName": "Test feeder", "mac": "AA:BB:CC:DD:EE:05"}, coordinator)


def row(kind="EAT", flag=2, event_id="event-test"):
    return {"id": event_id, "type": kind, "subEvent": "EAT" if kind == "EAT" else "R_AUTO",
            "event": "Eating" if kind == "EAT" else "Food dispensed", "time": "12:30:00",
            "createTime": 1770118200000, "mediaDisplayFlag": flag,
            "firstSection": "5 g", "secondSection": "2 min",
            "picId0": "synthetic-zero", "picId1": "synthetic-one", "picId2": "synthetic-two"}


def response(rows):
    return {"returnCode": 0, "data": {"feederLogs": {"total": str(len(rows)), "rows": rows}, "endFlag": True}}


def test_normalization_preserves_f05_fields_and_type_scoped_ids():
    rows = normalize_records([row(), row(), row("FOOD_OUT")])
    assert len(rows) == 2
    assert rows[0]["event_start"] == 1770118200000
    assert rows[0]["first_section"] == "5 g"
    assert rows[1]["sub_event"] == "R_AUTO"
    assert "before_image" not in rows[0]


@pytest.mark.parametrize(("flag", "visible"), [(0, True), (2, True), (1, False), (3, False), (4, False), (None, False), (99, False)])
def test_f05_visibility_is_not_c07_visibility(flag, visible):
    record = normalize_records([row(flag=flag)])[0]
    assert images_visible(record) is visible
    record["sub_event"] = "R_AUTO_ERR"
    assert not images_visible(record)


def test_picture_urls_match_storage_ids_and_missing_slots_stay_empty():
    records = normalize_records([row()])
    apply_images(records, [{"storageId": "synthetic-two", "url": "https://example.invalid/2.jpg"},
                           {"storageId": "synthetic-zero", "url": "https://example.invalid/0.jpg"}])
    assert records[0]["image_0"] == "https://example.invalid/0.jpg"
    assert records[0]["image_1"] is None
    assert records[0]["image_2"] == "https://example.invalid/2.jpg"


async def test_events_use_feeder_timeline_and_batch_picture_api(device, monkeypatch):
    monkeypatch.setattr("custom_components.catlink.devices.f05.dt_util.now", lambda tz: dt_util.parse_datetime("2026-02-03T12:30:00+00:00"))
    device.account.request.side_effect = [response([row(), row("FOOD_OUT", event_id="other")]),
        {"returnCode": 0, "data": [{"storageId": "synthetic-zero", "url": "https://example.invalid/event.jpg?signature=synthetic"}]}]
    await device.update_events()
    first, second = device.account.request.await_args_list
    assert first.args == ("token/device/feederpro/stats/timeline", {"deviceId": "test-f05", "date": "2026-02-03", "type": 0, "pageNumber": 1, "pageSize": 10})
    assert second.args == ("token/media/ezviz/list/pics", {"picIds": "synthetic-zero,synthetic-one,synthetic-two"})
    assert device.last_event == "Eating"
    assert device.event_image_url("last_event_image_0").endswith("signature=synthetic")
    assert "signature" not in str(device.last_event_attrs())
    assert "signature" not in str(device.event_image_attrs(0))


@pytest.mark.parametrize("flag", [1, 3, 4])
async def test_hidden_media_skips_resolution_and_clears_old_images(device, flag):
    device.event_data = {"last_event": {"media_display_flag": 0, "image_0": "https://example.invalid/old.jpg"}}
    device.account.request.return_value = response([row(flag=flag)])
    await device.update_events()
    device.account.request.assert_awaited_once()
    assert device.event_image_url("last_event_image_0") is None


async def test_empty_events_clear_previous_event(device):
    device.event_data = {"last_event": {"event": "Old event"}}
    device.account.request.return_value = response([])
    await device.update_events()
    assert device.last_event == "unknown"
    assert device.event_image_url("last_event_image_0") is None


@pytest.mark.parametrize("payload", [{}, {"returnCode": 0, "data": None}, {"returnCode": 0, "data": {"feederLogs": {"rows": None}}}])
async def test_event_failure_preserves_last_success(device, payload):
    previous = device.event_data
    device.account.request.return_value = payload
    with pytest.raises(UpdateFailed):
        await device.update_events()
    assert device.event_data is previous


async def test_picture_failure_does_not_discard_event(device):
    device.account.request.side_effect = [response([row()]), {"returnCode": 42}]
    await device.update_events()
    assert device.last_event == "Eating"
    assert device.event_image_url("last_event_image_0") is None


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_real_event_entities_follow_refresh_and_clear_images(hass, device):
    device.event_coordinator = DataUpdateCoordinator(hass, logging.getLogger(__name__), name="f05-event-images", config_entry=None)
    records = normalize_records([row()])
    apply_images(records, [{"storageId": "synthetic-zero", "url": "https://example.invalid/event.jpg"}])
    device.event_data = {"last_event": records[0], "records": records}
    device.event_coordinator.async_set_updated_data(device.event_data)
    image = CatlinkImageEntity("last_event_image_0", device, device.hass_image["last_event_image_0"])
    sensor = CatlinkSensorEntity("last_event", device, device.hass_sensor["last_event"])
    await async_setup_component(hass, "sensor", {})
    await async_setup_component(hass, "image", {})
    await hass.data["sensor"].async_add_entities([sensor])
    await hass.data["image"].async_add_entities([image])
    await hass.async_block_till_done()
    assert hass.states.get(sensor.entity_id).state == "Eating"
    assert image.available
    assert image.image_last_updated == dt_util.utc_from_timestamp(records[0]["event_start"] / 1000)
    device.event_data = {"last_event": None, "records": []}
    device.event_coordinator.async_set_updated_data(device.event_data)
    assert hass.states.get(sensor.entity_id).state == "unknown"
    assert not image.available


async def test_event_query_uses_ha_local_date_at_utc_midnight(hass, device):
    from freezegun import freeze_time
    await hass.config.async_set_time_zone("America/Toronto")
    device.account.request.return_value = response([])
    with freeze_time("2026-02-04T01:00:00+00:00"):
        await device.update_events()
    assert device.account.request.await_args.args[1]["date"] == "2026-02-03"
