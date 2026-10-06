"""Tests for VISUAL_C07 support."""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.catlink.devices.c07 import C07Device
from custom_components.catlink.devices.registry import DEVICE_TYPES
from custom_components.catlink.entities.button import CatlinkButtonEntity
from custom_components.catlink.entities.switch import CatlinkSwitchEntity
from homeassistant.components.button import DATA_COMPONENT as BUTTON_COMPONENT
from homeassistant.components.switch import DATA_COMPONENT as SWITCH_COMPONENT
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator."""
    coordinator = MagicMock()
    coordinator.account = MagicMock()
    coordinator.account.uid = "86-test-user"
    return coordinator


@pytest.fixture
def sample_c07_data():
    """Return a C07 list item."""
    return {
        "id": "c07-device-id",
        "mac": "AA:BB:CC:DD:EE:07",
        "model": "MODEL_00",
        "deviceName": "C07 test device",
        "deviceType": "VISUAL_C07",
    }


def mock_operation_feedback(device, final_status=""):
    """Return a fresh online device snapshot for operation command tests."""
    async def refresh():
        device.detail = {**device.detail, "online": True, "finalStatus": final_status}
        return device.detail

    device.update_device_detail = AsyncMock(side_effect=refresh)


def test_c07_is_registered() -> None:
    """VISUAL_C07 resolves to the dedicated device class."""
    assert DEVICE_TYPES["VISUAL_C07"] is C07Device


def test_c07_state_and_garbage_fields(mock_coordinator, sample_c07_data) -> None:
    """Expose C07 state fields and full-bin errors."""
    device = C07Device(sample_c07_data, mock_coordinator)
    device.detail = {
        "workStatus": "00",
        "runStatus": "00",
        "cleanStatus": "00",
        "garbageStatus": "00",
        "deviceErrorList": [],
        "online": True,
        "cameraSwitch": "11",
        "totalCleanTimes": 5,
    }

    assert device.state == "idle"
    assert device.online is True
    assert device.garbage_full is False
    assert device.garbage_nearly_full is False
    assert device.cat_detected is False
    assert device.camera_switch == "Both cameras"
    assert device.garbage_status == "Low"
    assert device.clean_status == "Idle"
    assert device.total_clean_time == 5
    assert device.state_attrs()["total_clean_times"] == 5
    assert device.state_attrs()["raw_camera_switch"] == "11"
    assert "garbage_status" in device.hass_sensor
    assert "last_event" in device.hass_sensor
    assert "last_event_before" in device.hass_image
    assert "camera_switch" not in device.hass_sensor
    assert "box_full_sensitivity" not in device.hass_sensor
    assert (
        not {
            "pave_level",
            "litter_type",
            "safe_time",
            "fill_light",
        }
        & device.hass_sensor.keys()
    )
    assert "action" not in device.hass_select
    assert "box_full_sensitivity" in device.hass_select
    assert "camera_switch_control" not in device.hass_select
    assert {"interior_camera", "exterior_camera"} <= device.hass_switch.keys()
    assert "pave_level_control" in device.hass_select
    assert "litter_type_control" in device.hass_select
    assert "safe_time_control" in device.hass_select
    assert "fill_light_control" in device.hass_select
    assert "add_sand_copies" in device.hass_number
    assert "fill_light" not in device.hass_switch
    assert "auto_clean" in device.hass_switch
    assert "key_lock" in device.hass_switch
    assert not {
        "temperature",
        "humidity",
        "litter_weight",
        "empty_status",
        "work_mode",
    } & device.hass_sensor.keys()
    assert "last_event_thumbnail" not in device.hass_image
    assert {
        "garbage_full",
        "garbage_nearly_full",
        "cat_detected",
        "sandbox_installed",
        "garbage_box_missing",
        "litter_low",
        "sandbox_low",
        "anti_pinch_protected",
        "engine_protected",
        "empty_state",
    }.issubset(device.hass_binary_sensor)

    device.detail["deviceErrorList"] = [{"errkey": "GARBAGE_FULL_ABNORMAL"}]
    assert device.garbage_full is True
    device.detail["deviceErrorList"] = [{"errkey": "GARBAGE_TOBE_FULL_ABNORMAL"}]
    assert device.garbage_full is False
    assert device.garbage_nearly_full is True
    device.detail["garbageStatus"] = "99"
    assert device.garbage_status == "Full"
    device.detail["garbageStatus"] = "01"
    assert device.garbage_status == "Full"
    device.detail["garbageStatus"] = "02"
    assert device.garbage_status == "Medium"
    device.detail["garbageStatus"] = "03"
    assert device.garbage_status == "Full"


@pytest.mark.parametrize(
    ("final_status", "expected"),
    [
        ("CLEAN_RUN", "Cleaning"),
        ("CLEAN_PAUSE", "Cleaning paused"),
        ("CLEAN_CANCEL", "Cancelling cleaning"),
        ("PAVE_RUN", "Paving"),
        ("PAVE_PAUSE", "Paving paused"),
        ("PAVE_CANCEL", "Cancelling paving"),
        ("EMPTY_RUN", "Emptying"),
        ("EMPTY_PAUSE", "Emptying paused"),
        ("EMPTY_CANCEL", "Cancelling emptying"),
        ("ADD_SAND_RUN", "Adding sand"),
        ("ADD_SAND_PAUSE", "Adding sand paused"),
        ("ADD_SAND_CANCEL", "Cancelling sand addition"),
    ],
)
def test_c07_apk_final_status_mapping(
    mock_coordinator, sample_c07_data, final_status, expected
) -> None:
    """Expose APK finalStatus values through the detailed clean status."""
    device = C07Device(sample_c07_data, mock_coordinator)
    device.detail = {
        "workStatus": "00",
        "finalStatus": final_status,
        "cleanStatus": "00",
    }

    assert device.state == "idle"
    assert device.clean_status == expected
    assert device.state_attrs()["final_status"] == final_status


def test_c07_unknown_final_status_falls_back_to_work_status(
    mock_coordinator, sample_c07_data
) -> None:
    """Unknown finalStatus values use the existing workStatus mapping."""
    device = C07Device(sample_c07_data, mock_coordinator)
    device.detail = {"workStatus": "01", "finalStatus": "UNKNOWN"}

    assert device.state == "running"


def test_c07_extended_status_fields(mock_coordinator, sample_c07_data) -> None:
    """Expose the C07 status fields used by the APK state page."""
    device = C07Device(sample_c07_data, mock_coordinator)
    device.detail = {
        "catLitterWeight": "2.5",
        "catLitterBalance": 1,
        "sandboxBalance": 2,
        "sandBoxInstall": True,
        "emptyState": False,
        "emptyStatus": "00",
        "temperature": "23.4",
        "humidity": "45.0",
        "litterType": 3,
        "sandPaveLevel": 2,
        "safeTime": "5",
        "autoSwitch": True,
        "kittenModel": "01",
        "keyLock": "01",
        "quietEnable": True,
        "continuousCleaning": "1",
        "softModel": False,
        "watermark": True,
        "voiceEnable": "01",
        "fillLight": 1,
        "paneltone": "ENABLED",
    }

    assert device.litter_weight == 2.5
    assert device.cat_litter_balance == "Low"
    assert device.sandbox_balance == "Medium"
    assert device.sandbox_installed is True
    assert device.empty_state is False
    assert device.empty_status == "00"
    assert device.temperature == 23.4
    assert device.humidity == 45.0
    assert device.litter_type == "Cassava"
    assert device.pave_level == 2
    assert device.pave_level_control == "Level 2"
    assert device.safe_time == "5 min"
    assert device.auto_clean is True
    assert device.kitty_model is True
    assert device.key_lock is True
    assert device.quiet_mode is True
    assert device.continuous_cleaning is True
    assert device.soft_model is False
    assert device.watermark is True
    assert device.voice_prompt is True
    assert device.fill_light == "Closed"
    assert device.fill_light_control == "Closed"
    assert device.panel_tone is True


def test_c07_unknown_select_values_are_unavailable(
    mock_coordinator, sample_c07_data
) -> None:
    """Do not expose values outside the options advertised by a select."""
    device = C07Device(sample_c07_data, mock_coordinator)
    device.detail = {
        "sandPaveLevel": 4,
        "litterType": 99,
        "safeTime": "9",
        "fillLight": 9,
    }

    assert device.pave_level_control is None
    assert device.litter_type_control is None
    assert device.safe_time_control is None
    assert device.fill_light_control is None


def test_c07_balance_falls_back_to_full_for_other_numeric_values(
    mock_coordinator, sample_c07_data
) -> None:
    """Follow the APK rule that balances other than 1/2 mean full."""
    device = C07Device(sample_c07_data, mock_coordinator)
    device.detail = {"catLitterBalance": 0, "sandboxBalance": 3}

    assert device.cat_litter_balance == "Full"
    assert device.sandbox_balance == "Full"


def test_c07_add_sand_copies_are_limited_to_apk_range(
    mock_coordinator, sample_c07_data
) -> None:
    """Keep the add-sand number within the APK's supported 1-3 range."""
    device = C07Device(sample_c07_data, mock_coordinator)

    device.add_sand_copies = 99
    assert device.add_sand_copies == 3
    device.add_sand_copies = 0
    assert device.add_sand_copies == 1


@pytest.mark.parametrize(
    ("error_key", "expected_error"),
    [
        ("RADAR_PROTECTED", "Normal Operation"),
        ("WEIGHT_PROTECTED", "Normal Operation"),
        ("SANDBOX_NOTENOUGH", "Sandbox not enough"),
        ("DEVICE_LITTER_NOTENOUGH", "Cat litter not enough"),
        ("GARBAGE_TOBE_FULL_ABNORMAL", "Garbage bin almost full"),
        ("GARBAGE_FULL_ABNORMAL", "Garbage bin full"),
        ("GARBAGE_BOX_UNINSTALL", "Garbage bin not installed"),
        ("DEVICE_ANTIPINCH_PROTECTION", "Anti-pinch protection"),
        ("ENGINE_PROTECTED", "Motor protection"),
    ],
)
def test_c07_error_mapping(
    mock_coordinator, sample_c07_data, error_key, expected_error
) -> None:
    """Map APK C07 protection and device errors without hiding raw details."""
    device = C07Device(sample_c07_data, mock_coordinator)
    device.detail = {"deviceErrorList": [{"errkey": error_key}]}

    assert device.error == expected_error
    assert error_key in device.error_attrs()["active_error_keys"]


def test_c07_known_error_takes_precedence_over_unknown_error(
    mock_coordinator, sample_c07_data
) -> None:
    """Prefer a mapped device error when the API also returns an unknown key."""
    device = C07Device(sample_c07_data, mock_coordinator)
    device.detail = {
        "deviceErrorList": [
            {"errkey": "NEW_UNKNOWN_ERROR"},
            {"errkey": "GARBAGE_FULL_ABNORMAL"},
        ]
    }

    assert device.error == "Garbage bin full"


def test_c07_unknown_error_uses_generic_label(
    mock_coordinator, sample_c07_data
) -> None:
    """Keep an unmapped device error visible through the generic label."""
    device = C07Device(sample_c07_data, mock_coordinator)
    device.detail = {"deviceErrorList": [{"errkey": "NEW_UNKNOWN_ERROR"}]}

    assert device.error == "Device error"


@pytest.mark.parametrize(
    ("raw_switch", "expected"),
    [
        ("00", "Off"),
        ("01", "Interior camera"),
        ("10", "Exterior camera"),
        ("11", "Both cameras"),
    ],
)
def test_c07_camera_switch_mapping(
    mock_coordinator, sample_c07_data, raw_switch, expected
) -> None:
    """Map the C07 camera bitmask while retaining its raw attribute."""
    device = C07Device(sample_c07_data, mock_coordinator)
    device.detail = {"cameraSwitch": raw_switch}

    assert device.camera_switch == expected
    assert device.state_attrs()["raw_camera_switch"] == raw_switch


def mock_camera_feedback(device, raw="00", online=True):
    """Supply fresh device camera feedback, independently of command acceptance."""
    async def refresh():
        device.detail = {**device.detail, "online": online, "cameraSwitch": raw}
        device._handle_listeners()
        return device.detail
    device.update_device_detail = AsyncMock(side_effect=refresh)


@pytest.mark.parametrize(
    ("raw", "interior", "exterior"),
    [("00", False, False), ("01", True, False), ("10", False, True),
     ("11", True, True), (None, None, None), ("", None, None),
     ("bad", None, None), (0, None, None), (False, None, None)],
)
def test_c07_individual_camera_feedback(mock_coordinator, sample_c07_data, raw, interior, exterior):
    device = C07Device(sample_c07_data, mock_coordinator)
    device.detail = {"cameraSwitch": raw}
    assert device.interior_camera is interior
    assert device.exterior_camera is exterior


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw", "camera", "enable", "target"),
    [("00", "interior_camera", True, "01"),
     ("10", "interior_camera", True, "11"),
     ("11", "interior_camera", False, "10"),
     ("01", "interior_camera", False, "00"),
     ("00", "exterior_camera", True, "10"),
     ("01", "exterior_camera", True, "11"),
     ("11", "exterior_camera", False, "01"),
     ("10", "exterior_camera", False, "00")],
)
async def test_c07_camera_switch_preserves_other_channel(
    mock_coordinator, sample_c07_data, raw, camera, enable, target
):
    device = C07Device(sample_c07_data, mock_coordinator)
    # Deliberately stale local state must not choose the other camera's bit.
    device.detail = {"online": True, "cameraSwitch": "11" if raw != "11" else "00"}
    mock_camera_feedback(device, raw)
    mock_coordinator.account.request = AsyncMock(return_value={"returnCode": 0})
    callback = device.hass_switch[camera]["async_turn_on" if enable else "async_turn_off"]
    assert await callback() is True
    mock_coordinator.account.request.assert_awaited_once_with(
        "token/cameraLitterbox/cameraSwitch",
        {"deviceId": device.id, "cameraSwitch": target}, "POST"
    )
    assert device.update_device_detail.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("camera", ["interior_camera", "exterior_camera"])
async def test_c07_camera_switch_skips_matching_fresh_state(mock_coordinator, sample_c07_data, camera):
    device = C07Device(sample_c07_data, mock_coordinator)
    mock_camera_feedback(device, "11")
    mock_coordinator.account.request = AsyncMock()
    assert await device.hass_switch[camera]["async_turn_on"]() is True
    mock_coordinator.account.request.assert_not_awaited()
    device.update_device_detail.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_c07_switch_control_skips_matching_state(
    mock_coordinator, sample_c07_data
) -> None:
    """Do not re-send a boolean setting that already matches the detail state."""
    device = C07Device(sample_c07_data, mock_coordinator)
    device.detail = {"autoSwitch": True}
    mock_coordinator.account.request = AsyncMock()
    device.update_device_detail = AsyncMock()

    assert await device.async_set_auto_clean(True) is True
    mock_coordinator.account.request.assert_not_awaited()
    device.update_device_detail.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [None, "bad", "", 0, False, {}, []])
async def test_c07_unknown_camera_feedback_rejects_write(mock_coordinator, sample_c07_data, raw):
    device = C07Device(sample_c07_data, mock_coordinator)
    mock_camera_feedback(device, raw)
    mock_coordinator.account.request = AsyncMock()
    with pytest.raises(HomeAssistantError, match="unknown"):
        await device.hass_switch["interior_camera"]["async_turn_on"]()
    mock_coordinator.account.request.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [{}, {"returnCode": 4001, "msg": "not allowed"},
    {"msg": "accepted"}, {"returnCode": False}, {"returnCode": 0.0}])
async def test_c07_camera_switch_failure_skips_post_refresh(mock_coordinator, sample_c07_data, response):
    device = C07Device(sample_c07_data, mock_coordinator)
    mock_camera_feedback(device)
    mock_coordinator.account.request = AsyncMock(return_value=response)
    with pytest.raises(HomeAssistantError):
        await device.hass_switch["interior_camera"]["async_turn_on"]()
    # The preflight read happened, but failed commands do not refresh afterwards.
    device.update_device_detail.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_c07_camera_switch_accepts_string_zero(mock_coordinator, sample_c07_data):
    device = C07Device(sample_c07_data, mock_coordinator)
    mock_camera_feedback(device)
    mock_coordinator.account.request = AsyncMock(return_value={"returnCode": "0"})
    assert await device.hass_switch["interior_camera"]["async_turn_on"]() is True
    assert device.update_device_detail.await_count == 2


@pytest.mark.asyncio
async def test_c07_camera_switch_uses_feedback_not_optimistic_command(hass, mock_coordinator, sample_c07_data):
    device = C07Device(sample_c07_data, mock_coordinator)
    mock_camera_feedback(device)
    mock_coordinator.account.request = AsyncMock(return_value={"returnCode": 0})
    entity = CatlinkSwitchEntity("interior_camera", device, device.hass_switch["interior_camera"])
    entity.hass = hass
    entity.entity_id = "switch.c07_test_interior_camera"
    device.listeners[entity.entity_id] = entity._handle_coordinator_update
    entity._handle_coordinator_update()
    assert await entity.async_turn_on() is True
    # Success without changed camera feedback is not proof that the camera is on.
    assert hass.states.get(entity.entity_id).state == "off"
    mock_camera_feedback(device, "01")
    await device.update_device_detail()
    assert hass.states.get(entity.entity_id).state == "on"
    device.detail = {"online": True}
    entity._handle_coordinator_update()
    assert hass.states.get(entity.entity_id).state == "unknown"


@pytest.mark.asyncio
async def test_c07_camera_switches_through_ha_services(
    hass, mock_coordinator, sample_c07_data
):
    """Native HA switch services publish both independent camera states."""
    coordinator = DataUpdateCoordinator(
        hass, logging.getLogger(__name__), name="c07-camera-test", config_entry=None
    )
    coordinator.account = mock_coordinator.account
    device = C07Device(sample_c07_data, coordinator)
    device.detail = {"online": True, "cameraSwitch": "00"}
    interior = CatlinkSwitchEntity(
        "interior_camera", device, device.hass_switch["interior_camera"]
    )
    exterior = CatlinkSwitchEntity(
        "exterior_camera", device, device.hass_switch["exterior_camera"]
    )
    assert await async_setup_component(hass, "switch", {})
    await hass.data[SWITCH_COMPONENT].async_add_entities([interior, exterior])
    await hass.async_block_till_done()
    remote_mask = "00"

    async def request(endpoint, params, method="GET"):
        nonlocal remote_mask
        if endpoint == "token/cameraLitterbox/info":
            return {"data": {"deviceInfo": {
                "online": True, "cameraSwitch": remote_mask
            }}}
        remote_mask = params["cameraSwitch"]
        return {"returnCode": 0}

    mock_coordinator.account.request = AsyncMock(side_effect=request)
    for entity, service, expected in (
        (interior, "turn_on", ("on", "off")),
        (exterior, "turn_on", ("on", "on")),
        (interior, "turn_off", ("off", "on")),
        (exterior, "turn_off", ("off", "off")),
    ):
        await hass.services.async_call(
            "switch", service, {"entity_id": entity.entity_id}, blocking=True
        )
        assert (
            hass.states.get(interior.entity_id).state,
            hass.states.get(exterior.entity_id).state,
        ) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("online", [False, True])
async def test_c07_camera_switch_rejects_missing_or_offline_feedback(
    mock_coordinator, sample_c07_data, online
):
    device = C07Device(sample_c07_data, mock_coordinator)
    device.detail = {"online": True, "cameraSwitch": "11"}
    response = (
        {"returnCode": 1003, "data": {}} if online else
        {"data": {"deviceInfo": {"online": False, "cameraSwitch": "11"}}}
    )
    mock_coordinator.account.request = AsyncMock(return_value=response)
    with pytest.raises(HomeAssistantError):
        await device.hass_switch["interior_camera"]["async_turn_off"]()
    mock_coordinator.account.request.assert_awaited_once_with(
        "token/cameraLitterbox/info", {"deviceId": device.id}
    )


@pytest.mark.asyncio
async def test_c07_delayed_camera_feedback_cannot_undo_other_camera(
    mock_coordinator, sample_c07_data
):
    """Block another compound write until the previous accepted mask is observed."""
    device = C07Device(sample_c07_data, mock_coordinator)
    feedback = "00"
    writes = []

    async def request(endpoint, params, method="GET"):
        await asyncio.sleep(0)
        if endpoint == "token/cameraLitterbox/info":
            return {"data": {"deviceInfo": {
                "online": True, "cameraSwitch": feedback
            }}}
        writes.append(params["cameraSwitch"])
        # The API accepts the setting, but its read endpoint remains behind.
        return {"returnCode": 0}

    mock_coordinator.account.request = AsyncMock(side_effect=request)
    results = await asyncio.gather(
        device.hass_switch["interior_camera"]["async_turn_on"](),
        device.hass_switch["exterior_camera"]["async_turn_on"](),
        return_exceptions=True,
    )
    assert results[0] is True
    assert isinstance(results[1], HomeAssistantError)
    assert "awaiting device confirmation" in str(results[1])
    assert writes == ["01"]  # Never POST stale 10, which would disable interior.
    assert device.interior_camera is False and device.exterior_camera is False

    # A normal device poll confirms the first write and releases the gate.
    feedback = "01"
    await device.update_device_detail()
    assert await device.hass_switch["exterior_camera"]["async_turn_on"]() is True
    assert writes == ["01", "11"]
    assert device.interior_camera is True and device.exterior_camera is False
    feedback = "11"
    await device.update_device_detail()
    assert device.interior_camera is True and device.exterior_camera is True


@pytest.mark.asyncio
async def test_c07_simultaneous_camera_switches_preserve_both_bits(mock_coordinator, sample_c07_data):
    device = C07Device(sample_c07_data, mock_coordinator)
    remote_mask = "00"
    writes = []
    async def request(endpoint, params, method="GET"):
        nonlocal remote_mask
        await asyncio.sleep(0)
        if endpoint == "token/cameraLitterbox/info":
            return {"data": {"deviceInfo": {"online": True, "cameraSwitch": remote_mask}}}
        remote_mask = params["cameraSwitch"]
        writes.append(remote_mask)
        return {"returnCode": 0}
    mock_coordinator.account.request = AsyncMock(side_effect=request)
    await asyncio.gather(
        device.hass_switch["interior_camera"]["async_turn_on"](),
        device.hass_switch["exterior_camera"]["async_turn_on"](),
    )
    assert writes == ["01", "11"]
    assert device.interior_camera is True and device.exterior_camera is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "endpoint", "payload"),
    [
        (
            "async_set_auto_clean",
            "token/cameraLitterbox/autoClean",
            {"deviceId": "c07-device-id", "switchFlag": True},
        ),
        (
            "async_set_kitty_model",
            "token/cameraLitterbox/kittyModelSwitch",
            {"deviceId": "c07-device-id", "enable": True},
        ),
        (
            "async_set_key_lock",
            "token/cameraLitterbox/keyLock",
            {"deviceId": "c07-device-id", "lockStatus": True},
        ),
        (
            "async_set_quiet_mode",
            "token/cameraLitterbox/quietMode",
            {"deviceId": "c07-device-id", "enable": True},
        ),
        (
            "async_set_continuous_cleaning",
            "token/cameraLitterbox/continuousCleaning",
            {"deviceId": "c07-device-id", "enable": True},
        ),
        (
            "async_set_soft_model",
            "token/cameraLitterbox/deepClean/softModel",
            {"deviceId": "c07-device-id", "enable": True},
        ),
        (
            "async_set_panel_tone",
            "token/cameraLitterbox/paneltone",
            {"deviceId": "c07-device-id", "enable": True},
        ),
        (
            "async_set_watermark",
            "token/cameraLitterbox/watermarkSwitch",
            {"deviceId": "c07-device-id", "enable": True},
        ),
        (
            "async_set_voice_prompt",
            "token/cameraLitterbox/voicePromptSwitch",
            {"deviceId": "c07-device-id", "enable": True},
        ),
    ],
)
async def test_c07_switch_controls_use_apk_endpoints(
    mock_coordinator, sample_c07_data, method, endpoint, payload
) -> None:
    """Use the APK endpoint and payload for every C07 switch control."""
    device = C07Device(sample_c07_data, mock_coordinator)
    mock_coordinator.account.request = AsyncMock(return_value={"returnCode": 0})
    device.update_device_detail = AsyncMock(return_value={})

    assert await getattr(device, method)(True) is True
    mock_coordinator.account.request.assert_awaited_once_with(endpoint, payload, "POST")
    device.update_device_detail.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_c07_switch_control_forwards_false_payload(
    mock_coordinator, sample_c07_data
) -> None:
    """Forward the off value unchanged to a C07 switch endpoint."""
    device = C07Device(sample_c07_data, mock_coordinator)
    mock_coordinator.account.request = AsyncMock(return_value={"returnCode": 0})
    device.update_device_detail = AsyncMock(return_value={})

    assert await device.async_set_auto_clean(False) is True
    mock_coordinator.account.request.assert_awaited_once_with(
        "token/cameraLitterbox/autoClean",
        {"deviceId": "c07-device-id", "switchFlag": False},
        "POST",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "endpoint", "payload", "value"),
    [
        (
            "select_pave_level",
            "token/cameraLitterbox/paveLevel",
            {"deviceId": "c07-device-id", "level": "2"},
            "Level 2",
        ),
        (
            "select_litter_type",
            "token/cameraLitterbox/catLitterSetting",
            {"deviceId": "c07-device-id", "litterType": 3},
            "Cassava",
        ),
        (
            "select_safe_time",
            "token/cameraLitterbox/safeTimeSetting",
            {"deviceId": "c07-device-id", "safeTime": "5"},
            "5 min",
        ),
        (
            "select_fill_light",
            "token/cameraLitterbox/fillLightSetting",
            {"deviceId": "c07-device-id", "status": "0"},
            "Always open",
        ),
    ],
)
async def test_c07_setting_selects_use_apk_endpoints(
    mock_coordinator, sample_c07_data, method, endpoint, payload, value
) -> None:
    """Use the APK endpoint and payload for C07 setting selects."""
    device = C07Device(sample_c07_data, mock_coordinator)
    mock_coordinator.account.request = AsyncMock(return_value={"returnCode": 0})
    device.update_device_detail = AsyncMock(return_value={})

    assert await getattr(device, method)(value) is True
    mock_coordinator.account.request.assert_awaited_once_with(endpoint, payload, "POST")
    device.update_device_detail.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_c07_add_sand_copies_are_sent_with_run_action(
    mock_coordinator, sample_c07_data
) -> None:
    """Use the configured copy count for the APK add-sand command."""
    device = C07Device(sample_c07_data, mock_coordinator)
    device.add_sand_copies = 3
    mock_coordinator.account.request = AsyncMock(return_value={"returnCode": 0})
    mock_operation_feedback(device)

    await device.hass_button["add_sand_start"]["async_press"]()
    mock_coordinator.account.request.assert_awaited_once_with(
        "token/cameraLitterbox/actionCmd/v2",
        {
            "deviceId": "c07-device-id",
            "behavior": "ADD_SAND",
            "action": "RUN",
            "copies": "3",
        },
        "POST",
    )


@pytest.mark.asyncio
async def test_c07_fill_light_auto_uses_status_two(
    mock_coordinator, sample_c07_data
) -> None:
    """Use the APK status code for automatic fill-light mode."""
    device = C07Device(sample_c07_data, mock_coordinator)
    mock_coordinator.account.request = AsyncMock(return_value={"returnCode": 0})
    device.update_device_detail = AsyncMock(return_value={})

    assert await device.select_fill_light("Auto") is True
    mock_coordinator.account.request.assert_awaited_once_with(
        "token/cameraLitterbox/fillLightSetting",
        {"deviceId": "c07-device-id", "status": "2"},
        "POST",
    )


@pytest.mark.asyncio
async def test_c07_action_error_takes_precedence_over_device_error(
    mock_coordinator, sample_c07_data
) -> None:
    """Keep the immediate action failure visible until the next refresh."""
    device = C07Device(sample_c07_data, mock_coordinator)
    device.detail = {"deviceErrorList": [{"errkey": "ENGINE_PROTECTED"}]}
    mock_operation_feedback(device)
    mock_coordinator.account.request = AsyncMock(
        return_value={"returnCode": 4001, "msg": "not allowed"}
    )

    with pytest.raises(HomeAssistantError, match="not allowed"):
        await device.hass_button["clean_start"]["async_press"]()
    assert device.error == "not allowed (returnCode: 4001)"


def test_c07_box_full_sensitivity_mapping(mock_coordinator, sample_c07_data) -> None:
    """Map supported levels and leave unknown API values unavailable."""
    device = C07Device(sample_c07_data, mock_coordinator)
    device.detail = {"boxFullSensitivity": 2}
    assert device.box_full_sensitivity == "Level 2"
    assert list(device.box_full_levels.values()) == ["Level 1", "Level 2"]

    device.detail["boxFullSensitivity"] = 4
    assert device.box_full_sensitivity is None


@pytest.mark.asyncio
async def test_c07_update_device_detail_uses_camera_endpoint(
    mock_coordinator, sample_c07_data
) -> None:
    """Use the camera-specific C07 endpoint instead of token/device/info."""
    device = C07Device(sample_c07_data, mock_coordinator)
    mock_coordinator.account.request = AsyncMock(
        return_value={"data": {"deviceInfo": {"online": True, "cleanStatus": "00"}}}
    )

    result = await device.update_device_detail()

    assert result["online"] is True
    mock_coordinator.account.request.assert_awaited_once_with(
        "token/cameraLitterbox/info", {"deviceId": "c07-device-id"}
    )


@pytest.mark.asyncio
async def test_c07_update_device_detail_keeps_previous_data_on_failure(
    mock_coordinator, sample_c07_data
) -> None:
    """Do not turn all C07 entities unknown on a failed detail refresh."""
    device = C07Device(sample_c07_data, mock_coordinator)
    previous = {"online": True, "cameraSwitch": "11", "finalStatus": "CLEAN_RUN"}
    device.detail = previous
    mock_coordinator.account.request = AsyncMock(
        return_value={"returnCode": 1003, "data": {}}
    )

    assert await device.update_device_detail() is previous
    assert device.detail is previous
    assert device.clean_status == "Cleaning"


@pytest.mark.asyncio
async def test_c07_update_events_normalizes_records_and_resolves_picture_ids(
    mock_coordinator, sample_c07_data
) -> None:
    """Normalize the timeline and resolve missing before/after image URLs."""
    device = C07Device(sample_c07_data, mock_coordinator)
    mock_coordinator.account.hass.config.time_zone = "UTC"

    async def request(api, params=None, method="GET"):
        if api == "token/litterbox/stats/log/timeline":
            return {
                "data": {
                    "records": [
                        {
                            "id": "event-1",
                            "event": "Cats appear",
                            "time": "2026-09-13 10:00:00",
                            "picIdOfPre": "before-1",
                            "picOnSite": "onsite-1",
                            "eventPicAfter": "https://example.invalid/after.jpg",
                            "eventPicThumbUrl": "https://example.invalid/thumb.jpg",
                        }
                    ],
                    "total": 1,
                }
            }
        if api == "token/cameraLitterbox/getPicUrl":
            return {
                "data": {
                    "picUrl": {
                        "before-1": "https://example.invalid/before.jpg",
                        "onsite-1": "https://example.invalid/onsite.jpg",
                    }[params["picId"]]
                }
            }
        raise AssertionError(api)

    mock_coordinator.account.request = AsyncMock(side_effect=request)

    result = await device.update_events()

    assert result["last_event"]["event_id"] == "event-1"
    assert device.last_event == "Cats appear"
    assert device.event_image_url("last_event_before") == (
        "https://example.invalid/before.jpg"
    )
    assert device.event_image_url("last_event_after") == (
        "https://example.invalid/after.jpg"
    )
    assert device.event_image_url("last_event_on_site") == (
        "https://example.invalid/onsite.jpg"
    )
    attrs = device.last_event_attrs()
    assert attrs["event"] == "Cats appear"
    assert "records" not in attrs
    assert "total" not in attrs
    assert "current" not in attrs
    assert "pages" not in attrs


@pytest.mark.asyncio
async def test_c07_update_events_keeps_previous_data_on_failure(
    mock_coordinator, sample_c07_data
) -> None:
    """A failed event refresh must not clear the last successful event."""
    device = C07Device(sample_c07_data, mock_coordinator)
    previous = {
        "records": [{"event_id": "event-1"}],
        "last_event": {"event_id": "event-1", "event": "poop"},
        "total": 1,
        "current": 1,
        "pages": 1,
    }
    device.event_data = previous
    mock_coordinator.account.request = AsyncMock(return_value={})

    assert await device.update_events() is previous


@pytest.mark.asyncio
async def test_c07_async_init_skips_unsupported_logs(
    hass, mock_coordinator, sample_c07_data
) -> None:
    """C07 initialization must not require the generic log endpoint."""
    device = C07Device(sample_c07_data, mock_coordinator)
    mock_coordinator.account.hass = hass
    mock_coordinator.config_entry = None
    mock_coordinator.account.hass.config.time_zone = "UTC"
    mock_coordinator.account.request = AsyncMock(
        return_value={"data": {"deviceInfo": {"online": True}}}
    )

    await device.async_init()

    calls = mock_coordinator.account.request.await_args_list
    assert calls[0].args == (
        "token/cameraLitterbox/info",
        {"deviceId": "c07-device-id"},
    )
    assert calls[1].args[0] == "token/litterbox/stats/log/timeline"


@pytest.mark.asyncio
async def test_c07_clean_button_can_be_pressed_repeatedly_through_ha(
    hass, mock_coordinator, sample_c07_data
) -> None:
    """Each HA button.press call sends RUN and keeps HA's press timestamp."""
    coordinator = DataUpdateCoordinator(
        hass, logging.getLogger(__name__), name="c07-test", config_entry=None
    )
    coordinator.account = mock_coordinator.account
    device = C07Device(sample_c07_data, coordinator)
    device.detail = {"online": True, "finalStatus": ""}
    entity = CatlinkButtonEntity(
        "clean_start", device, device.hass_button["clean_start"]
    )
    assert await async_setup_component(hass, "button", {})
    await hass.data[BUTTON_COMPONENT].async_add_entities([entity])
    await hass.async_block_till_done()

    mock_coordinator.account.request = AsyncMock(
        side_effect=[
            {"data": {"deviceInfo": {"online": True, "finalStatus": ""}}},
            {"returnCode": 0},
            {"data": {"deviceInfo": {"online": True, "finalStatus": "CLEAN_RUN"}}},
            {"data": {"deviceInfo": {
                "online": True, "finalStatus": "", "cleanStatus": "00"
            }}},
            {"data": {"deviceInfo": {"online": True, "finalStatus": ""}}},
            {"returnCode": 0},
            {"data": {"deviceInfo": {"online": True, "finalStatus": "CLEAN_RUN"}}},
        ]
    )
    await hass.services.async_call(
        "button", "press", {"entity_id": entity.entity_id}, blocking=True
    )
    assert dt_util.parse_datetime(hass.states.get(entity.entity_id).state) is not None
    await device.update_device_detail()
    assert device.clean_status == "Idle"
    await hass.services.async_call(
        "button", "press", {"entity_id": entity.entity_id}, blocking=True
    )
    commands = [
        call for call in mock_coordinator.account.request.await_args_list
        if call.args[0] == "token/cameraLitterbox/actionCmd/v2"
    ]
    assert len(commands) == 2
    assert all(call.args[1]["action"] == "RUN" for call in commands)
    assert dt_util.parse_datetime(hass.states.get(entity.entity_id).state) is not None


@pytest.mark.asyncio
async def test_c07_command_buttons_use_existing_payloads(
    mock_coordinator, sample_c07_data
) -> None:
    """Four start buttons preserve operation semantics and add-sand quantities."""
    device = C07Device(sample_c07_data, mock_coordinator)
    device.add_sand_copies = 2
    mock_coordinator.account.request = AsyncMock(return_value={"returnCode": 0})
    mock_operation_feedback(device)
    assert set(device.hass_button) == {
        "clean_start", "pave_start", "empty_start", "add_sand_start",
        "operation_pause", "operation_resume", "operation_cancel",
    }
    for behavior in ("CLEAN", "PAVE", "EMPTY", "ADD_SAND"):
        command = "RUN"
        key = f"{behavior.lower()}_start"
        await device.hass_button[key]["async_press"]()
        payload = {"deviceId": device.id, "behavior": behavior, "action": command}
        if behavior == "ADD_SAND" and command == "RUN":
            payload["copies"] = "2"
        mock_coordinator.account.request.assert_awaited_with(
            "token/cameraLitterbox/actionCmd/v2", payload, "POST"
        )


@pytest.mark.asyncio
async def test_c07_button_rejection_raises_ha_error(
    mock_coordinator, sample_c07_data
) -> None:
    """A rejected press must fail the HA service rather than silently return."""
    device = C07Device(sample_c07_data, mock_coordinator)
    mock_operation_feedback(device)
    mock_coordinator.account.request = AsyncMock(
        return_value={"returnCode": 4001, "msg": "not allowed"}
    )
    with pytest.raises(HomeAssistantError, match="not allowed"):
        await device.hass_button["clean_start"]["async_press"]()


@pytest.mark.asyncio
@pytest.mark.parametrize("behavior", ["CLEAN", "PAVE", "EMPTY", "ADD_SAND"])
@pytest.mark.parametrize(
    ("key", "phase", "command"),
    [
        ("operation_pause", "RUN", "PAUSE"),
        ("operation_resume", "PAUSE", "RUN"),
        ("operation_cancel", "RUN", "CANCEL"),
        ("operation_cancel", "PAUSE", "CANCEL"),
    ],
)
async def test_c07_shared_controls_follow_fresh_app_operation(
    mock_coordinator, sample_c07_data, behavior, key, phase, command
) -> None:
    """Resolve App-started tasks from fresh feedback, not cached HA commands."""
    device = C07Device(sample_c07_data, mock_coordinator)
    device.detail = {"online": True, "finalStatus": "EMPTY_RUN"}
    device.add_sand_copies = 3
    mock_operation_feedback(device, f"{behavior}_{phase}")
    mock_coordinator.account.request = AsyncMock(return_value={"returnCode": 0})

    await device.hass_button[key]["async_press"]()

    mock_coordinator.account.request.assert_awaited_once_with(
        "token/cameraLitterbox/actionCmd/v2",
        {"deviceId": device.id, "behavior": behavior, "action": command},
        "POST",
    )
    # In particular, resuming ADD_SAND must not submit copies again.
    assert device.update_device_detail.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "final_status"),
    [
        ("clean_start", "PAVE_RUN"),
        ("clean_start", "CLEAN_RUN"),
        ("clean_start", "CLEAN_PAUSE"),
        ("operation_pause", ""),
        ("operation_pause", "CLEAN_PAUSE"),
        ("operation_resume", ""),
        ("operation_resume", "CLEAN_RUN"),
        ("operation_cancel", ""),
        ("clean_start", "CLEAN_CANCEL"),
        ("operation_pause", "CLEAN_CANCEL"),
        ("operation_resume", "CLEAN_CANCEL"),
        ("operation_cancel", "CLEAN_CANCEL"),
        ("operation_pause", "NEW_UNKNOWN_STATUS"),
        ("clean_start", {"unexpected": "status"}),
    ],
)
async def test_c07_invalid_operation_controls_send_no_command(
    mock_coordinator, sample_c07_data, key, final_status
) -> None:
    """Reject conflicting, stale, or inapplicable controls before POST."""
    device = C07Device(sample_c07_data, mock_coordinator)
    mock_operation_feedback(device, final_status)
    mock_coordinator.account.request = AsyncMock()

    with pytest.raises(HomeAssistantError):
        await device.hass_button[key]["async_press"]()
    mock_coordinator.account.request.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        {"returnCode": 1003, "data": {}},
        {"data": {"deviceInfo": {"online": False, "finalStatus": "CLEAN_RUN"}}},
        {"data": {"deviceInfo": {"online": True}}},
    ],
)
async def test_c07_current_control_rejects_unconfirmed_feedback(
    mock_coordinator, sample_c07_data, response
) -> None:
    """Never use a stale cached operation when its fresh status is unavailable."""
    device = C07Device(sample_c07_data, mock_coordinator)
    device.detail = {"online": True, "finalStatus": "CLEAN_RUN"}
    mock_coordinator.account.request = AsyncMock(return_value=response)

    with pytest.raises(HomeAssistantError):
        await device.hass_button["operation_pause"]["async_press"]()
    mock_coordinator.account.request.assert_awaited_once_with(
        "token/cameraLitterbox/info", {"deviceId": device.id}
    )


@pytest.mark.asyncio
async def test_c07_simultaneous_starts_refresh_under_one_lock(
    mock_coordinator, sample_c07_data
) -> None:
    """The second start checks feedback after the first operation is accepted."""
    device = C07Device(sample_c07_data, mock_coordinator)
    remote_status = ""

    async def request(endpoint, params, method="GET"):
        nonlocal remote_status
        await asyncio.sleep(0)
        if endpoint == "token/cameraLitterbox/info":
            return {"data": {"deviceInfo": {
                "online": True, "finalStatus": remote_status
            }}}
        remote_status = f"{params['behavior']}_{params['action']}"
        return {"returnCode": 0}

    mock_coordinator.account.request = AsyncMock(side_effect=request)
    result = await asyncio.gather(
        device.hass_button["clean_start"]["async_press"](),
        device.hass_button["pave_start"]["async_press"](),
        return_exceptions=True,
    )
    assert result[0] is None
    assert isinstance(result[1], HomeAssistantError)
    commands = [
        call for call in mock_coordinator.account.request.await_args_list
        if call.args[0] == "token/cameraLitterbox/actionCmd/v2"
    ]
    assert len(commands) == 1
    assert commands[0].args[1]["behavior"] == "CLEAN"


@pytest.mark.asyncio
async def test_c07_cancel_waits_for_device_idle_feedback(
    mock_coordinator, sample_c07_data
) -> None:
    """A successful CANCEL response is not evidence of completed cancellation."""
    device = C07Device(sample_c07_data, mock_coordinator)
    mock_coordinator.account.request = AsyncMock(side_effect=[
        {"data": {"deviceInfo": {"online": True, "finalStatus": "CLEAN_RUN"}}},
        {"returnCode": 0},
        {"data": {"deviceInfo": {"online": True, "finalStatus": "CLEAN_CANCEL"}}},
        {"data": {"deviceInfo": {
            "online": True, "finalStatus": "", "cleanStatus": "00"
        }}},
    ])
    await device.hass_button["operation_cancel"]["async_press"]()
    assert device.clean_status == "Cancelling cleaning"
    await device.update_device_detail()
    assert device.clean_status == "Idle"


@pytest.mark.asyncio
async def test_c07_unknown_box_full_level_is_rejected(
    mock_coordinator, sample_c07_data
) -> None:
    """Do not send unsupported C07 sensitivity levels to the API."""
    device = C07Device(sample_c07_data, mock_coordinator)
    mock_coordinator.account.request = AsyncMock()

    assert await device.select_box_full_sensitivity("Level 3") is False
    mock_coordinator.account.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_c07_box_full_sensitivity_uses_c07_endpoint(
    mock_coordinator, sample_c07_data
) -> None:
    """Set C07 box-full sensitivity using its string level payload."""
    device = C07Device(sample_c07_data, mock_coordinator)
    mock_coordinator.account.request = AsyncMock(return_value={"returnCode": 0})
    device.update_device_detail = AsyncMock(return_value={})

    assert await device.select_box_full_sensitivity("Level 2") is True
    mock_coordinator.account.request.assert_awaited_once_with(
        "token/cameraLitterbox/boxfullSensitivity",
        {"deviceId": "c07-device-id", "level": "2"},
        "POST",
    )
