"""F05 contract tests with synthetic device data only."""

import logging
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.setup import async_setup_component

from custom_components.catlink.const import SUPPORTED_DEVICE_TYPES
from custom_components.catlink.devices.f05 import F05Device
from custom_components.catlink.devices.registry import create_device
from custom_components.catlink.entities.binary import CatlinkBinarySensorEntity
from custom_components.catlink.entities.button import CatlinkButtonEntity
from custom_components.catlink.entities.number import CatlinkNumberEntity
from custom_components.catlink.entities.sensor import CatlinkSensorEntity
from custom_components.catlink.entities.switch import CatlinkSwitchEntity


@pytest.fixture
def feedback():
    return {
        "workStatus": "00", "online": True, "totalBalanceDesc": "Sufficient",
        "totalBalance": None, "foodoutCopies": "3", "cameraSwitch": True,
        "micSwitch": True, "childLock": False, "autoSwitch": True,
        "timerSwitch": False, "faceModelSwitch": False,
        "currentErrorMessage": None, "deviceErrorList": [],
    }


@pytest.fixture
def device(hass, feedback):
    coordinator = MagicMock()
    coordinator.hass = hass
    coordinator.config_entry = None
    coordinator.account.hass = hass
    coordinator.account.request = AsyncMock(
        return_value={"returnCode": 0, "data": {"deviceInfo": feedback}}
    )

    async def request(api, *args):
        if api == "token/device/feederpro/stats/timeline":
            return {"returnCode": 0, "data": {"feederLogs": {"total": "0", "rows": []}}}
        return coordinator.account.request.return_value

    coordinator.account.request.side_effect = request
    return create_device({
        "id": "f05-test", "mac": "AA:BB:CC:DD:EE:05", "model": "00",
        "deviceName": "Test feeder", "deviceType": "VISUAL_F05",
    }, coordinator)


async def test_f05_discovery_and_feedback(device):
    assert isinstance(device, F05Device)
    assert "VISUAL_F05" in SUPPORTED_DEVICE_TYPES
    await device.async_init()
    device.account.request.assert_any_await(
        "token/cameraFeeder/detail", {"deviceId": "f05-test"}
    )
    assert device.state == "idle"
    assert device.online is True
    assert device.food_remaining == "Sufficient"
    assert device.food_out_portions == 3
    assert device.camera is True
    assert device.key_lock is False
    assert set(device.hass_select) == {"refill_interval"}
    assert "weight" not in device.hass_sensor
    assert "last_log" not in device.hass_sensor
    assert "temperature" not in device.state_attrs()


@pytest.mark.parametrize("response", [
    {"returnCode": 1002, "msg": "Session expired"},
    {"returnCode": 0, "data": None},
    {},
])
async def test_detail_failure_preserves_last_feedback(device, response):
    await device.async_init()
    previous = device.detail
    device.account.request.return_value = response
    with pytest.raises(UpdateFailed):
        await device.update_device_detail()
    assert device.detail is previous


async def test_missing_feedback_stays_unknown(device):
    assert device.camera is None
    assert device.microphone is None
    assert device.online is None
    assert device.food_remaining is None
    assert device.food_out_portions is None
    assert device.error is None


@pytest.mark.parametrize(("detail", "expected"), [
    ({"deviceErrorList": [], "currentErrorMessage": None}, "Normal Operation"),
    ({"deviceErrorList": [], "currentErrorMessage": ""}, "Normal Operation"),
    ({"deviceErrorList": [], "currentErrorMessage": "Food jammed"}, "Food jammed"),
    ({"deviceErrorList": [{"errkey": "FOOD_JAM"}]}, "Device error"),
    ({"deviceErrorList": [{"errkey": "FOOD_JAM"}], "currentErrorMessage": "Food jammed"}, "Food jammed"),
    ({"workStatus": "00"}, None),
    ({"deviceErrorList": None}, None),
])
def test_error_state_requires_explicit_feedback(device, detail, expected):
    """Distinguish confirmed normal feedback, an active error and missing data."""
    device.detail = detail
    assert device.error == expected


async def test_action_error_takes_precedence_until_successful_refresh(device):
    await device.async_init()
    device._set_action_error("Command rejected")
    assert device.error == "Command rejected"
    await device.update_device_detail()
    assert device.error == "Normal Operation"


async def test_manual_feed_uses_selected_portions_and_f05_contract(device):
    device.portions = 4
    await device.hass_button["feed"]["async_press"]()
    assert device.account.request.await_args_list == [
        call("token/cameraFeeder/foodOut", {"deviceId": "f05-test", "foodOutNum": 4}, "POST"),
        call("token/cameraFeeder/detail", {"deviceId": "f05-test"}),
    ]
    assert device.hass_number["portions"]["max"] == 5


@pytest.mark.parametrize("response", [{"returnCode": 42, "msg": "Feeder busy"}, {}])
async def test_failed_feed_is_reported_without_retry(device, response):
    device.account.request.return_value = response
    with pytest.raises(HomeAssistantError):
        await device.food_out()
    assert device.error
    assert device.account.request.await_count == 1


@pytest.mark.parametrize(("name", "endpoint", "parameter"), [
    ("camera", "cameraSwitch", "cameraSwitch"),
    ("microphone", "micSwitch", "switchFlag"),
    ("key_lock", "keyLock/setting", "switchFlag"),
    ("auto_refill", "autoSwitch", "switchFlag"),
    ("timed_feeding", "timerSwitch", "switchFlag"),
    ("face_feeding", "faceModeSwitch", "switchFlag"),
    ("food_balance_control", "balanceLimitSwitch", "enable"),
])
@pytest.mark.parametrize("on", [True, False])
async def test_switch_contract_and_feedback(device, name, endpoint, parameter, on):
    await device.async_init()
    previous = getattr(device, name)
    device.account.request.reset_mock()
    action = "async_turn_on" if on else "async_turn_off"
    await device.hass_switch[name][action](entity=MagicMock())
    expected = str(int(on)) if name == "camera" else str(on).lower()
    device.account.request.assert_any_await(
        f"token/cameraFeeder/{endpoint}", {"deviceId": "f05-test", parameter: expected}, "POST"
    )
    assert getattr(device, name) == previous
    assert device.hass_switch[name]["optimistic"] is False


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_f05_entities_and_number_service(hass, device):
    """Exercise the real HA number and switch paths, including fresh feedback."""
    await device.async_init()
    coordinator = DataUpdateCoordinator(hass, logging.getLogger(__name__), name="f05-test", config_entry=None)
    coordinator.account = device.account
    coordinator.async_set_updated_data({})
    device.coordinator = coordinator
    classes = {
        "sensor": CatlinkSensorEntity, "binary_sensor": CatlinkBinarySensorEntity,
        "button": CatlinkButtonEntity, "number": CatlinkNumberEntity,
        "switch": CatlinkSwitchEntity,
    }
    entities = {}
    for domain, cls in classes.items():
        await async_setup_component(hass, domain, {})
        created = [cls(name, device, options) for name, options in getattr(device, f"hass_{domain}").items()]
        await hass.data[domain].async_add_entities(created)
        entities.update({(domain, entity._name): entity for entity in created})
    await hass.async_block_till_done()

    online = entities["binary_sensor", "online"]
    assert online.device_class == "connectivity"
    assert hass.states.get(online.entity_id).state == "on"
    assert hass.states.get(entities["switch", "key_lock"].entity_id).state == "off"
    assert ("switch", "child_lock") not in entities
    error = hass.states.get(entities["sensor", "error"].entity_id)
    assert error.state == "Normal Operation"
    assert error.attributes["errors"] == []
    assert "device_errors" not in error.attributes

    number = entities["number", "portions"]
    assert hass.states.get(number.entity_id).state == "1"
    await hass.services.async_call("number", "set_value", {"entity_id": number.entity_id, "value": 2}, blocking=True)
    assert hass.states.get(number.entity_id).state == "2"
    await hass.services.async_call("button", "press", {"entity_id": entities["button", "feed"].entity_id}, blocking=True)
    device.account.request.assert_any_await("token/cameraFeeder/foodOut", {"deviceId": "f05-test", "foodOutNum": 2}, "POST")

    camera = entities["switch", "camera"]
    await hass.services.async_call("switch", "turn_off", {"entity_id": camera.entity_id}, blocking=True)
    assert hass.states.get(camera.entity_id).state == "on"
    device.account.request.return_value = {"returnCode": 0, "data": {"deviceInfo": {"cameraSwitch": False}}}
    await device.update_device_detail()
    assert hass.states.get(camera.entity_id).state == "off"


@pytest.mark.parametrize(("name", "endpoint", "value", "field"), [
    ("refill_portions", "refillSetting", 5, "refillCopies"),
    ("daily_refill_limit", "dailyRefillSetting", 20, "dailyRefillCopies"),
])
async def test_persistent_numbers_use_api_and_feedback(device, feedback, name, endpoint, value, field):
    feedback[field] = 3
    await device.hass_number[name]["async_set"](value)
    device.account.request.assert_any_await(
        f"token/cameraFeeder/{endpoint}", {"deviceId": "f05-test", "copies": str(value)}, "POST"
    )
    assert getattr(device, name) == 3


@pytest.mark.parametrize(("name", "value"), [
    ("refill_portions", 0), ("refill_portions", 6), ("refill_portions", 2.5),
    ("daily_refill_limit", 201),
])
async def test_number_bounds_match_app(device, name, value):
    with pytest.raises(HomeAssistantError):
        await device.async_set_number(name, value)
    device.account.request.assert_not_awaited()


async def test_interval_updates_preserve_other_setting_under_concurrency(device):
    import asyncio
    backend = {"refillDelay": 30, "refillDelaySwitch": False}

    async def request(api, params, method="GET"):
        if method == "GET":
            snapshot = dict(backend)
            await asyncio.sleep(0)
            return {"returnCode": 0, "data": {"deviceInfo": snapshot}}
        assert api == "token/cameraFeeder/foodoutTimeInterval"
        backend.update(refillDelay=int(params["timeInterval"]), refillDelaySwitch=params["switchFlag"] == "true")
        return {"returnCode": 0}

    device.account.request.side_effect = request
    await asyncio.gather(
        device.async_set_refill_interval("120 min"),
        device.async_set_refill_interval(enabled=True),
    )
    assert backend == {"refillDelay": 120, "refillDelaySwitch": True}
    assert device.refill_interval == "120 min"


async def test_interval_refuses_unknown_companion_feedback(device):
    with pytest.raises(HomeAssistantError, match="Unable to read"):
        await device.async_set_refill_interval("60 min")
    assert all(c.args[0] == "token/cameraFeeder/detail" for c in device.account.request.await_args_list)


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_config_numbers_and_interval_through_ha(hass, device, feedback):
    from custom_components.catlink.entities.select import CatlinkSelectEntity
    feedback.update(refillCopies=3, dailyRefillCopies=20, refillDelay=30, refillDelaySwitch=False)
    await device.async_init()
    coordinator = DataUpdateCoordinator(hass, logging.getLogger(__name__), name="f05-config", config_entry=None)
    coordinator.account = device.account
    coordinator.async_set_updated_data({})
    device.coordinator = coordinator
    number = CatlinkNumberEntity("refill_portions", device, device.hass_number["refill_portions"])
    select = CatlinkSelectEntity("refill_interval", device, device.hass_select["refill_interval"])
    await async_setup_component(hass, "number", {})
    await async_setup_component(hass, "select", {})
    await hass.data["number"].async_add_entities([number])
    await hass.data["select"].async_add_entities([select])
    await hass.async_block_till_done()
    assert hass.states.get(number.entity_id).state == "3"
    assert hass.states.get(select.entity_id).state == "30 min"
    await hass.services.async_call("number", "set_value", {"entity_id": number.entity_id, "value": 5}, blocking=True)
    assert hass.states.get(number.entity_id).state == "3"
    await hass.services.async_call("select", "select_option", {"entity_id": select.entity_id, "option": "120 min"}, blocking=True)
    assert hass.states.get(select.entity_id).state == "30 min"
    feedback.update(refillCopies=5, refillDelay=120)
    await device.update_device_detail()
    assert hass.states.get(number.entity_id).state == "5"
    assert hass.states.get(select.entity_id).state == "120 min"
