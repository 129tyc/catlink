"""Binary entities for CatLink integration."""

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.const import STATE_OFF, STATE_ON

from ..devices.base import Device
from .base import CatlinkEntity


class CatlinkBinaryEntity(CatlinkEntity):
    """CatlinkBinaryEntity."""

    def __init__(self, name, device: Device, option=None) -> None:
        """Initialize the entity."""
        super().__init__(name, device, option)
        self._attr_is_on = False

    def update(self) -> None:
        """Update the entity."""
        super().update()
        if hasattr(self._device, self._name):
            value = getattr(self._device, self._name)
            self._attr_is_on = None if value is None else bool(value)
        else:
            self._attr_is_on = False

    @property
    def state(self) -> str | None:
        """Return the state of the entity."""
        if self._attr_is_on is None:
            return None
        return STATE_ON if self._attr_is_on else STATE_OFF


class CatlinkBinarySensorEntity(CatlinkBinaryEntity, BinarySensorEntity):
    """Binary sensor entity for CatLink."""
