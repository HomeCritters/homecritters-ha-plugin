"""The HomeCritters integration: a desk tamagotchi on an ESP32-S3 ball."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant, ServiceCall
import homeassistant.helpers.config_validation as cv

from .const import CONF_FW, CONF_MAC, CONF_NAME, CONF_TOKEN, DOMAIN
from .hub import FerretHub

PLATFORMS: list[Platform] = [
    Platform.ASSIST_SATELLITE,
    Platform.BUTTON,
    Platform.MEDIA_PLAYER,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TEXT,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hub = FerretHub(
        hass,
        entry.data[CONF_HOST],
        entry.data[CONF_MAC],
        entry.data.get(CONF_NAME, "HomeCritters"),
        entry.data.get(CONF_FW, "unknown"),
        token=entry.data.get(CONF_TOKEN, ""),
        on_auth_failed=lambda: entry.async_start_reauth(hass),
    )
    await hub.async_start()
    entry.runtime_data = hub
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _revoke_connection(call: ServiceCall) -> None:
        """End one paired connection by its slot (see the connections sensor)."""
        target = hass.config_entries.async_get_entry(call.data["config_entry"])
        if target and target.domain == DOMAIN:
            await target.runtime_data.revoke(int(call.data["slot"]))

    if not hass.services.has_service(DOMAIN, "revoke_connection"):
        hass.services.async_register(
            DOMAIN,
            "revoke_connection",
            _revoke_connection,
            schema=vol.Schema(
                {
                    vol.Required("config_entry"): cv.string,
                    vol.Required("slot"): vol.Coerce(int),
                }
            ),
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_stop()
    return unload_ok
