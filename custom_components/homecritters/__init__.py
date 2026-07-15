"""The HomeCritters integration: a desk tamagotchi on an ESP32-S3 ball."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant

from .const import CONF_FW, CONF_MAC, CONF_NAME, CONF_TOKEN
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
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_stop()
    return unload_ok
