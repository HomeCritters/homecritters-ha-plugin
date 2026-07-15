"""Config flow for HomeCritters (manual host or zeroconf discovery).

Pairing (F-Sec 1): TV-style. The flow asks the device to pair ("pair:start"),
which pops a random 6-digit PIN on its screen; the user types the PIN here
and the device hands back its long-lived token ("token:<hex>"), which we
store. The token itself is never displayed anywhere.
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PIN
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import format_mac

try:  # HA 2025.1+ location, with a fallback for slightly older cores
    from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
except ImportError:  # pragma: no cover
    from homeassistant.components.zeroconf import ZeroconfServiceInfo

from .const import CONF_FW, CONF_MAC, CONF_NAME, CONF_TOKEN, DOMAIN, WS_PORT


class FerretBallConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._host: str | None = None
        self._info: dict[str, Any] = {}

    async def _fetch_info(self, host: str) -> dict[str, Any]:
        """GET /info from the device (identity: name, mac, fw). Public."""
        session = async_get_clientsession(self.hass)
        async with asyncio.timeout(10):
            resp = await session.get(f"http://{host}/info")
            resp.raise_for_status()
            return await resp.json(content_type=None)

    async def _pair_request(self, host: str) -> bool:
        """Ask the device to pair: pops the 6-digit PIN on its screen."""
        session = async_get_clientsession(self.hass)
        try:
            async with asyncio.timeout(8):
                ws = await session.ws_connect(f"ws://{host}:{WS_PORT}/")
                await ws.send_str("pair:start")
                await asyncio.sleep(0.3)  # let the frame flush before closing
                await ws.close()
            return True
        except (aiohttp.ClientError, TimeoutError, OSError):
            return False

    async def _pair_submit(self, host: str, pin: str) -> str | None:
        """Submit the PIN; returns the long-lived token when accepted."""
        session = async_get_clientsession(self.hass)
        try:
            async with asyncio.timeout(10):
                ws = await session.ws_connect(f"ws://{host}:{WS_PORT}/")
                try:
                    await ws.send_str(f"pair:{pin}")
                    # The device greets with "challenge:<nonce>" first; skip
                    # any frame until the "token:<hex>" reply (or a close).
                    for _ in range(4):
                        msg = await ws.receive(timeout=5)
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            return None
                        if msg.data.startswith("token:"):
                            return msg.data[6:]
                    return None
                finally:
                    await ws.close()
        except (aiohttp.ClientError, TimeoutError, OSError):
            return None

    def _entry_data(self, token: str) -> dict[str, Any]:
        return {
            CONF_HOST: self._host,
            CONF_MAC: format_mac(self._info["mac"]),
            CONF_NAME: self._info.get("name", "HomeCritters"),
            CONF_FW: self._info.get("fw", "unknown"),
            CONF_TOKEN: token,
        }

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            try:
                info = await self._fetch_info(host)
            except (aiohttp.ClientError, TimeoutError, KeyError, ValueError):
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(format_mac(info["mac"]))
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                self._host = host
                self._info = info
                if await self._pair_request(host):
                    return await self.async_step_pin()
                errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
            errors=errors,
        )

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        host = discovery_info.host
        try:
            info = await self._fetch_info(host)
        except (aiohttp.ClientError, TimeoutError, KeyError, ValueError):
            return self.async_abort(reason="cannot_connect")
        await self.async_set_unique_id(format_mac(info["mac"]))
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})
        self._host = host
        self._info = info
        self.context["title_placeholders"] = {"name": info.get("name", "HomeCritters")}
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._host is not None
        if user_input is not None:
            if await self._pair_request(self._host):
                return await self.async_step_pin()
            return self.async_abort(reason="cannot_connect")
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={"name": self._info.get("name", "HomeCritters")},
        )

    async def async_step_pin(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The PIN is now on the device screen; ask the user to type it."""
        assert self._host is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            pin = user_input[CONF_PIN].strip()
            token = await self._pair_submit(self._host, pin)
            if token:
                if self.source == SOURCE_REAUTH:
                    return self.async_update_reload_and_abort(
                        self._get_reauth_entry(), data_updates={CONF_TOKEN: token}
                    )
                return self.async_create_entry(
                    title=self._info.get("name", "HomeCritters"),
                    data=self._entry_data(token),
                )
            errors["base"] = "invalid_auth"
            # Wrong PIN closed our socket (and 3 misses close the window):
            # nudge the device to show a (possibly fresh) PIN again.
            await self._pair_request(self._host)
        return self.async_show_form(
            step_id="pin",
            data_schema=vol.Schema({vol.Required(CONF_PIN): str}),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Device rejected our token (re-paired/reset): pair again via PIN."""
        self._host = entry_data[CONF_HOST]
        self._info = {"mac": entry_data.get(CONF_MAC, ""),
                      "name": entry_data.get(CONF_NAME, "HomeCritters")}
        await self._pair_request(self._host)
        return await self.async_step_pin()
