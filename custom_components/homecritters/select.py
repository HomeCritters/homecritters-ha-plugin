"""Config selects: timezone, idle-clock delay, menu timeout, time/date format.

Mirrors the device portal's settings drawer 1:1 - same options, same wire
commands - so everything configurable on the ball is configurable from HA.
"""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import FerretEntity
from .hub import FerretHub

# (label shown in HA, wire value sent to the firmware) - kept identical to
# the web portal's option lists (web/src/App.jsx).
TZ_OPTIONS: list[tuple[str, str]] = [
    ("São Paulo (UTC-3)", "<-03>3"),
    ("UTC", "UTC0"),
    ("Lisboa", "WET0WEST,M3.5.0/1,M10.5.0"),
    ("Londres", "GMT0BST,M3.5.0/1,M10.5.0"),
    ("Nova York", "EST5EDT,M3.2.0,M11.1.0"),
    ("Los Angeles", "PST8PDT,M3.2.0,M11.1.0"),
    ("Berlim / Paris", "CET-1CEST,M3.5.0,M10.5.0/3"),
    ("Tóquio", "JST-9"),
    ("Sydney", "AEST-10AEDT,M10.1.0,M4.1.0/3"),
]
IDLE_OPTIONS: list[tuple[str, str]] = [
    ("15 segundos", "15"),
    ("30 segundos", "30"),
    ("1 minuto", "60"),
    ("2 minutos", "120"),
    ("5 minutos", "300"),
]
MENU_OPTIONS: list[tuple[str, str]] = [
    ("Desativado", "0"),
    ("5 segundos", "5"),
    ("10 segundos", "10"),
    ("15 segundos", "15"),
    ("30 segundos", "30"),
    ("1 minuto", "60"),
]
HOUR_OPTIONS: list[tuple[str, str]] = [("24h", "24"), ("12h", "12")]
DATE_OPTIONS: list[tuple[str, str]] = [("DD/MM/AAAA", "dmy"), ("MM/DD/AAAA", "mdy")]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    hub: FerretHub = entry.runtime_data
    async_add_entities(
        [
            FerretSelect(hub, "tz", "mdi:earth", TZ_OPTIONS, "tz",
                         lambda d: d.get("tz") or None),
            FerretSelect(hub, "idle_delay", "mdi:timer-sand", IDLE_OPTIONS, "idle",
                         lambda d: str(d.get("idleSec", ""))),
            FerretSelect(hub, "menu_timeout", "mdi:timer-off-outline", MENU_OPTIONS,
                         "menu", lambda d: str(d.get("menuSec", ""))),
            FerretSelect(hub, "hour_format", "mdi:clock-digital", HOUR_OPTIONS, "fmt",
                         lambda d: "24" if d.get("h24") else "12"),
            FerretSelect(hub, "date_format", "mdi:calendar", DATE_OPTIONS, "date",
                         lambda d: "dmy" if d.get("dmy", True) else "mdy"),
        ]
    )


class FerretSelect(FerretEntity, SelectEntity):
    """One device setting: a fixed option list mapped to a WS command."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        hub: FerretHub,
        key: str,
        icon: str,
        options: list[tuple[str, str]],
        cmd: str,
        current: Callable[[dict], str | None],
    ) -> None:
        super().__init__(hub, key)
        self._attr_translation_key = key
        self._attr_icon = icon
        self._pairs = options
        self._cmd = cmd
        self._current = current
        self._attr_options = [label for label, _ in options]

    @property
    def current_option(self) -> str | None:
        wire = self._current(self._hub.data)
        for label, value in self._pairs:
            if value == wire:
                return label
        return None

    async def async_select_option(self, option: str) -> None:
        for label, value in self._pairs:
            if label == option:
                await self._hub.send(f"{self._cmd}:{value}")
                return
