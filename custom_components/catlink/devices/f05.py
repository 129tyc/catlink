"""CATLINK 饭兜 / VISUAL_F05 feeder support."""

import asyncio
from datetime import timedelta
from functools import partial

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from ..const import _LOGGER
from ..helpers import format_api_error
from ..models.f05_events import apply_images, images_visible, normalize_records
from .base import Device


_REFILL_INTERVALS = {str(value): f"{value} min" for value in (10, 30, 60, 120, 240, 360)}
_NUMBER_SETTINGS = {
    "refill_portions": ("refillSetting", "Refill portions", 5),
    "daily_refill_limit": ("dailyRefillSetting", "Daily refill count limit", 200),
}


class F05Device(Device):
    """Expose F05 feedback and commands through its cameraFeeder API."""

    def __init__(self, dat, coordinator, additional_config=None) -> None:
        super().__init__(dat, coordinator, additional_config)
        self._portions = 1
        self._interval_lock = asyncio.Lock()
        self.event_coordinator: DataUpdateCoordinator | None = None
        self.event_data = {"records": [], "last_event": None, "total": 0}

    async def async_init(self) -> None:
        await super().async_init()
        if self.event_coordinator is None:
            self.event_coordinator = DataUpdateCoordinator(
                self.account.hass, _LOGGER, name=f"catlink-{self.id}-events",
                config_entry=self.coordinator.config_entry,
                update_method=self.update_events, update_interval=timedelta(minutes=1),
            )
            await self.event_coordinator.async_refresh()

    @property
    def portions(self) -> int:
        """Return the portions selected for the next manual feed."""
        return self._portions

    @portions.setter
    def portions(self, value: int) -> None:
        self._portions = int(value)
        self._handle_listeners()

    @property
    def online(self) -> bool | None:
        return self.detail.get("online")

    @property
    def food_remaining(self) -> str | None:
        """Return the device's description; F05 does not always report grams."""
        return self.detail.get("totalBalanceDesc")

    @property
    def food_out_portions(self) -> int | None:
        value = self.detail.get("foodoutCopies")
        return int(value) if value is not None else None

    @property
    def error(self) -> str | None:
        if self._action_error:
            return self._action_error
        if message := self.detail.get("currentErrorMessage"):
            return message
        errors = self.detail.get("deviceErrorList")
        if errors:
            return "Device error"
        if errors == []:
            return "Normal Operation"
        return None

    @property
    def camera(self) -> bool | None:
        return self.detail.get("cameraSwitch")

    @property
    def microphone(self) -> bool | None:
        return self.detail.get("micSwitch")

    @property
    def key_lock(self) -> bool | None:
        return self.detail.get("childLock")

    @property
    def auto_refill(self) -> bool | None:
        return self.detail.get("autoSwitch")

    @property
    def timed_feeding(self) -> bool | None:
        return self.detail.get("timerSwitch")

    @property
    def face_feeding(self) -> bool | None:
        return self.detail.get("faceModelSwitch")

    @property
    def food_balance_control(self) -> bool | None:
        return self.detail.get("balanceLimitSwitch")

    @property
    def refill_interval_enabled(self) -> bool | None:
        return self.detail.get("refillDelaySwitch")

    @property
    def refill_portions(self) -> int | None:
        value = self.detail.get("refillCopies")
        return int(value) if value is not None else None

    @property
    def daily_refill_limit(self) -> int | None:
        value = self.detail.get("dailyRefillCopies")
        return int(value) if value is not None else None

    @property
    def refill_interval(self) -> str | None:
        return _REFILL_INTERVALS.get(str(self.detail.get("refillDelay")))

    def state_attrs(self) -> dict:
        """Expose feeding modes without inheriting litter-box attributes."""
        return {
            "work_status": self.detail.get("workStatus"),
            "timed_feeding": self.detail.get("timerSwitch"),
            "face_feeding": self.detail.get("faceModelSwitch"),
        }

    def error_attrs(self) -> dict:
        return {
            "current_error_type": self.detail.get("currentErrorType"),
            "errors": self.detail.get("deviceErrorList"),
        }

    async def update_device_detail(self) -> dict:
        response = await self.account.request(
            "token/cameraFeeder/detail", {"deviceId": self.id}
        )
        if response.get("returnCode") != 0:
            raise UpdateFailed(format_api_error(response))
        detail = (response.get("data") or {}).get("deviceInfo")
        if not detail:
            raise UpdateFailed("Missing F05 device details")
        self.detail = detail
        self._action_error = None
        self._handle_listeners()
        return detail

    async def _command(self, endpoint: str, params: dict) -> bool:
        response = await self.account.request(
            f"token/cameraFeeder/{endpoint}",
            {"deviceId": self.id, **params},
            "POST",
        )
        if response.get("returnCode") != 0:
            message = format_api_error(response)
            self._set_action_error(message)
            raise HomeAssistantError(message)
        await self.update_device_detail()
        return True

    async def food_out(self) -> bool:
        return await self._command("foodOut", {"foodOutNum": self.portions})

    async def _set_switch(self, endpoint: str, parameter: str, on: bool, **kwargs) -> bool:
        # The App sends 1/0 for cameraSwitch and true/false for switchFlag.
        value = str(int(on)) if parameter == "cameraSwitch" else str(on).lower()
        return await self._command(endpoint, {parameter: value})

    async def async_set_number(self, name: str, value: float) -> bool:
        endpoint, _, maximum = _NUMBER_SETTINGS[name]
        if not 1 <= value <= maximum or int(value) != value:
            raise HomeAssistantError(f"Value must be a whole number from 1 to {maximum}")
        return await self._command(endpoint, {"copies": str(int(value))})

    async def async_set_refill_interval(
        self, option: str | None = None, *, enabled: bool | None = None, **kwargs
    ) -> bool:
        if option is not None and option not in _REFILL_INTERVALS.values():
            raise HomeAssistantError("Unsupported refill interval")
        async with self._interval_lock:
            await self.update_device_detail()
            interval = self.detail.get("refillDelay")
            current_enabled = self.refill_interval_enabled
            if interval is None or current_enabled is None:
                raise HomeAssistantError("Unable to read refill interval settings")
            if option is not None:
                interval = next(k for k, v in _REFILL_INTERVALS.items() if v == option)
            return await self._command("foodoutTimeInterval", {
                "timeInterval": str(interval),
                "switchFlag": str(current_enabled if enabled is None else enabled).lower(),
            })

    async def update_events(self) -> dict:
        timezone = dt_util.get_time_zone(self.account.hass.config.time_zone)
        date = dt_util.now(timezone).date().isoformat()
        response = await self.account.request("token/device/feederpro/stats/timeline", {
            "deviceId": self.id, "date": date, "type": 0, "pageNumber": 1, "pageSize": 10,
        })
        if response.get("returnCode") != 0:
            raise UpdateFailed("Unable to fetch F05 events")
        logs = (response.get("data") or {}).get("feederLogs")
        if not isinstance(logs, dict) or not isinstance(logs.get("rows"), list):
            raise UpdateFailed("Missing F05 event records")
        records = normalize_records(logs["rows"])
        for record in records:
            record["event_date"] = date
        picture_ids = list(dict.fromkeys(
            record[f"image_{slot}_id"]
            for record in records if images_visible(record)
            for slot in range(3) if record.get(f"image_{slot}_id")
        ))
        if picture_ids:
            pictures = await self.account.request(
                "token/media/ezviz/list/pics", {"picIds": ",".join(picture_ids)}
            )
            if pictures.get("returnCode") == 0 and isinstance(pictures.get("data"), list):
                apply_images(records, pictures["data"])
        self.event_data = {
            "records": records, "last_event": records[0] if records else None,
            "total": logs.get("total", len(records)),
        }
        return self.event_data

    @property
    def last_event(self) -> str:
        return (self.event_data.get("last_event") or {}).get("event") or "unknown"

    def last_event_attrs(self) -> dict:
        record = self.event_data.get("last_event") or {}
        return {k: v for k, v in record.items() if k not in {"image_0", "image_1", "image_2"}}

    def event_image_url(self, name: str) -> str | None:
        record = self.event_data.get("last_event") or {}
        return record.get(name.removeprefix("last_event_")) if images_visible(record) else None

    def event_image_attrs(self, slot: int) -> dict:
        record = self.event_data.get("last_event") or {}
        return {"event_id": record.get("event_id"), "event_type": record.get("type"),
                "media_display_flag": record.get("media_display_flag"), "source_field": f"picId{slot}"}

    @property
    def hass_image(self) -> dict:
        return {
            f"last_event_image_{slot}": {
                "name": f"Last event image {slot + 1}", "coordinator_attr": "event_coordinator",
                "state_attrs": partial(self.event_image_attrs, slot),
            }
            for slot in range(3)
        }

    @property
    def hass_sensor(self) -> dict:
        return {
            "state": {"icon": "mdi:information", "state_attrs": self.state_attrs},
            "food_remaining": {"name": "Food remaining", "icon": "mdi:food"},
            "food_out_portions": {"name": "Food out portions", "icon": "mdi:counter"},
            "error": {"icon": "mdi:alert-circle", "state_attrs": self.error_attrs},
            "last_event": {"icon": "mdi:history", "coordinator_attr": "event_coordinator",
                           "state_attrs": self.last_event_attrs},
        }

    @property
    def hass_binary_sensor(self) -> dict:
        return {"online": {"class": BinarySensorDeviceClass.CONNECTIVITY}}

    @property
    def hass_button(self) -> dict:
        return {"feed": {"icon": "mdi:food", "async_press": self.food_out}}

    @property
    def hass_number(self) -> dict:
        return {
            "portions": {
                "name": "Portions", "icon": "mdi:counter", "min": 1, "max": 5, "step": 1
            },
            **{name: {"name": label, "icon": "mdi:counter", "min": 1, "max": maximum,
                      "step": 1, "async_set": partial(self.async_set_number, name)}
               for name, (_, label, maximum) in _NUMBER_SETTINGS.items()},
        }

    @property
    def hass_switch(self) -> dict:
        switches = {
            name: {
                "name": label,
                "icon": icon,
                "optimistic": False,
                "async_turn_on": partial(self._set_switch, endpoint, parameter, True),
                "async_turn_off": partial(self._set_switch, endpoint, parameter, False),
            }
            for name, label, icon, endpoint, parameter in (
                ("camera", "Camera", "mdi:camera", "cameraSwitch", "cameraSwitch"),
                ("microphone", "Microphone", "mdi:microphone", "micSwitch", "switchFlag"),
                ("key_lock", "Child lock", "mdi:lock", "keyLock/setting", "switchFlag"),
                ("auto_refill", "Auto refill", "mdi:autorenew", "autoSwitch", "switchFlag"),
                ("timed_feeding", "Timed feeding", "mdi:calendar-clock", "timerSwitch", "switchFlag"),
                ("face_feeding", "Face feeding", "mdi:cat", "faceModeSwitch", "switchFlag"),
                ("food_balance_control", "Remaining food control", "mdi:food", "balanceLimitSwitch", "enable"),
            )
        }
        switches["refill_interval_enabled"] = {
            "name": "Refill interval", "icon": "mdi:timer", "optimistic": False,
            "async_turn_on": partial(self.async_set_refill_interval, enabled=True),
            "async_turn_off": partial(self.async_set_refill_interval, enabled=False),
        }
        return switches

    @property
    def hass_select(self) -> dict:
        return {"refill_interval": {
            "name": "Refill interval", "icon": "mdi:timer",
            "options": list(_REFILL_INTERVALS.values()), "async_select": self.async_set_refill_interval,
        }}
