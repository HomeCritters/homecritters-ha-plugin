"""Text: the pet's name."""

from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import FerretEntity
from .hub import FerretHub


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    hub: FerretHub = entry.runtime_data
    async_add_entities([FerretNameText(hub)])


class FerretNameText(FerretEntity, TextEntity):
    """The pet's display name (persisted on the device)."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "pet_name"
    _attr_icon = "mdi:rename"
    _attr_native_min = 1
    _attr_native_max = 14  # firmware truncates at 14 (Pet::setName) - match it

    def __init__(self, hub: FerretHub) -> None:
        super().__init__(hub, "petname")

    @property
    def native_value(self) -> str | None:
        return self._hub.data.get("name")

    async def async_set_value(self, value: str) -> None:
        await self._hub.send(f"name:{value}")
