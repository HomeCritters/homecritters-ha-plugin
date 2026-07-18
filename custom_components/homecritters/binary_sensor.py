"""Binary sensors: honest, effective device state (not settings).

"Assistant listening" mirrors the device's end-to-end truth (micLive):
streaming AND the pipeline confirmed it's consuming AND not muted AND not
in night mode - the same rule as the cyan mic icon on the screen. The
Microphone SWITCH shows the mute *setting*; this shows what's really
happening (night mode gates the mic without touching the setting).
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import FerretEntity
from .hub import FerretHub


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    hub: FerretHub = entry.runtime_data
    async_add_entities([FerretListeningSensor(hub)])


class FerretListeningSensor(FerretEntity, BinarySensorEntity):
    """On = the assistant can actually hear (device is streaming mic audio
    into a live HA pipeline). Off while muted, in night mode, or whenever
    the pipeline isn't consuming - regardless of the mute switch."""

    _attr_translation_key = "listening"
    _attr_device_class = BinarySensorDeviceClass.SOUND

    def __init__(self, hub: FerretHub) -> None:
        super().__init__(hub, "listening")

    @property
    def is_on(self) -> bool:
        return bool(self._hub.data.get("micLive"))
