"""WebSocket client for the HomeCritters device.

The firmware pushes its full state as JSON over a plain WebSocket (port 81)
and accepts short text commands ("feed", "vol:80", "media:play:<url>", ...).
This hub keeps one connection alive, fans state updates out to the entities
and exposes a send() used by every control.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
import logging
import secrets
import unicodedata
from collections.abc import Callable

import aiohttp

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_state_change_event

from .const import WS_PORT

_LOGGER = logging.getLogger(__name__)

RECONNECT_SECONDS = 5

# Domains the device panel can toggle on/off (everything else is read-only,
# e.g. sensors show their value). cover/lock get a domain-specific service.
CONTROLLABLE = {
    "light", "switch", "fan", "input_boolean", "cover", "lock", "siren",
    "humidifier",
}


class FerretHub:
    """Owns the WS connection + last known state."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        mac: str,
        name: str,
        fw: str,
        token: str = "",
        on_auth_failed: Callable[[], None] | None = None,
        entities: list[str] | None = None,
    ) -> None:
        self.hass = hass
        self.host = host
        self.mac = mac
        self.name = name
        self.fw = fw
        self._token = token
        self._on_auth_failed = on_auth_failed
        self._auth_fail_streak = 0
        self.clients: list[dict] = []  # connections manager list (from clients:)
        # HA panel: entities exposed on the device screen (options flow).
        self._entities = entities or []
        self._ha_unsub: Callable[[], None] | None = None
        self._ha_last: dict[str, str] = {}  # last-sent display sig (throttle)
        self.data: dict = {}
        self.available = False
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._task: asyncio.Task | None = None
        self._listeners: set[Callable[[], None]] = set()
        # Voice assistant sinks (set by the assist_satellite entity).
        self._audio_sink: asyncio.Queue[bytes] | None = None
        self._event_cb: Callable[[str], None] | None = None

    @property
    def mic_enabled(self) -> bool:
        """Mic privacy gate - DEVICE-owned (micMuted in its state push, also
        flipped by a quick BOOT tap or the HA switch via mute:on/off). The
        assist satellite arms/disarms the wake word run off this."""
        return not self.data.get("micMuted", False)

    async def async_start(self) -> None:
        self._task = self.hass.loop.create_task(self._run())

    async def async_stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def subscribe(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.add(cb)

        def _unsub() -> None:
            self._listeners.discard(cb)

        return _unsub

    @callback
    def _notify(self) -> None:
        for cb in list(self._listeners):
            cb()

    # --- voice assistant wiring (assist_satellite entity) ---
    def set_audio_sink(self, queue: asyncio.Queue[bytes] | None) -> None:
        """Route incoming binary mic frames into this queue (None = drop)."""
        self._audio_sink = queue

    def clear_audio_sink(self, queue: asyncio.Queue[bytes]) -> None:
        """Drop the sink ONLY if it's still `queue`. A cancelled pipeline run
        cleans up after the replacement run installed its own queue - an
        unconditional clear here deafened the new run (PTT went silent)."""
        if self._audio_sink is queue:
            self._audio_sink = None

    def set_event_cb(self, cb: Callable[[str], None] | None) -> None:
        """Receive device voice events ('ptt:start', 'ptt:end', ...)."""
        self._event_cb = cb

    def _hmac(self, nonce: str) -> str:
        """HMAC-SHA256(token, nonce) as lowercase hex - matches the firmware."""
        return hmac.new(
            self._token.encode(), nonce.encode(), hashlib.sha256
        ).hexdigest()

    async def revoke(self, slot: int) -> None:
        """End one paired connection (device rotates that slot's credential)."""
        await self.send(f"revoke:{int(slot)}")

    async def revoke_all(self) -> None:
        """End every connection - all clients (including us) must re-pair."""
        await self.send("revoke:all")

    # --- HA panel bridge (device screen: sensors + on/off controls) ---
    def _entity_payload(self, state) -> dict | None:
        """Compact entity dict for the device: {id,n,d,s,v,c}."""
        if state is None:
            return None
        domain = state.entity_id.split(".")[0]
        raw_name = state.attributes.get("friendly_name") or state.entity_id
        # The device font is ASCII-only: transliterate accents (Umidade ok,
        # "Sala de Estar" ok, accented chars -> closest ASCII).
        name = (
            unicodedata.normalize("NFKD", raw_name)
            .encode("ascii", "ignore")
            .decode("ascii")
        )
        unit = state.attributes.get("unit_of_measurement") or ""
        raw_value = f"{state.state}{unit}" if domain in ("sensor", "number") else ""
        # ASCII-only for the device font (degree sign etc. get dropped).
        value = (
            unicodedata.normalize("NFKD", raw_value)
            .encode("ascii", "ignore")
            .decode("ascii")
        )
        return {
            "id": state.entity_id,
            "n": name[:18],
            "d": domain,
            "s": state.state,
            "v": value[:12],
            "c": domain in CONTROLLABLE,
            # device_class drives the icon on the device (person for
            # motion/occupancy/presence, sun for illuminance, ...).
            "dc": (state.attributes.get("device_class") or "")[:12],
        }

    async def _ha_setup(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        """Subscribe to the exposed entities and push the initial list."""
        self._ha_teardown()
        if self._entities:
            self._ha_unsub = async_track_state_change_event(
                self.hass, self._entities, self._ha_state_event
            )
        await self._ha_send_list(ws)

    async def _ha_send_list(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        items = [
            p
            for e in self._entities
            if (p := self._entity_payload(self.hass.states.get(e)))
        ]
        for p in items:
            self._ha_last[p["id"]] = p["s"] + "|" + p["v"]
        await ws.send_str("ha:list:" + json.dumps(items, separators=(",", ":")))

    @callback
    def _ha_state_event(self, event: Event) -> None:
        p = self._entity_payload(event.data.get("new_state"))
        if not p:
            return
        sig = p["s"] + "|" + p["v"]
        if self._ha_last.get(p["id"]) == sig:  # display unchanged: skip
            return
        self._ha_last[p["id"]] = sig
        self.hass.async_create_task(
            self._safe_send("ha:upd:" + json.dumps(p, separators=(",", ":")))
        )

    async def _safe_send(self, cmd: str) -> None:
        with contextlib.suppress(Exception):
            await self.send(cmd)

    async def _ha_command(self, eid: str, action: str) -> None:
        """Toggle a device from the panel (v1: on/off only)."""
        domain = eid.split(".")[0]
        try:
            if domain == "cover":
                await self.hass.services.async_call(
                    "cover", "toggle", {"entity_id": eid}, blocking=False
                )
            elif domain == "lock":
                st = self.hass.states.get(eid)
                svc = "unlock" if st and st.state == "locked" else "lock"
                await self.hass.services.async_call(
                    "lock", svc, {"entity_id": eid}, blocking=False
                )
            else:
                await self.hass.services.async_call(
                    "homeassistant", "toggle", {"entity_id": eid}, blocking=False
                )
        except Exception:  # noqa: BLE001 - a bad entity shouldn't kill the hub
            _LOGGER.warning("HA panel command failed: %s %s", eid, action)

    def _ha_teardown(self) -> None:
        if self._ha_unsub:
            self._ha_unsub()
            self._ha_unsub = None
        self._ha_last = {}

    async def send(self, cmd: str) -> None:
        if self._ws is None or self._ws.closed:
            raise HomeAssistantError(
                f"HomeCritters ({self.name}) is not connected; cannot send {cmd!r}"
            )
        try:
            await self._ws.send_str(cmd)
        except (aiohttp.ClientError, ConnectionError, OSError) as err:
            # The socket was a zombie (e.g. the device rebooted and this side
            # never noticed). Close it so _run() reconnects, flag entities
            # unavailable right away, and surface the failure to the caller
            # (Music Assistant retries once the player comes back).
            _LOGGER.warning("Send failed, reconnecting: %s", err)
            ws = self._ws
            self._ws = None
            if self.available:
                self.available = False
                self._notify()
            with contextlib.suppress(Exception):
                await ws.close()
            raise HomeAssistantError(
                f"HomeCritters ({self.name}) connection lost while sending {cmd!r}"
            ) from err

    async def _run(self) -> None:
        session = async_get_clientsession(self.hass)
        while True:
            try:
                # heartbeat=10: detect a dead socket (device reboot / WiFi
                # drop) within seconds - a zombie connection here silently
                # swallowed Music Assistant play commands.
                async with session.ws_connect(
                    f"ws://{self.host}:{WS_PORT}/", heartbeat=10
                ) as ws:
                    self._ws = ws
                    # Challenge-response (F-Sec 2): the device greets us with
                    # "challenge:<nonce>". We answer HMAC(token, nonce) plus
                    # our own nonce and require the device to prove itself back
                    # (mutual auth) before we trust anything or send voice:sub.
                    cnonce = secrets.token_hex(16)
                    got_state = False
                    verified = False
                    async for msg in ws:
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            if msg.type == aiohttp.WSMsgType.BINARY:
                                if verified and self._audio_sink is not None:
                                    self._audio_sink.put_nowait(msg.data)
                            elif msg.type in (
                                aiohttp.WSMsgType.CLOSED,
                                aiohttp.WSMsgType.ERROR,
                            ):
                                break
                            continue
                        data = msg.data
                        if data.startswith("challenge:"):
                            resp = self._hmac(data[10:])
                            await ws.send_str(f"auth:{resp}:{cnonce}")
                            continue
                        if data.startswith("proof:"):
                            if not hmac.compare_digest(data[6:], self._hmac(cnonce)):
                                _LOGGER.warning("Device failed proof - not the real ball")
                                break
                            verified = True
                            await ws.send_str("voice:sub")
                            await ws.send_str("label:Home Assistant")
                            await ws.send_str("clients?")
                            await self._ha_setup(ws)  # panel: subscribe + list
                            continue
                        if data.startswith("ha:cmd:"):
                            eid, _, action = data[7:].partition(":")
                            await self._ha_command(eid, action)
                            continue
                        if data == "ha:sub":
                            await self._ha_send_list(ws)
                            continue
                        if data.startswith("clients:"):
                            try:
                                self.clients = json.loads(data[8:])
                            except ValueError:
                                self.clients = []
                            self._notify()
                            continue
                        if not got_state:
                            got_state = True  # first state frame = authenticated
                            self._auth_fail_streak = 0
                            self.available = True
                            self._notify()
                        # Voice events ("evt:ptt:start") aren't JSON state.
                        if data.startswith("evt:"):
                            _LOGGER.debug("device event %s", data)
                            if self._event_cb is not None:
                                self._event_cb(data[4:])
                            continue
                        try:
                            self.data = json.loads(data)
                        except ValueError:
                            continue
                        self._notify()
                    # Connected but closed before ANY state frame = the device
                    # rejected our token. After 3 straight rejections (not a
                    # reboot fluke), ask the user to re-pair.
                    if not got_state:
                        self._auth_fail_streak += 1
                        _LOGGER.warning(
                            "Device closed before auth reply (%d/3)",
                            self._auth_fail_streak,
                        )
                        if self._auth_fail_streak >= 3 and self._on_auth_failed:
                            self._on_auth_failed()
            except asyncio.CancelledError:
                self._ws = None
                raise
            except (aiohttp.ClientError, OSError) as err:
                _LOGGER.debug("WS connection error: %s", err)

            self._ws = None
            self.clients = []
            self._ha_teardown()
            if self.available:
                self.available = False
                self._notify()
            await asyncio.sleep(RECONNECT_SECONDS)
