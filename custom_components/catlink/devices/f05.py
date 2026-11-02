"""CATLINK 饭兜 / VISUAL_F05 feeder support."""

from functools import partial

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed

from ..helpers import format_api_error
from .base import Device


class F05Device(Device):
    """Expose F05 feedback and commands through its cameraFeeder API."""

    def __init__(self, dat, coordinator, additional_config=None) -> None:
        super().__init__(dat, coordinator, additional_config)
        self._portions = 1

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
        return self._action_error or self.detail.get("currentErrorMessage")

    @property
    def camera(self) -> bool | None:
        return self.detail.get("cameraSwitch")

    @property
    def microphone(self) -> bool | None:
        return self.detail.get("micSwitch")

    @property
    def child_lock(self) -> bool | None:
        return self.detail.get("childLock")

    @property
    def auto_refill(self) -> bool | None:
        return self.detail.get("autoSwitch")

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
            "device_errors": self.detail.get("deviceErrorList"),
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

    @property
    def hass_sensor(self) -> dict:
        return {
            "state": {"icon": "mdi:information", "state_attrs": self.state_attrs},
            "food_remaining": {"name": "Food remaining", "icon": "mdi:food"},
            "food_out_portions": {"name": "Food out portions", "icon": "mdi:counter"},
            "error": {"icon": "mdi:alert-circle", "state_attrs": self.error_attrs},
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
            }
        }

    @property
    def hass_switch(self) -> dict:
        return {
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
                ("child_lock", "Child lock", "mdi:lock", "keyLock/setting", "switchFlag"),
                ("auto_refill", "Auto refill", "mdi:autorenew", "autoSwitch", "switchFlag"),
            )
        }

    @property
    def hass_select(self) -> dict:
        """Feeding is a one-shot command, not a persistent selection."""
        return {}
