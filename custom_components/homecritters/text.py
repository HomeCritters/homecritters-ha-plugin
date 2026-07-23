"""Text: the pet's name and birthday."""

from __future__ import annotations

import re

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
    async_add_entities([FerretNameText(hub), FerretBirthdayText(hub)])


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


class FerretBirthdayText(FerretEntity, TextEntity):
    """The pet's birthday as YYYY-MM-DD (the party fires on the MM-DD part; the
    year lets the portal show the pet's age). Legacy MM-DD is still accepted."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "birthday"
    _attr_icon = "mdi:cake-variant"
    _attr_pattern = r"(\d{4}-)?\d{2}-\d{2}"
    _attr_native_min = 5
    _attr_native_max = 10

    def __init__(self, hub: FerretHub) -> None:
        super().__init__(hub, "bday")

    @property
    def native_value(self) -> str | None:
        return self._hub.data.get("bday")

    async def async_set_value(self, value: str) -> None:
        if re.fullmatch(r"(\d{4}-)?\d{2}-\d{2}", value):
            await self._hub.send(f"bday:{value}")
