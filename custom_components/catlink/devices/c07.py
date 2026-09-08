"""VISUAL_C07 device support for CatLink."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..const import _LOGGER
from ..helpers import format_api_error
from ..models.additional_cfg import AdditionalDeviceConfig
from .litter_device import LitterDevice

if TYPE_CHECKING:
    from ..modules.devices_coordinator import DevicesCoordinator


API_C07_INFO = "token/cameraLitterbox/info"
API_C07_CAMERA_SWITCH = "token/cameraLitterbox/cameraSwitch"
API_C07_ACTION_COMMAND_V2 = "token/litterbox/actionCmd/v2"
API_C07_BOX_FULL_SENSITIVITY = "token/litterbox/boxfullSensitivity"

_GARBAGE_FULL_ERRORS = {
    "GARBAGE_FULL_ABNORMAL",
    "GARBAGE_TOBE_FULL_ABNORMAL",
}

_FINAL_STATUS_LABELS = {
    "CLEAN_RUN": "Cleaning",
    "CLEAN_PAUSE": "Cleaning paused",
    "CLEAN_CANCEL": "Idle",
    "PAVE_RUN": "Paving",
    "PAVE_PAUSE": "Paving paused",
    "PAVE_CANCEL": "Idle",
}
_GARBAGE_STATUS_LABELS = {
    "00": "Normal",
    "02": "Movement Started",
    "03": "Moving",
}
_CAMERA_SWITCH_LABELS = {
    "00": "Off",
    "01": "Second camera",
    "10": "Main camera",
    "11": "Both cameras",
}


class C07Device(LitterDevice):
    """CatLink 大白 Pro / VISUAL_C07 device."""

    def __init__(
        self,
        dat: dict,
        coordinator: "DevicesCoordinator",
        additional_config: AdditionalDeviceConfig | None = None,
    ) -> None:
        """Initialize the C07 device."""
        super().__init__(dat, coordinator, additional_config)
        self._last_action: str | None = None

    async def async_init(self) -> None:
        """Initialize C07 without the unsupported generic log coordinator."""
        await self.update_device_detail()

    @property
    def actions(self) -> dict[str, str]:
        """Return the supported C07 cleaning actions."""
        return {
            "CLEAN:RUN": "Clean: start",
            "CLEAN:PAUSE": "Clean: pause",
            "CLEAN:CANCEL": "Clean: cancel",
        }

    @property
    def action(self) -> str | None:
        """Return the last requested action."""
        return self._last_action

    @property
    def state(self) -> str:
        """Return the APK-aligned C07 state with existing fallback mapping."""
        final_status = str(self.detail.get("finalStatus") or "")
        return _FINAL_STATUS_LABELS.get(final_status, super().state)

    @property
    def total_clean_time(self) -> int:
        """Return the C07 total clean count."""
        try:
            return int(self.detail.get("totalCleanTimes", 0))
        except (TypeError, ValueError):
            return 0

    @property
    def box_full_levels(self) -> dict[str, str]:
        """Return the C07 box-full sensitivity levels."""
        return {
            "1": "Level 1",
            "2": "Level 2",
        }

    @property
    def error(self) -> str:
        """Return the current C07 error."""
        if self._action_error:
            return self._action_error
        if self.detail.get("currentMessage"):
            return self.detail["currentMessage"]
        if self.detail.get("currentErrorMessage"):
            return self.detail["currentErrorMessage"]
        if self.detail.get("deviceErrorList"):
            return "Device error"
        return "Normal Operation"

    @property
    def garbage_status(self) -> str:
        """Return the readable garbage-bin status."""
        raw = str(self.detail.get("garbageStatus") or "")
        return _GARBAGE_STATUS_LABELS.get(raw, "Unknown")

    @property
    def clean_status(self) -> str:
        """Return the readable cleaning status."""
        final_status = str(self.detail.get("finalStatus") or "")
        if final_status in _FINAL_STATUS_LABELS:
            return _FINAL_STATUS_LABELS[final_status]
        raw = str(self.detail.get("cleanStatus") or "")
        return "Idle" if raw == "00" else raw or "Unknown"

    @property
    def camera_switch(self) -> str:
        """Return the readable camera-channel state."""
        raw = str(self.detail.get("cameraSwitch") or "")
        return _CAMERA_SWITCH_LABELS.get(raw, raw or "Unknown")

    @property
    def camera_switch_control(self) -> str:
        """Return the current value of the camera switch select."""
        return self.camera_switch

    @property
    def garbage_full(self) -> bool:
        """Return whether the API reports a full garbage bin."""
        errors = self.detail.get("deviceErrorList") or []
        return any(
            isinstance(error, dict)
            and str(error.get("errkey", "")).upper() in _GARBAGE_FULL_ERRORS
            for error in errors
        )

    @property
    def hass_sensor(self) -> dict:
        """Return C07 sensors."""
        return {
            "state": {
                "icon": "mdi:information",
                "state_attrs": self.state_attrs,
            },
            "error": {
                "icon": "mdi:alert-circle",
                "state_attrs": self.error_attrs,
            },
            "online": {"icon": "mdi:wifi"},
            "garbage_status": {"icon": "mdi:delete"},
            "clean_status": {"icon": "mdi:broom"},
            "camera_switch": {"icon": "mdi:camera"},
            "litter_remaining_days": {"icon": "mdi:calendar"},
            "deodorant_countdown": {"icon": "mdi:timer"},
            "total_clean_time": {"icon": "mdi:history", "unit": "times"},
        }

    @property
    def hass_binary_sensor(self) -> dict:
        """Return C07 binary sensors."""
        return {
            "garbage_full": {"icon": "mdi:delete-alert"},
        }

    @property
    def hass_select(self) -> dict:
        """Return C07 selects using the integration's existing pattern."""
        return {
            "action": {
                "icon": "mdi:play-box",
                "options": list(self.actions.values()),
                "async_select": self.select_action,
                "delay_update": 5,
            },
            "box_full_sensitivity": {
                "icon": "mdi:tune",
                "options": list(self.box_full_levels.values()),
                "state_attrs": self.box_full_sensitivity_attrs,
                "async_select": self.select_box_full_sensitivity,
            },
            "camera_switch_control": {
                "icon": "mdi:camera-switch",
                "options": list(_CAMERA_SWITCH_LABELS.values()),
                "state_attrs": self.camera_switch_attrs,
                "async_select": self.select_camera_switch,
            },
        }

    def state_attrs(self) -> dict:
        """Return C07 state attributes."""
        return {
            **self._base_state_attrs(),
            "total_clean_times": self.total_clean_time,
            "run_status": self.detail.get("runStatus"),
            "final_status": self.detail.get("finalStatus"),
            "clean_status": self.clean_status,
            "garbage_status": self.garbage_status,
            "raw_clean_status": self.detail.get("cleanStatus"),
            "raw_garbage_status": self.detail.get("garbageStatus"),
            "raw_camera_switch": self.detail.get("cameraSwitch"),
            "device_error_list": self.detail.get("deviceErrorList"),
            "device_warn": self.detail.get("deviceWarn"),
            "box_full_sensitivity": self.detail.get("boxFullSensitivity"),
            "full_times": self.detail.get("fullTimes"),
            "camera_switch": self.camera_switch,
            "dn": self.detail.get("dn"),
        }

    def error_attrs(self) -> dict:
        """Return C07 error attributes."""
        return {
            "errors": self.detail.get("deviceErrorList") or [],
            "warning": self.detail.get("deviceWarn"),
        }

    @property
    def box_full_sensitivity(self) -> str | None:
        """Return the readable box-full sensitivity level."""
        raw = self.detail.get("boxFullSensitivity")
        if raw is None:
            return None
        return self.box_full_levels.get(str(raw))

    def box_full_sensitivity_attrs(self) -> dict:
        """Return the raw box-full sensitivity value."""
        return {"raw_level": self.detail.get("boxFullSensitivity")}

    def camera_switch_attrs(self) -> dict:
        """Return the raw camera-switch value."""
        return {"raw_camera_switch": self.detail.get("cameraSwitch")}

    async def update_device_detail(self) -> dict:
        """Update C07 detail from the camera-specific endpoint."""
        response: dict[str, Any] | None = None
        try:
            response = await self.account.request(
                API_C07_INFO,
                {"deviceId": self.id},
            )
            data = response.get("data", {})
            detail = data.get("deviceInfo", {})
            rdt = detail if isinstance(detail, dict) else {}
        except (TypeError, ValueError) as exc:
            rdt = {}
            _LOGGER.error("Got C07 device detail for %s failed: %s", self.name, exc)

        if not rdt:
            _LOGGER.warning(
                "Got C07 device detail for %s failed: %s", self.name, response
            )
        self.detail = rdt
        self._action_error = None
        self._handle_listeners()
        return rdt

    async def select_action(self, action, **kwargs) -> bool:
        """Select a C07 cleaning action."""
        action_code = next(
            (code for code, label in self.actions.items() if label == action), None
        )
        if action_code is None:
            _LOGGER.warning("Select C07 action failed for %s", action)
            return False
        behavior, command = action_code.split(":", 1)
        response = await self.account.request(
            API_C07_ACTION_COMMAND_V2,
            {
                "deviceId": self.id,
                "behavior": behavior,
                "action": command,
            },
            "POST",
        )
        if response.get("returnCode", 0):
            error = format_api_error(response)
            _LOGGER.error("Select C07 action failed: %s", error)
            self._set_action_error(error)
            return False
        await self.update_device_detail()
        self._last_action = action
        _LOGGER.info("Selected C07 action %s for %s", action, self.id)
        return True

    async def select_box_full_sensitivity(self, level, **kwargs) -> bool:
        """Select the C07 box-full sensitivity level."""
        level_code = next(
            (code for code, label in self.box_full_levels.items() if label == level),
            None,
        )
        if level_code is None:
            _LOGGER.warning("Select C07 box-full sensitivity failed for %s", level)
            return False
        response = await self.account.request(
            API_C07_BOX_FULL_SENSITIVITY,
            {"deviceId": self.id, "level": level_code},
            "POST",
        )
        if response.get("returnCode", 0):
            error = format_api_error(response)
            _LOGGER.error("Select C07 box-full sensitivity failed: %s", error)
            self._set_action_error(error)
            return False
        await self.update_device_detail()
        return True

    async def select_camera_switch(self, value, **kwargs) -> bool:
        """Select which C07 camera channels are enabled."""
        camera_switch = next(
            (code for code, label in _CAMERA_SWITCH_LABELS.items() if label == value),
            None,
        )
        if camera_switch is None:
            _LOGGER.warning("Select C07 camera switch failed for %s", value)
            return False
        response = await self.account.request(
            API_C07_CAMERA_SWITCH,
            {"deviceId": self.id, "cameraSwitch": camera_switch},
            "POST",
        )
        if not response or response.get("returnCode", 0):
            error = format_api_error(response) if response else "Request failed"
            _LOGGER.error("Select C07 camera switch failed: %s", error)
            self._set_action_error(error)
            return False
        await self.update_device_detail()
        return True
