"""Config flow for HomeCritters (manual host or zeroconf discovery).

Pairing (F-Sec 1): the device requires a 16-hex token (shown on its screen
under Config > Seguranca > Senha) as the first WebSocket message. The flow
asks for it and validates by actually authenticating a WS connection.
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST
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
        self._info: dict[str, Any] | None = None

    async def _fetch_info(self, host: str) -> dict[str, Any]:
        """GET /info from the device (identity: name, mac, fw). Public."""
        session = async_get_clientsession(self.hass)
        async with asyncio.timeout(10):
            resp = await session.get(f"http://{host}/info")
            resp.raise_for_status()
            return await resp.json(content_type=None)

    async def _check_token(self, host: str, token: str) -> bool:
        """True when the device accepts "auth:<token>" (answers with state)."""
        session = async_get_clientsession(self.hass)
        try:
            async with asyncio.timeout(10):
                ws = await session.ws_connect(f"ws://{host}:{WS_PORT}/")
                try:
                    await ws.send_str(f"auth:{token}")
                    msg = await ws.receive(timeout=5)
                    return msg.type == aiohttp.WSMsgType.TEXT
                finally:
                    await ws.close()
        except (aiohttp.ClientError, TimeoutError, OSError):
            return False

    def _entry_data(
        self, host: str, info: dict[str, Any], token: str
    ) -> dict[str, Any]:
        return {
            CONF_HOST: host,
            CONF_MAC: format_mac(info["mac"]),
            CONF_NAME: info.get("name", "HomeCritters"),
            CONF_FW: info.get("fw", "unknown"),
            CONF_TOKEN: token,
        }

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            token = user_input[CONF_TOKEN].strip().lower()
            try:
                info = await self._fetch_info(host)
            except (aiohttp.ClientError, TimeoutError, KeyError, ValueError):
                errors["base"] = "cannot_connect"
            else:
                if not await self._check_token(host, token):
                    errors["base"] = "invalid_auth"
                else:
                    await self.async_set_unique_id(format_mac(info["mac"]))
                    self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                    return self.async_create_entry(
                        title=info.get("name", "HomeCritters"),
                        data=self._entry_data(host, info, token),
                    )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_HOST): str, vol.Required(CONF_TOKEN): str}
            ),
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
        assert self._host is not None and self._info is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            token = user_input[CONF_TOKEN].strip().lower()
            if await self._check_token(self._host, token):
                return self.async_create_entry(
                    title=self._info.get("name", "HomeCritters"),
                    data=self._entry_data(self._host, self._info, token),
                )
            errors["base"] = "invalid_auth"
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({vol.Required(CONF_TOKEN): str}),
            description_placeholders={"name": self._info.get("name", "HomeCritters")},
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Device rejected our token (changed/factory reset): ask again."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            token = user_input[CONF_TOKEN].strip().lower()
            if await self._check_token(entry.data[CONF_HOST], token):
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_TOKEN: token}
                )
            errors["base"] = "invalid_auth"
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_TOKEN): str}),
            description_placeholders={"name": entry.title},
            errors=errors,
        )
