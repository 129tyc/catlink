"""Sensor entity for CatLink integration."""

from homeassistant.components.sensor import SensorEntity

from .base import CatlinkEntity


class CatlinkSensorEntity(CatlinkEntity, SensorEntity):
    """Sensor entity for CatLink."""

    @property
    def available(self) -> bool:
        """Combine coordinator health with an optional device availability check."""
        if not super().available:
            return False
        check = self._option.get("available")
        return bool(check()) if callable(check) else True
