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
    assert device.camera_switch == "Both cameras"
    assert device.garbage_status == "Normal"
    assert device.clean_status == "Idle"
    assert device.total_clean_time == 5
    assert device.state_attrs()["total_clean_times"] == 5
    assert device.state_attrs()["raw_camera_switch"] == "11"
    assert "garbage_status" in device.hass_sensor
    assert "box_full_sensitivity" not in device.hass_sensor
    assert "action" in device.hass_select
    assert "box_full_sensitivity" in device.hass_select

    device.detail["deviceErrorList"] = [{"errkey": "GARBAGE_FULL_ABNORMAL"}]
    assert device.garbage_full is True
    device.detail["garbageStatus"] = "99"
    assert device.garbage_status == "Unknown"
    device.detail["garbageStatus"] = "02"
    assert device.garbage_status == "Movement Started"
    device.detail["garbageStatus"] = "03"
    assert device.garbage_status == "Moving"


@pytest.mark.parametrize(
    ("final_status", "expected"),
    [
        ("CLEAN_RUN", "Cleaning"),
        ("CLEAN_PAUSE", "Cleaning paused"),
        ("CLEAN_CANCEL", "Idle"),
        ("PAVE_RUN", "Paving"),
        ("PAVE_PAUSE", "Paving paused"),
        ("PAVE_CANCEL", "Idle"),
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
        "token/litterbox/actionCmd/v2",
        {"deviceId": "c07-device-id", "behavior": "CLEAN", "action": "RUN"},
        "POST",
    )
    device.update_device_detail.assert_awaited_once_with()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("label", "behavior", "action"),
    [
        ("Clean: pause", "CLEAN", "PAUSE"),
        ("Clean: cancel", "CLEAN", "CANCEL"),
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
    mock_coordinator.account.request.assert_awaited_once_with(
        "token/litterbox/actionCmd/v2",
        {"deviceId": "c07-device-id", "behavior": behavior, "action": action},
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
        "token/litterbox/boxfullSensitivity",
        {"deviceId": "c07-device-id", "level": "2"},
        "POST",
    )
