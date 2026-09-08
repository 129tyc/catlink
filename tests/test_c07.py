"""Tests for VISUAL_C07 support."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.catlink.devices.c07 import C07Device
from custom_components.catlink.devices.registry import DEVICE_TYPES


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
    assert "action" in device.hass_select
    assert "box_full_sensitivity" in device.hass_select
    assert "camera_switch_control" in device.hass_select
    assert "pave_level_control" in device.hass_select
    assert "litter_type_control" in device.hass_select
    assert "safe_time_control" in device.hass_select
    assert "fill_light_control" in device.hass_select
    assert "add_sand_copies" in device.hass_number
    assert "fill_light" not in device.hass_switch
    assert "auto_clean" in device.hass_switch
    assert "key_lock" in device.hass_switch
    assert "temperature" in device.hass_sensor
    assert "humidity" in device.hass_sensor
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
        ("CLEAN_CANCEL", "Idle"),
        ("PAVE_RUN", "Paving"),
        ("PAVE_PAUSE", "Paving paused"),
        ("PAVE_CANCEL", "Idle"),
        ("EMPTY_RUN", "Emptying"),
        ("EMPTY_PAUSE", "Emptying paused"),
        ("EMPTY_CANCEL", "Idle"),
        ("ADD_SAND_RUN", "Adding sand"),
        ("ADD_SAND_PAUSE", "Adding sand paused"),
        ("ADD_SAND_CANCEL", "Idle"),
    ],
)
def test_c07_apk_final_status_mapping(
    mock_coordinator, sample_c07_data, final_status, expected
) -> None:
    """Use APK finalStatus values before the generic workStatus fallback."""
    device = C07Device(sample_c07_data, mock_coordinator)
    device.detail = {
        "workStatus": "00",
        "finalStatus": final_status,
        "cleanStatus": "00",
    }

    assert device.state == expected
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
        ("01", "Second camera"),
        ("10", "Main camera"),
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("label", "camera_switch"),
    [
        ("Off", "00"),
        ("Second camera", "01"),
        ("Main camera", "10"),
        ("Both cameras", "11"),
    ],
)
async def test_c07_camera_switch_control_uses_camera_switch_endpoint(
    mock_coordinator, sample_c07_data, label, camera_switch
) -> None:
    """Control each C07 camera channel combination using the APK endpoint."""
    device = C07Device(sample_c07_data, mock_coordinator)
    mock_coordinator.account.request = AsyncMock(return_value={"returnCode": 0})
    device.update_device_detail = AsyncMock(return_value={})

    assert await device.select_camera_switch(label) is True
    mock_coordinator.account.request.assert_awaited_once_with(
        "token/cameraLitterbox/cameraSwitch",
        {"deviceId": "c07-device-id", "cameraSwitch": camera_switch},
        "POST",
    )
    device.update_device_detail.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_c07_camera_switch_control_rejects_invalid_option(
    mock_coordinator, sample_c07_data
) -> None:
    """Do not send unsupported camera switch values to the API."""
    device = C07Device(sample_c07_data, mock_coordinator)
    mock_coordinator.account.request = AsyncMock()

    assert await device.select_camera_switch("Invalid camera") is False
    mock_coordinator.account.request.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        {},
        {"returnCode": 4001, "msg": "not allowed"},
    ],
)
async def test_c07_camera_switch_control_failure_skips_refresh(
    mock_coordinator, sample_c07_data, response
) -> None:
    """Report camera switch failures without refreshing stale state."""
    device = C07Device(sample_c07_data, mock_coordinator)
    mock_coordinator.account.request = AsyncMock(return_value=response)
    device.update_device_detail = AsyncMock(return_value={})

    assert await device.select_camera_switch("Both cameras") is False
    device.update_device_detail.assert_not_awaited()


@pytest.mark.asyncio
async def test_c07_missing_return_code_is_failure(
    mock_coordinator, sample_c07_data
) -> None:
    """Do not treat a malformed response without returnCode as success."""
    device = C07Device(sample_c07_data, mock_coordinator)
    mock_coordinator.account.request = AsyncMock(return_value={"msg": "accepted"})
    device.update_device_detail = AsyncMock(return_value={})

    assert await device.select_camera_switch("Both cameras") is False
    device.update_device_detail.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("return_code", [False, 0.0])
async def test_c07_non_integer_zero_return_code_is_failure(
    mock_coordinator, sample_c07_data, return_code
) -> None:
    """Do not accept boolean or float zero as a numeric API success code."""
    device = C07Device(sample_c07_data, mock_coordinator)
    mock_coordinator.account.request = AsyncMock(
        return_value={"returnCode": return_code}
    )
    device.update_device_detail = AsyncMock(return_value={})

    assert await device.select_camera_switch("Both cameras") is False
    device.update_device_detail.assert_not_awaited()


@pytest.mark.asyncio
async def test_c07_string_zero_return_code_is_success(
    mock_coordinator, sample_c07_data
) -> None:
    """Accept the string zero form used by some API responses."""
    device = C07Device(sample_c07_data, mock_coordinator)
    mock_coordinator.account.request = AsyncMock(return_value={"returnCode": "0"})
    device.update_device_detail = AsyncMock(return_value={})

    assert await device.select_camera_switch("Both cameras") is True
    device.update_device_detail.assert_awaited_once_with()


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
    device.update_device_detail = AsyncMock(return_value={})

    assert await device.select_action("Add sand: start") is True
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
    mock_coordinator.account.request = AsyncMock(
        return_value={"returnCode": 4001, "msg": "not allowed"}
    )

    assert await device.select_action("Clean: start") is False
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
async def test_c07_async_init_skips_unsupported_logs(
    mock_coordinator, sample_c07_data
) -> None:
    """C07 initialization must not require the generic log endpoint."""
    device = C07Device(sample_c07_data, mock_coordinator)
    mock_coordinator.account.request = AsyncMock(
        return_value={"data": {"deviceInfo": {"online": True}}}
    )

    await device.async_init()

    mock_coordinator.account.request.assert_awaited_once_with(
        "token/cameraLitterbox/info", {"deviceId": "c07-device-id"}
    )


@pytest.mark.asyncio
async def test_c07_clean_action_uses_existing_action_select_pattern(
    mock_coordinator, sample_c07_data
) -> None:
    """Start cleaning through the C07 action command endpoint."""
    device = C07Device(sample_c07_data, mock_coordinator)
    mock_coordinator.account.request = AsyncMock(return_value={"returnCode": 0})
    device.update_device_detail = AsyncMock(return_value={})

    assert await device.select_action("Clean: start") is True
    mock_coordinator.account.request.assert_awaited_once_with(
        "token/cameraLitterbox/actionCmd/v2",
        {"deviceId": "c07-device-id", "behavior": "CLEAN", "action": "RUN"},
        "POST",
    )
    device.update_device_detail.assert_awaited_once_with()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("label", "behavior", "action"),
    [
        ("Clean: start", "CLEAN", "RUN"),
        ("Clean: pause", "CLEAN", "PAUSE"),
        ("Clean: cancel", "CLEAN", "CANCEL"),
        ("Pave: start", "PAVE", "RUN"),
        ("Pave: pause", "PAVE", "PAUSE"),
        ("Pave: cancel", "PAVE", "CANCEL"),
        ("Empty: start", "EMPTY", "RUN"),
        ("Empty: pause", "EMPTY", "PAUSE"),
        ("Empty: cancel", "EMPTY", "CANCEL"),
        ("Add sand: start", "ADD_SAND", "RUN"),
        ("Add sand: pause", "ADD_SAND", "PAUSE"),
        ("Add sand: cancel", "ADD_SAND", "CANCEL"),
    ],
)
async def test_c07_clean_action_variants(
    mock_coordinator, sample_c07_data, label, behavior, action
) -> None:
    """Use the existing action select shape for pause and cancel."""
    device = C07Device(sample_c07_data, mock_coordinator)
    mock_coordinator.account.request = AsyncMock(return_value={"returnCode": 0})
    device.update_device_detail = AsyncMock(return_value={})

    assert await device.select_action(label) is True
    expected_payload = {
        "deviceId": "c07-device-id",
        "behavior": behavior,
        "action": action,
    }
    if behavior == "ADD_SAND" and action == "RUN":
        expected_payload["copies"] = "1"
    mock_coordinator.account.request.assert_awaited_once_with(
        "token/cameraLitterbox/actionCmd/v2",
        expected_payload,
        "POST",
    )


@pytest.mark.asyncio
async def test_c07_action_error_is_reported(mock_coordinator, sample_c07_data) -> None:
    """Expose API action failures through the existing action-error path."""
    device = C07Device(sample_c07_data, mock_coordinator)
    mock_coordinator.account.request = AsyncMock(
        return_value={"returnCode": 4001, "msg": "not allowed"}
    )

    assert await device.select_action("Clean: start") is False
    assert device.error == "not allowed (returnCode: 4001)"


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
