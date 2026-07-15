"""Buttons: the pet-care actions (feed, pat, bath)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import FerretEntity
from .hub import FerretHub

BUTTONS: tuple[ButtonEntityDescription, ...] = (
    ButtonEntityDescription(key="feed", translation_key="feed", icon="mdi:food-apple"),
    ButtonEntityDescription(key="pat", translation_key="pat", icon="mdi:hand-heart"),
    ButtonEntityDescription(key="clean", translation_key="clean", icon="mdi:shower-head"),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    hub: FerretHub = entry.runtime_data
    async_add_entities(
        [FerretButton(hub, d) for d in BUTTONS] + [FerretRevokeAllButton(hub)]
    )


class FerretRevokeAllButton(FerretEntity, ButtonEntity):
    """End every paired connection - all clients must re-pair by PIN."""

    _attr_translation_key = "revoke_all"
    _attr_icon = "mdi:lan-disconnect"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hub: FerretHub) -> None:
        super().__init__(hub, "revoke_all")

    async def async_press(self) -> None:
        await self._hub.revoke_all()


class FerretButton(FerretEntity, ButtonEntity):
    def __init__(self, hub: FerretHub, description: ButtonEntityDescription) -> None:
        super().__init__(hub, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        # The command IS the key ("feed"/"pat"/"clean") in the WS protocol.
        await self._hub.send(self.entity_description.key)
