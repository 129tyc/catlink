"""VISUAL_C07 device support for CatLink."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import PERCENTAGE, UnitOfTemperature

from ..const import _LOGGER
from ..helpers import format_api_error
from ..models.additional_cfg import AdditionalDeviceConfig
from .litter_device import LitterDevice

if TYPE_CHECKING:
    from ..modules.devices_coordinator import DevicesCoordinator


API_C07_INFO = "token/cameraLitterbox/info"
API_C07_CAMERA_SWITCH = "token/cameraLitterbox/cameraSwitch"
API_C07_ACTION_COMMAND_V2 = "token/cameraLitterbox/actionCmd/v2"
API_C07_BOX_FULL_SENSITIVITY = "token/cameraLitterbox/boxfullSensitivity"
API_C07_AUTO_CLEAN = "token/cameraLitterbox/autoClean"
API_C07_KITTY_MODEL_SWITCH = "token/cameraLitterbox/kittyModelSwitch"
API_C07_KEY_LOCK = "token/cameraLitterbox/keyLock"
API_C07_QUIET_MODE = "token/cameraLitterbox/quietMode"
API_C07_CONTINUOUS_CLEANING = "token/cameraLitterbox/continuousCleaning"
API_C07_SOFT_MODEL = "token/cameraLitterbox/deepClean/softModel"
API_C07_SAFE_TIME_SETTING = "token/cameraLitterbox/safeTimeSetting"
API_C07_PAVE_LEVEL = "token/cameraLitterbox/paveLevel"
API_C07_CAT_LITTER_SETTING = "token/cameraLitterbox/catLitterSetting"
API_C07_PANELTONE = "token/cameraLitterbox/paneltone"
API_C07_VOICE_PROMPT_SWITCH = "token/cameraLitterbox/voicePromptSwitch"
API_C07_WATERMARK_SWITCH = "token/cameraLitterbox/watermarkSwitch"
API_C07_FILL_LIGHT_SETTING = "token/cameraLitterbox/fillLightSetting"

_GARBAGE_FULL_ERROR = "GARBAGE_FULL_ABNORMAL"
_GARBAGE_NEARLY_FULL_ERROR = "GARBAGE_TOBE_FULL_ABNORMAL"
_RADAR_PROTECTION_ERRORS = {"RADAR_PROTECTED", "WEIGHT_PROTECTED"}
_DEVICE_ERROR_LABELS = {
    "SANDBOX_NOTENOUGH": "Sandbox not enough",
    "DEVICE_LITTER_NOTENOUGH": "Cat litter not enough",
    _GARBAGE_NEARLY_FULL_ERROR: "Garbage bin almost full",
    _GARBAGE_FULL_ERROR: "Garbage bin full",
    "GARBAGE_BOX_UNINSTALL": "Garbage bin not installed",
    "DEVICE_ANTIPINCH_PROTECTION": "Anti-pinch protection",
    "ENGINE_PROTECTED": "Motor protection",
}

_FINAL_STATUS_LABELS = {
    "CLEAN_RUN": "Cleaning",
    "CLEAN_PAUSE": "Cleaning paused",
    "CLEAN_CANCEL": "Idle",
    "PAVE_RUN": "Paving",
    "PAVE_PAUSE": "Paving paused",
    "PAVE_CANCEL": "Idle",
    "EMPTY_RUN": "Emptying",
    "EMPTY_PAUSE": "Emptying paused",
    "EMPTY_CANCEL": "Idle",
    "ADD_SAND_RUN": "Adding sand",
    "ADD_SAND_PAUSE": "Adding sand paused",
    "ADD_SAND_CANCEL": "Idle",
}
_GARBAGE_STATUS_LABELS = {
    "00": "Low",
    "02": "Medium",
    "01": "Full",
    "03": "Full",
}
_CAMERA_SWITCH_LABELS = {
    "00": "Off",
    "01": "Second camera",
    "10": "Main camera",
    "11": "Both cameras",
}
_BALANCE_LABELS = {1: "Low", 2: "Medium"}
_LITTER_TYPE_LABELS = {
    0: "Clay",
    2: "Mixed",
    3: "Cassava",
}
_PAVE_LEVEL_LABELS = {str(level): f"Level {level}" for level in range(4)}
_SAFE_TIME_LABELS = {
    "1": "1 min",
    "3": "3 min",
    "5": "5 min",
    "7": "7 min",
    "10": "10 min",
    "15": "15 min",
    "30": "30 min",
}
_FILL_LIGHT_LABELS = {
    "2": "Auto",
    "0": "Always open",
    "1": "Closed",
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
        self._add_sand_copies = 1

    async def async_init(self) -> None:
        """Initialize C07 without the unsupported generic log coordinator."""
        await self.update_device_detail()

    @property
    def actions(self) -> dict[str, str]:
        """Return the supported C07 operation actions."""
        return {
            "CLEAN:RUN": "Clean: start",
            "CLEAN:PAUSE": "Clean: pause",
            "CLEAN:CANCEL": "Clean: cancel",
            "PAVE:RUN": "Pave: start",
            "PAVE:PAUSE": "Pave: pause",
            "PAVE:CANCEL": "Pave: cancel",
            "EMPTY:RUN": "Empty: start",
            "EMPTY:PAUSE": "Empty: pause",
            "EMPTY:CANCEL": "Empty: cancel",
            "ADD_SAND:RUN": "Add sand: start",
            "ADD_SAND:PAUSE": "Add sand: pause",
            "ADD_SAND:CANCEL": "Add sand: cancel",
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

    @staticmethod
    def _flag(value: Any) -> bool:
        """Convert the API's mixed boolean representations to bool."""
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        return str(value or "").strip().upper() in {
            "1",
            "01",
            "TRUE",
            "ON",
            "OPEN",
            "OPENED",
            "ENABLED",
            "LOCKED",
            "ALWAYS_OPEN",
        }

    @staticmethod
    def _number(value: Any, integer: bool = False) -> float | int | None:
        """Convert a numeric C07 field without turning missing data into zero."""
        if value is None or value == "":
            return None
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return int(result) if integer else result

    def _error_key_list(self) -> list[str]:
        """Return normalized active C07 error keys in API order."""
        errors = self.detail.get("deviceErrorList") or []
        return [
            str(error.get("errkey", "")).upper()
            for error in errors
            if isinstance(error, dict) and error.get("errkey")
        ]

    def _error_keys(self) -> set[str]:
        """Return normalized active C07 device error keys."""
        return set(self._error_key_list())

    @property
    def litter_weight(self) -> float | None:
        """Return C07 litter weight in kilograms."""
        value = self._number(self.detail.get("catLitterWeight"))
        if value is None:
            return None
        return value - self.empty_litter_box_weight

    @property
    def manual_clean_time(self) -> int:
        """Return the C07 manual clean count."""
        return int(self._number(self.detail.get("manualTimes"), integer=True) or 0)

    @property
    def induction_clean_time(self) -> int:
        """Return the C07 automatic clean count."""
        return int(self._number(self.detail.get("inductionTimes"), integer=True) or 0)

    @property
    def clear_time(self) -> int:
        """Return the C07 clear-operation count."""
        return int(self._number(self.detail.get("clearTimes"), integer=True) or 0)

    @property
    def full_time(self) -> int:
        """Return the C07 full-bin count."""
        return int(self._number(self.detail.get("fullTimes"), integer=True) or 0)

    @property
    def work_mode(self) -> str:
        """Return the raw C07 work mode."""
        return str(self.detail.get("workModel") or "Unknown")

    @property
    def cat_litter_balance(self) -> str:
        """Return the App-aligned cat litter balance label."""
        raw = self._number(self.detail.get("catLitterBalance"), integer=True)
        return _BALANCE_LABELS.get(raw, "Full" if raw is not None else "Unknown")

    @property
    def sandbox_balance(self) -> str:
        """Return the App-aligned sandbox balance label."""
        raw = self._number(self.detail.get("sandboxBalance"), integer=True)
        return _BALANCE_LABELS.get(raw, "Full" if raw is not None else "Unknown")

    @property
    def sandbox_installed(self) -> bool:
        """Return whether the C07 sandbox is installed."""
        return self._flag(self.detail.get("sandBoxInstall"))

    @property
    def empty_state(self) -> bool:
        """Return the C07 empty-state flag."""
        return self._flag(self.detail.get("emptyState"))

    @property
    def empty_status(self) -> str:
        """Return the raw C07 empty status."""
        return str(self.detail.get("emptyStatus") or "Unknown")

    @property
    def temperature(self) -> float | None:
        """Return the C07 temperature."""
        return self._number(self.detail.get("temperature"))

    @property
    def humidity(self) -> float | None:
        """Return the C07 humidity."""
        return self._number(self.detail.get("humidity"))

    @property
    def litter_type(self) -> str:
        """Return the readable C07 litter type."""
        raw = self._number(self.detail.get("litterType"), integer=True)
        return _LITTER_TYPE_LABELS.get(raw, str(raw) if raw is not None else "Unknown")

    @property
    def pave_level(self) -> int | None:
        """Return the C07 paving level."""
        return self._number(self.detail.get("sandPaveLevel"), integer=True)

    @property
    def pave_level_control(self) -> str | None:
        """Return the current paving-level select option."""
        raw = self.pave_level
        return _PAVE_LEVEL_LABELS.get(str(raw)) if raw is not None else None

    @property
    def safe_time(self) -> str:
        """Return the readable C07 safe time."""
        raw = str(self.detail.get("safeTime") or "")
        return _SAFE_TIME_LABELS.get(raw, raw or "Unknown")

    @property
    def safe_time_control(self) -> str | None:
        """Return the current safe-time select option."""
        raw = str(self.detail.get("safeTime") or "")
        return _SAFE_TIME_LABELS.get(raw) or None

    @property
    def litter_type_control(self) -> str | None:
        """Return the current litter-type select option."""
        raw = self._number(self.detail.get("litterType"), integer=True)
        return _LITTER_TYPE_LABELS.get(raw) if raw is not None else None

    @property
    def auto_clean(self) -> bool:
        """Return whether automatic cleaning is enabled."""
        return self._flag(self.detail.get("autoSwitch"))

    @property
    def kitty_model(self) -> bool:
        """Return whether kitten mode is enabled."""
        return self._flag(self.detail.get("kittenModel"))

    @property
    def key_lock(self) -> bool:
        """Return whether the device key lock is enabled."""
        return self._flag(self.detail.get("keyLock"))

    @property
    def quiet_mode(self) -> bool:
        """Return whether quiet mode is enabled."""
        return self._flag(self.detail.get("quietEnable"))

    @property
    def continuous_cleaning(self) -> bool:
        """Return whether continuous cleaning is enabled."""
        return self._flag(self.detail.get("continuousCleaning"))

    @property
    def soft_model(self) -> bool:
        """Return whether the soft/deep-clean mode is enabled."""
        return self._flag(self.detail.get("softModel"))

    @property
    def watermark(self) -> bool:
        """Return whether the camera watermark is enabled."""
        return self._flag(self.detail.get("watermark"))

    @property
    def voice_prompt(self) -> bool:
        """Return whether voice prompts are enabled."""
        return self._flag(self.detail.get("voiceEnable"))

    @property
    def fill_light(self) -> str | None:
        """Return the readable C07 three-state fill-light setting."""
        raw = self.detail.get("fillLight")
        if raw is None or raw == "":
            return None
        return _FILL_LIGHT_LABELS.get(str(raw))

    @property
    def fill_light_control(self) -> str | None:
        """Return the current fill-light select option."""
        return self.fill_light

    @property
    def panel_tone(self) -> bool:
        """Return whether device panel sounds are enabled."""
        return self._flag(self.detail.get("paneltone"))

    @property
    def add_sand_copies(self) -> int:
        """Return the number of sand portions used by the next add-sand action."""
        return self._add_sand_copies

    @add_sand_copies.setter
    def add_sand_copies(self, value: int) -> None:
        """Set the number of sand portions used by the next add-sand action."""
        self._add_sand_copies = min(3, max(1, int(value)))

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
        error_keys = self._error_key_list()
        for key in error_keys:
            if key not in _RADAR_PROTECTION_ERRORS and key in _DEVICE_ERROR_LABELS:
                return _DEVICE_ERROR_LABELS[key]
        for key in error_keys:
            if key not in _RADAR_PROTECTION_ERRORS:
                return "Device error"
        if error_keys:
            return "Normal Operation"
        if self.detail.get("currentMessage"):
            return self.detail["currentMessage"]
        if self.detail.get("currentErrorMessage"):
            return self.detail["currentErrorMessage"]
        return "Normal Operation"

    @property
    def garbage_status(self) -> str:
        """Return the readable garbage-bin status."""
        raw = str(self.detail.get("garbageStatus") or "")
        return _GARBAGE_STATUS_LABELS.get(raw, "Full" if raw else "Unknown")

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
        return _GARBAGE_FULL_ERROR in self._error_keys()

    @property
    def garbage_nearly_full(self) -> bool:
        """Return whether the API reports that the garbage bin is nearly full."""
        return _GARBAGE_NEARLY_FULL_ERROR in self._error_keys()

    @property
    def cat_detected(self) -> bool:
        """Return whether C07 radar/weight protection detects a cat."""
        return bool(self._error_keys() & _RADAR_PROTECTION_ERRORS)

    @property
    def anti_pinch_protected(self) -> bool:
        """Return whether C07 anti-pinch protection is active."""
        return "DEVICE_ANTIPINCH_PROTECTION" in self._error_keys()

    @property
    def engine_protected(self) -> bool:
        """Return whether C07 motor protection is active."""
        return "ENGINE_PROTECTED" in self._error_keys()

    @property
    def garbage_box_missing(self) -> bool:
        """Return whether the garbage box is reported as uninstalled."""
        return "GARBAGE_BOX_UNINSTALL" in self._error_keys()

    @property
    def litter_low(self) -> bool:
        """Return whether the API reports insufficient cat litter."""
        return self._number(self.detail.get("catLitterBalance"), integer=True) == 1 or (
            "DEVICE_LITTER_NOTENOUGH" in self._error_keys()
        )

    @property
    def sandbox_low(self) -> bool:
        """Return whether the API reports insufficient sandbox material."""
        return self._number(self.detail.get("sandboxBalance"), integer=True) == 1 or (
            "SANDBOX_NOTENOUGH" in self._error_keys()
        )

    @property
    def timed_cleaning(self) -> bool:
        """Return whether scheduled cleaning is enabled."""
        return self._flag(self.detail.get("timerSwitch"))

    @property
    def deodorant_enabled(self) -> bool:
        """Return whether the deodorant system is enabled."""
        return self._flag(self.detail.get("deodorantEnable"))

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
            "litter_weight": {"icon": "mdi:weight", "unit": "kg"},
            "manual_clean_time": {"icon": "mdi:history", "unit": "times"},
            "induction_clean_time": {"icon": "mdi:autorenew", "unit": "times"},
            "clear_time": {"icon": "mdi:delete-sweep", "unit": "times"},
            "full_time": {"icon": "mdi:delete-alert", "unit": "times"},
            "work_mode": {"icon": "mdi:menu"},
            "cat_litter_balance": {"icon": "mdi:shaker-outline"},
            "sandbox_balance": {"icon": "mdi:shaker"},
            "empty_status": {"icon": "mdi:delete-sweep"},
            "temperature": {
                "icon": "mdi:thermometer",
                "class": SensorDeviceClass.TEMPERATURE,
                "unit": UnitOfTemperature.CELSIUS,
            },
            "humidity": {
                "icon": "mdi:water-percent",
                "class": SensorDeviceClass.HUMIDITY,
                "unit": PERCENTAGE,
            },
            "camera_switch": {"icon": "mdi:camera"},
            "litter_remaining_days": {"icon": "mdi:calendar", "unit": "days"},
            "deodorant_countdown": {"icon": "mdi:timer", "unit": "days"},
            "total_clean_time": {"icon": "mdi:history", "unit": "times"},
        }

    @property
    def hass_binary_sensor(self) -> dict:
        """Return C07 binary sensors."""
        return {
            "garbage_full": {"icon": "mdi:delete-alert"},
            "garbage_nearly_full": {"icon": "mdi:delete-clock"},
            "cat_detected": {"icon": "mdi:cat"},
            "sandbox_installed": {"icon": "mdi:package-variant-closed"},
            "garbage_box_missing": {"icon": "mdi:delete-off"},
            "litter_low": {"icon": "mdi:shaker-outline"},
            "sandbox_low": {"icon": "mdi:shaker"},
            "anti_pinch_protected": {"icon": "mdi:hand-back-right"},
            "engine_protected": {"icon": "mdi:engine-off"},
            "empty_state": {"icon": "mdi:delete-sweep"},
            "timed_cleaning": {"icon": "mdi:calendar-clock"},
            "deodorant_enabled": {"icon": "mdi:air-filter"},
        }

    @property
    def hass_switch(self) -> dict:
        """Return C07 configuration switches using the existing pattern."""
        return {
            "auto_clean": {
                "icon": "mdi:robot",
                "async_turn_on": partial(self.async_set_auto_clean, True),
                "async_turn_off": partial(self.async_set_auto_clean, False),
            },
            "kitty_model": {
                "icon": "mdi:cat",
                "async_turn_on": partial(self.async_set_kitty_model, True),
                "async_turn_off": partial(self.async_set_kitty_model, False),
            },
            "key_lock": {
                "icon": "mdi:lock",
                "async_turn_on": partial(self.async_set_key_lock, True),
                "async_turn_off": partial(self.async_set_key_lock, False),
            },
            "quiet_mode": {
                "icon": "mdi:volume-off",
                "async_turn_on": partial(self.async_set_quiet_mode, True),
                "async_turn_off": partial(self.async_set_quiet_mode, False),
            },
            "continuous_cleaning": {
                "icon": "mdi:replay",
                "async_turn_on": partial(self.async_set_continuous_cleaning, True),
                "async_turn_off": partial(self.async_set_continuous_cleaning, False),
            },
            "soft_model": {
                "icon": "mdi:feather",
                "async_turn_on": partial(self.async_set_soft_model, True),
                "async_turn_off": partial(self.async_set_soft_model, False),
            },
            "watermark": {
                "icon": "mdi:watermark",
                "async_turn_on": partial(self.async_set_watermark, True),
                "async_turn_off": partial(self.async_set_watermark, False),
            },
            "voice_prompt": {
                "icon": "mdi:volume-high",
                "async_turn_on": partial(self.async_set_voice_prompt, True),
                "async_turn_off": partial(self.async_set_voice_prompt, False),
            },
            "panel_tone": {
                "icon": "mdi:volume-high",
                "async_turn_on": partial(self.async_set_panel_tone, True),
                "async_turn_off": partial(self.async_set_panel_tone, False),
            },
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
            "pave_level_control": {
                "icon": "mdi:tune",
                "options": list(_PAVE_LEVEL_LABELS.values()),
                "state_attrs": self.pave_level_attrs,
                "async_select": self.select_pave_level,
            },
            "litter_type_control": {
                "icon": "mdi:shaker-outline",
                "options": list(_LITTER_TYPE_LABELS.values()),
                "state_attrs": self.litter_type_attrs,
                "async_select": self.select_litter_type,
            },
            "safe_time_control": {
                "icon": "mdi:timer",
                "options": list(_SAFE_TIME_LABELS.values()),
                "state_attrs": self.safe_time_attrs,
                "async_select": self.select_safe_time,
            },
            "fill_light_control": {
                "icon": "mdi:lightbulb",
                "options": list(_FILL_LIGHT_LABELS.values()),
                "state_attrs": self.fill_light_attrs,
                "async_select": self.select_fill_light,
            },
        }

    @property
    def hass_number(self) -> dict:
        """Return C07 number controls."""
        return {
            "add_sand_copies": {
                "name": "Add sand copies",
                "icon": "mdi:counter",
                "min": 1,
                "max": 3,
                "step": 1,
            }
        }

    def state_attrs(self) -> dict:
        """Return C07 state attributes."""
        return {
            **self._base_state_attrs(),
            "total_clean_times": self.total_clean_time,
            "run_status": self.detail.get("runStatus"),
            "final_status": self.detail.get("finalStatus"),
            "work_mode": self.work_mode,
            "clean_status": self.clean_status,
            "garbage_status": self.garbage_status,
            "empty_status": self.empty_status,
            "raw_clean_status": self.detail.get("cleanStatus"),
            "raw_garbage_status": self.detail.get("garbageStatus"),
            "raw_camera_switch": self.detail.get("cameraSwitch"),
            "cat_litter_balance": self.detail.get("catLitterBalance"),
            "sandbox_balance": self.detail.get("sandboxBalance"),
            "sandbox_installed": self.sandbox_installed,
            "empty_state": self.empty_state,
            "litter_type": self.detail.get("litterType"),
            "sand_pave_level": self.detail.get("sandPaveLevel"),
            "temperature": self.detail.get("temperature"),
            "humidity": self.detail.get("humidity"),
            "device_error_list": self.detail.get("deviceErrorList"),
            "device_warn": self.detail.get("deviceWarn"),
            "box_full_sensitivity": self.detail.get("boxFullSensitivity"),
            "full_times": self.detail.get("fullTimes"),
            "full_close_times": self.detail.get("fullCloseTimes"),
            "clear_times": self.detail.get("clearTimes"),
            "induction_times": self.detail.get("inductionTimes"),
            "manual_times": self.detail.get("manualTimes"),
            "induction_clean_time": self.induction_clean_time,
            "clear_time": self.clear_time,
            "full_time": self.full_time,
            "auto_clean": self.auto_clean,
            "kitty_model": self.kitty_model,
            "key_lock": self.key_lock,
            "quiet_mode": self.quiet_mode,
            "continuous_cleaning": self.continuous_cleaning,
            "soft_model": self.soft_model,
            "watermark": self.watermark,
            "voice_prompt": self.voice_prompt,
            "fill_light": self.fill_light,
            "panel_tone": self.panel_tone,
            "off_screen_duration": self.detail.get("offScreenDuration"),
            "quiet_times": self.detail.get("quietTimes"),
            "timing_switch": self.detail.get("timerSwitch"),
            "deodorant_enable": self.detail.get("deodorantEnable"),
            "timed_cleaning": self.timed_cleaning,
            "deodorant_enabled": self.deodorant_enabled,
            "camera_switch": self.camera_switch,
            "dn": self.detail.get("dn"),
        }

    def error_attrs(self) -> dict:
        """Return C07 error attributes."""
        return {
            "errors": self.detail.get("deviceErrorList") or [],
            "warning": self.detail.get("deviceWarn"),
            "active_error_keys": sorted(self._error_keys()),
            "cat_detected": self.cat_detected,
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

    def pave_level_attrs(self) -> dict:
        """Return the raw paving-level value."""
        return {"raw_level": self.detail.get("sandPaveLevel")}

    def litter_type_attrs(self) -> dict:
        """Return the raw litter-type value."""
        return {"raw_litter_type": self.detail.get("litterType")}

    def safe_time_attrs(self) -> dict:
        """Return the raw safe-time value."""
        return {"raw_safe_time": self.detail.get("safeTime")}

    def fill_light_attrs(self) -> dict:
        """Return the raw fill-light value."""
        return {"raw_fill_light": self.detail.get("fillLight")}

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
        """Select a C07 operation action."""
        action_code = next(
            (code for code, label in self.actions.items() if label == action), None
        )
        if action_code is None:
            _LOGGER.warning("Select C07 action failed for %s", action)
            return False
        behavior, command = action_code.split(":", 1)
        payload = {
            "deviceId": self.id,
            "behavior": behavior,
            "action": command,
        }
        if behavior == "ADD_SAND" and command == "RUN":
            payload["copies"] = str(self.add_sand_copies)
        response = await self.account.request(
            API_C07_ACTION_COMMAND_V2,
            payload,
            "POST",
        )
        if not await self._handle_action_response(response, "Select C07 action"):
            return False
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
        return await self._handle_action_response(
            response, "Select C07 box-full sensitivity"
        )

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
        return await self._handle_action_response(response, "Select C07 camera switch")

    async def _handle_action_response(self, response: dict, action_name: str) -> bool:
        """Handle a C07 command response and refresh the device state."""
        return_code = response.get("returnCode") if response else None
        success = (type(return_code) is int and return_code == 0) or (
            type(return_code) is str and return_code == "0"
        )
        if not response or not success:
            error = format_api_error(response) if response else "Request failed"
            _LOGGER.error("%s failed: %s", action_name, error)
            self._set_action_error(error)
            return False
        await self.update_device_detail()
        return True

    async def _set_toggle(
        self, api: str, enable: bool, action_name: str, key: str = "enable"
    ) -> bool:
        """Set a C07 boolean setting through its APK endpoint."""
        response = await self.account.request(
            api,
            {"deviceId": self.id, key: enable},
            "POST",
        )
        return await self._handle_action_response(response, action_name)

    async def async_set_auto_clean(self, enable: bool, **kwargs) -> bool:
        """Enable or disable automatic cleaning."""
        return await self._set_toggle(
            API_C07_AUTO_CLEAN,
            enable,
            "C07 automatic cleaning",
            "switchFlag",
        )

    async def async_set_kitty_model(self, enable: bool, **kwargs) -> bool:
        """Enable or disable kitten mode."""
        return await self._set_toggle(
            API_C07_KITTY_MODEL_SWITCH, enable, "C07 kitten mode"
        )

    async def async_set_key_lock(self, enable: bool, **kwargs) -> bool:
        """Enable or disable the C07 key lock."""
        response = await self.account.request(
            API_C07_KEY_LOCK,
            {"deviceId": self.id, "lockStatus": enable},
            "POST",
        )
        return await self._handle_action_response(response, "C07 key lock")

    async def async_set_quiet_mode(self, enable: bool, **kwargs) -> bool:
        """Enable or disable C07 quiet mode."""
        payload = {"deviceId": self.id, "enable": enable}
        if self.detail.get("quietTimes"):
            payload["times"] = self.detail["quietTimes"]
        response = await self.account.request(API_C07_QUIET_MODE, payload, "POST")
        return await self._handle_action_response(response, "C07 quiet mode")

    async def async_set_continuous_cleaning(self, enable: bool, **kwargs) -> bool:
        """Enable or disable continuous cleaning."""
        return await self._set_toggle(
            API_C07_CONTINUOUS_CLEANING, enable, "C07 continuous cleaning"
        )

    async def async_set_soft_model(self, enable: bool, **kwargs) -> bool:
        """Enable or disable C07 soft cleaning mode."""
        return await self._set_toggle(API_C07_SOFT_MODEL, enable, "C07 soft mode")

    async def async_set_watermark(self, enable: bool, **kwargs) -> bool:
        """Enable or disable the camera watermark."""
        return await self._set_toggle(API_C07_WATERMARK_SWITCH, enable, "C07 watermark")

    async def async_set_voice_prompt(self, enable: bool, **kwargs) -> bool:
        """Enable or disable camera voice prompts."""
        return await self._set_toggle(
            API_C07_VOICE_PROMPT_SWITCH, enable, "C07 voice prompt"
        )

    async def select_fill_light(self, value, **kwargs) -> bool:
        """Set the C07 three-state camera fill light."""
        status = next(
            (code for code, label in _FILL_LIGHT_LABELS.items() if label == value),
            None,
        )
        if status is None:
            _LOGGER.warning("Select C07 fill light failed for %s", value)
            return False
        response = await self.account.request(
            API_C07_FILL_LIGHT_SETTING,
            {"deviceId": self.id, "status": status},
            "POST",
        )
        return await self._handle_action_response(response, "Select C07 fill light")

    async def async_set_panel_tone(self, enable: bool, **kwargs) -> bool:
        """Enable or disable device panel sounds."""
        return await self._set_toggle(API_C07_PANELTONE, enable, "C07 panel tone")

    async def select_pave_level(self, value, **kwargs) -> bool:
        """Set the C07 paving level."""
        level = next(
            (code for code, label in _PAVE_LEVEL_LABELS.items() if label == value),
            None,
        )
        if level is None:
            _LOGGER.warning("Select C07 paving level failed for %s", value)
            return False
        response = await self.account.request(
            API_C07_PAVE_LEVEL,
            {"deviceId": self.id, "level": level},
            "POST",
        )
        return await self._handle_action_response(response, "Select C07 paving level")

    async def select_litter_type(self, value, **kwargs) -> bool:
        """Set the C07 litter type."""
        litter_type = next(
            (code for code, label in _LITTER_TYPE_LABELS.items() if label == value),
            None,
        )
        if litter_type is None:
            _LOGGER.warning("Select C07 litter type failed for %s", value)
            return False
        response = await self.account.request(
            API_C07_CAT_LITTER_SETTING,
            {"deviceId": self.id, "litterType": litter_type},
            "POST",
        )
        return await self._handle_action_response(response, "Select C07 litter type")

    async def select_safe_time(self, value, **kwargs) -> bool:
        """Set the C07 cleaning safe time."""
        safe_time = next(
            (code for code, label in _SAFE_TIME_LABELS.items() if label == value),
            None,
        )
        if safe_time is None:
            _LOGGER.warning("Select C07 safe time failed for %s", value)
            return False
        response = await self.account.request(
            API_C07_SAFE_TIME_SETTING,
            {"deviceId": self.id, "safeTime": safe_time},
            "POST",
        )
        return await self._handle_action_response(response, "Select C07 safe time")
