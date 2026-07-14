"""WebSocket client for the HomeCritters device.

The firmware pushes its full state as JSON over a plain WebSocket (port 81)
and accepts short text commands ("feed", "vol:80", "media:play:<url>", ...).
This hub keeps one connection alive, fans state updates out to the entities
and exposes a send() used by every control.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
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
        self, hass: HomeAssistant, host: str, mac: str, name: str, fw: str
    ) -> None:
        self.hass = hass
        self.host = host
        self.mac = mac
        self.name = name
        self.fw = fw
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
                    self.available = True
                    self._notify()
                    # Register as the device's voice audio sink so mic frames
                    # (binary) get streamed to us when the user talks.
                    await ws.send_str("voice:sub")
                    _LOGGER.debug("Connected to %s", self.host)
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = msg.data
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
                        elif msg.type == aiohttp.WSMsgType.BINARY:
                            # Raw 16kHz mono 16-bit PCM mic frame -> STT pipeline.
                            if self._audio_sink is not None:
                                self._audio_sink.put_nowait(msg.data)
                        elif msg.type in (
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.ERROR,
                        ):
                            break
            except asyncio.CancelledError:
                self._ws = None
                raise
            except (aiohttp.ClientError, OSError) as err:
                _LOGGER.debug("WS connection error: %s", err)

            self._ws = None
            if self.available:
                self.available = False
                self._notify()
            await asyncio.sleep(RECONNECT_SECONDS)
