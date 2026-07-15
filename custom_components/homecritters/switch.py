"""Switches: sleep, night mode (+ its sound settings) and the idle clock."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
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
    async_add_entities(
        [
            FerretSleepSwitch(hub),
            FerretMicSwitch(hub),
            FerretNightSwitch(hub),
            FerretNightSoundSwitch(hub, "sleepsnd", "sleep_sound", "mdi:music-note"),
            FerretNightSoundSwitch(hub, "wakesnd", "wake_sound", "mdi:alarm"),
            FerretClockSwitch(hub),
        ]
    )


class FerretSleepSwitch(FerretEntity, SwitchEntity):
    _attr_translation_key = "sleep"
    _attr_icon = "mdi:sleep"

    def __init__(self, hub: FerretHub) -> None:
        super().__init__(hub, "sleep")

    @property
    def is_on(self) -> bool:
        return bool(self._hub.data.get("sleeping"))

    async def async_turn_on(self, **kwargs) -> None:
        if not self.is_on:  # the firmware command is a toggle
            await self._hub.send("sleep")

    async def async_turn_off(self, **kwargs) -> None:
        if self.is_on:
            await self._hub.send("sleep")


class FerretMicSwitch(FerretEntity, SwitchEntity):
    """Microphone privacy switch (Echo-style): off = the device refuses to
    stream ANY audio (PTT denied, mic:on ignored) and shows a red LED.

    The device owns the state (persisted in NVS, also toggled by a quick
    BOOT tap); this mirrors data["micMuted"], inverted: switch on = mic live.
    """

    _attr_translation_key = "mic"
    _attr_icon = "mdi:microphone"

    def __init__(self, hub: FerretHub) -> None:
        super().__init__(hub, "mic")

    @property
    def is_on(self) -> bool:
        return not self._hub.data.get("micMuted", False)

    async def async_turn_on(self, **kwargs) -> None:
        await self._hub.send("mute:off")

    async def async_turn_off(self, **kwargs) -> None:
        await self._hub.send("mute:on")


class FerretNightSwitch(FerretEntity, SwitchEntity):
    """Full sleep / night mode: screen and LED off, pet asleep.

    Made for schedule automations (e.g. off at 23:00, on at 07:00). A local
    touch or BOOT press on the device also wakes it - the switch state
    follows via the device's state push.
    """

    _attr_translation_key = "night"
    _attr_icon = "mdi:weather-night"

    def __init__(self, hub: FerretHub) -> None:
        super().__init__(hub, "night")

    @property
    def is_on(self) -> bool:
        return bool(self._hub.data.get("fullSleep"))

    async def async_turn_on(self, **kwargs) -> None:
        await self._hub.send("fullsleep:on")

    async def async_turn_off(self, **kwargs) -> None:
        await self._hub.send("fullsleep:off")


class FerretNightSoundSwitch(FerretEntity, SwitchEntity):
    """Night-mode sound settings: play the snore/wake tune on FULL-sleep
    transitions? (The regular sleep button always keeps its sounds.)

    cmd is the firmware command prefix and the state JSON key differs only
    in casing: "sleepsnd" -> data["sleepSnd"], "wakesnd" -> data["wakeSnd"].
    """

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hub: FerretHub, cmd: str, key: str, icon: str) -> None:
        super().__init__(hub, cmd)
        self._cmd = cmd
        self._data_key = "sleepSnd" if cmd == "sleepsnd" else "wakeSnd"
        self._attr_translation_key = key
        self._attr_icon = icon

    @property
    def is_on(self) -> bool:
        return bool(self._hub.data.get(self._data_key, True))

    async def async_turn_on(self, **kwargs) -> None:
        await self._hub.send(f"{self._cmd}:on")

    async def async_turn_off(self, **kwargs) -> None:
        await self._hub.send(f"{self._cmd}:off")


class FerretClockSwitch(FerretEntity, SwitchEntity):
    _attr_translation_key = "idle_clock"
    _attr_icon = "mdi:clock-outline"

    def __init__(self, hub: FerretHub) -> None:
        super().__init__(hub, "clock")

    @property
    def is_on(self) -> bool:
        return bool(self._hub.data.get("clockOn"))

    async def async_turn_on(self, **kwargs) -> None:
        await self._hub.send("clock:on")

    async def async_turn_off(self, **kwargs) -> None:
        await self._hub.send("clock:off")
