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
from collections.abc import Callable

import aiohttp

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import WS_PORT

_LOGGER = logging.getLogger(__name__)

RECONNECT_SECONDS = 5


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
        self.data: dict = {}
        self.available = False
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._task: asyncio.Task | None = None
        self._listeners: set[Callable[[], None]] = set()
        # Voice assistant sinks (set by the assist_satellite entity).
        self._audio_sink: asyncio.Queue[bytes] | None = None
        self._event_cb: Callable[[str], None] | None = None

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
            if self.available:
                self.available = False
                self._notify()
            await asyncio.sleep(RECONNECT_SECONDS)
