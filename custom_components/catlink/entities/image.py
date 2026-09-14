"""Image entities for CatLink."""

import httpx

from homeassistant.components.image import Image, ImageEntity
from homeassistant.util import dt as dt_util

from ..const import _LOGGER
from .base import CatlinkEntity


class CatlinkImageEntity(CatlinkEntity, ImageEntity):
    """Expose a device's latest event image."""

    def __init__(self, name, device, option=None) -> None:
        """Initialize both the CatLink coordinator and ImageEntity bases."""
        CatlinkEntity.__init__(self, name, device, option)
        ImageEntity.__init__(self, device.coordinator.hass)

    def update(self) -> None:
        """Update the current event image URL."""
        super().update()
        image_url = self._device.event_image_url(self._name)
        if image_url != getattr(self, "_attr_image_url", None):
            self._attr_image_url = image_url
            self._cached_image = None
        self._attr_image_last_updated = self._event_time()

    def _event_time(self):
        """Return the latest event time for ImageEntity state display."""
        record = self._device.event_data.get("last_event") or {}
        timezone = dt_util.get_time_zone(self.account.hass.config.time_zone)

        for value in (record.get("event_start"), record.get("time")):
            if value is None or value == "":
                continue

            raw = str(value)
            if raw.isdigit():
                try:
                    timestamp = float(raw)
                    if timestamp > 100_000_000_000:
                        timestamp /= 1000
                    if timestamp > 0:
                        return dt_util.utc_from_timestamp(timestamp).astimezone(
                            timezone
                        )
                except (OverflowError, OSError, ValueError):
                    continue

            candidate = raw
            if len(candidate) <= 8 and record.get("event_date"):
                candidate = f"{record['event_date']} {candidate}"
            parsed = dt_util.parse_datetime(candidate)
            if parsed is not None:
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone)
                else:
                    parsed = parsed.astimezone(timezone)
                return parsed

        return None

    async def _async_load_image_from_url(self, url: str) -> Image | None:
        """Load an image without logging its signed URL on failure."""
        if not url:
            return None
        try:
            response = await self._client.get(url, timeout=10)
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "image/jpeg")
            content_type = content_type.split(";", 1)[0].strip().lower()
            if not content_type.startswith("image/"):
                _LOGGER.warning(
                    "CatLink image %s returned non-image content type %s",
                    self._name,
                    content_type,
                )
                return None
            _LOGGER.debug(
                "CatLink image %s fetched status=%s content_type=%s bytes=%s",
                self._name,
                response.status_code,
                content_type,
                len(response.content),
            )
            return Image(content=response.content, content_type=content_type)
        except (httpx.HTTPError, TimeoutError) as exc:
            _LOGGER.debug(
                "CatLink image %s fetch failed error=%s",
                self._name,
                type(exc).__name__,
            )
            return None

    @property
    def state(self) -> str | None:
        """Use ImageEntity's timestamp-based state."""
        return ImageEntity.state.fget(self)

    @property
    def available(self) -> bool:
        """Report unavailable when the latest event has no image."""
        return super().available and bool(getattr(self, "_attr_image_url", None))
