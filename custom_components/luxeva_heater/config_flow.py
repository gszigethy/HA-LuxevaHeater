"""Config flow for the Luxeva Heater integration."""
from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult

from .const import (
    CONF_DISCLAIMER,
    CONF_MAC,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

_MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")

_STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_MAC): str,
    }
)

_STEP_DISCLAIMER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DISCLAIMER, default=False): bool,
    }
)


def _normalize_mac(raw: str) -> str | None:
    """Normalise various MAC formats to XX:XX:XX:XX:XX:XX uppercase."""
    cleaned = raw.strip().upper().replace("-", ":").replace(" ", "")
    if re.match(r"^[0-9A-F]{12}$", cleaned):
        cleaned = ":".join(cleaned[i : i + 2] for i in range(0, 12, 2))
    if _MAC_RE.match(cleaned):
        return cleaned
    return None


class LuxevaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the UI config flow for Luxeva Heater."""

    VERSION = 1

    def __init__(self) -> None:
        self._mac: str = ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            mac = _normalize_mac(user_input.get(CONF_MAC, ""))
            if mac is None:
                _LOGGER.debug("Config flow: invalid MAC entered: %r", user_input.get(CONF_MAC, ""))
                errors[CONF_MAC] = "invalid_mac"
            else:
                await self.async_set_unique_id(mac.replace(":", ""))
                self._abort_if_unique_id_configured()

                self._mac = mac
                _LOGGER.debug("Config flow: valid MAC %s, proceeding to disclaimer", mac)
                return await self.async_step_disclaimer()

        return self.async_show_form(
            step_id="user",
            data_schema=_STEP_USER_SCHEMA,
            errors=errors,
        )

    async def async_step_disclaimer(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            if not user_input.get(CONF_DISCLAIMER, False):
                errors[CONF_DISCLAIMER] = "disclaimer_not_accepted"
            else:
                _LOGGER.info("Config flow: disclaimer accepted, creating entry for %s", self._mac)
                return self.async_create_entry(
                    title=f"Luxeva Heater {self._mac}",
                    data={
                        CONF_MAC: self._mac,
                    },
                )

        return self.async_show_form(
            step_id="disclaimer",
            data_schema=_STEP_DISCLAIMER_SCHEMA,
            errors=errors,
        )
