"""Guided heater setup and separate, reusable local MQTT service setup."""

from __future__ import annotations

import asyncio
import re
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_BROKER,
    CONF_CONNECTION,
    CONF_CONTROL_MODE,
    CONF_DISCLAIMER,
    CONF_ENTRY_TYPE,
    CONF_LOCAL_SERVICE,
    CONF_MAC,
    CONF_MIN_CYCLE,
    CONF_PORT,
    CONF_POWER_SWITCH,
    CONF_PREPARE_BROKER,
    CONF_PROTECT_EXTERNAL,
    CONF_SENSOR,
    CONF_SENSOR_TIMEOUT,
    CONF_TOLERANCE,
    CONNECTION_CLOUD,
    CONNECTION_LOCAL,
    DEFAULT_OPTIONS,
    DEFAULT_PORT,
    DOMAIN,
    ENTRY_HEATER,
    ENTRY_LOCAL_SERVICE,
    MODE_ACTUATOR,
    MODE_CLIMATE,
    MODE_COMPATIBILITY,
)
from .local import async_prepare_mosquitto, async_probe_broker

_MAC_RE = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$")


def _normalize_mac(raw: str) -> str | None:
    cleaned = raw.strip().upper().replace("-", ":").replace(" ", "")
    if re.fullmatch(r"[0-9A-F]{12}", cleaned):
        cleaned = ":".join(cleaned[i : i + 2] for i in range(0, 12, 2))
    return cleaned if _MAC_RE.fullmatch(cleaned) else None


def _heater_schema(hass, *, existing: bool = False) -> vol.Schema:
    services = [
        {"value": entry.entry_id, "label": entry.title}
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_LOCAL_SERVICE
    ]
    modes = [MODE_CLIMATE, MODE_ACTUATOR]
    if existing:
        modes.insert(0, MODE_COMPATIBILITY)
    fields = {
        vol.Required(CONF_CONTROL_MODE): selector.SelectSelector(
            selector.SelectSelectorConfig(options=modes, translation_key="control_mode")
        ),
        vol.Required(CONF_CONNECTION): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[CONNECTION_CLOUD, CONNECTION_LOCAL],
                translation_key="connection",
            )
        ),
        vol.Optional(CONF_SENSOR): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
        ),
        vol.Optional(CONF_POWER_SWITCH): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="switch")
        ),
        vol.Required(CONF_TOLERANCE): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0.1, max=3, step=0.1, mode=selector.NumberSelectorMode.BOX
            )
        ),
        vol.Required(CONF_MIN_CYCLE): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0,
                max=1800,
                step=1,
                unit_of_measurement="s",
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
        vol.Required(CONF_SENSOR_TIMEOUT): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0,
                max=1440,
                step=1,
                unit_of_measurement="min",
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
        vol.Required(CONF_PROTECT_EXTERNAL): bool,
    }
    if services:
        fields[vol.Optional(CONF_LOCAL_SERVICE)] = selector.SelectSelector(
            selector.SelectSelectorConfig(options=services)
        )
    return vol.Schema(fields)


def _broker_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_BROKER): str,
            vol.Required(CONF_PORT): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=65535)
            ),
            vol.Optional(CONF_PREPARE_BROKER, default=False): bool,
        }
    )


def _heater_errors(hass, values, mac: str) -> dict[str, str]:
    errors = {}
    if values[CONF_CONNECTION] == CONNECTION_LOCAL:
        service = hass.config_entries.async_get_entry(
            values.get(CONF_LOCAL_SERVICE, "")
        )
        if (
            service is None
            or service.domain != DOMAIN
            or service.data.get(CONF_ENTRY_TYPE) != ENTRY_LOCAL_SERVICE
        ):
            errors[CONF_CONNECTION] = "local_service_required"
    power = values.get(CONF_POWER_SWITCH)
    if power:
        from homeassistant.helpers import entity_registry as er

        registered = er.async_get(hass).async_get(power)
        if registered and registered.platform == DOMAIN:
            errors[CONF_POWER_SWITCH] = "invalid_power_switch"
    return errors


def _endpoint_in_use(hass, values, exclude: str | None = None) -> bool:
    """One service per broker endpoint; heaters reference the service entry."""
    broker = str(values[CONF_BROKER]).strip().lower()
    return any(
        entry.entry_id != exclude
        and entry.data.get(CONF_ENTRY_TYPE) == ENTRY_LOCAL_SERVICE
        and str(entry.options.get(CONF_BROKER, "")).strip().lower() == broker
        and entry.options.get(CONF_PORT) == values[CONF_PORT]
        for entry in hass.config_entries.async_entries(DOMAIN)
    )


class BrokerSetupMixin:
    """Shared progress step for new and existing local-service entries."""

    hass: Any
    _values: dict[str, Any]
    _broker_task: asyncio.Task | None = None
    _broker_error: str | None = None
    _own_entry_id: str | None = None

    async def _prepare(self) -> None:
        try:
            if self._values.get(CONF_PREPARE_BROKER):
                await async_prepare_mosquitto(self.hass)
            if not await async_probe_broker(self.hass, self._values):
                self._broker_error = "cannot_connect"
        except Exception:
            # Never expose exception text that could contain broker credentials.
            self._broker_error = "broker_setup_failed"

    async def async_step_prepare(self, user_input=None):
        if self._broker_task is None:
            self._broker_task = self.hass.async_create_task(self._prepare())
        if not self._broker_task.done():
            return self.async_show_progress(
                step_id="prepare",
                progress_action="prepare_broker",
                progress_task=self._broker_task,
            )
        await self._broker_task
        return self.async_show_progress_done(next_step_id="local_service")


# ConfigFlow consumes domain at runtime; HA imports are skipped by mypy in CI.
class LuxevaConfigFlow(BrokerSetupMixin, config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    """One heater per MAC, plus independently configured shared local services."""

    VERSION = 2

    def __init__(self) -> None:
        self._mac = ""
        self._name = ""
        self._values: dict[str, Any] = {}
        self._broker_task = None
        self._broker_error = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        if config_entry.data.get(CONF_ENTRY_TYPE) == ENTRY_LOCAL_SERVICE:
            return LuxevaServiceOptionsFlow()
        return LuxevaOptionsFlow()

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="user", menu_options=["heater", "local_service"]
        )

    async def async_step_heater(self, user_input=None) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            mac = _normalize_mac(user_input.get(CONF_MAC, ""))
            if mac is None:
                errors[CONF_MAC] = "invalid_mac"
            else:
                await self.async_set_unique_id(mac.replace(":", ""))
                self._abort_if_unique_id_configured()
                self._mac = mac
                self._name = str(user_input.get(CONF_NAME, "")).strip()
                return await self.async_step_disclaimer()
        return self.async_show_form(
            step_id="heater",
            # The name seeds the device name, so entity IDs read climate.patio
            # rather than carrying the MAC address.
            data_schema=vol.Schema(
                {vol.Required(CONF_MAC): str, vol.Optional(CONF_NAME): str}
            ),
            errors=errors,
        )

    async def async_step_disclaimer(self, user_input=None) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            if user_input.get(CONF_DISCLAIMER):
                return await self.async_step_settings()
            errors[CONF_DISCLAIMER] = "disclaimer_not_accepted"
        return self.async_show_form(
            step_id="disclaimer",
            data_schema=vol.Schema(
                {vol.Required(CONF_DISCLAIMER, default=False): bool}
            ),
            errors=errors,
        )

    async def async_step_settings(self, user_input=None) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            errors = _heater_errors(self.hass, user_input, self._mac)
            if not errors:
                data = {CONF_MAC: self._mac, CONF_ENTRY_TYPE: ENTRY_HEATER}
                if self._name:
                    data[CONF_NAME] = self._name
                return self.async_create_entry(
                    title=self._name or f"Luxeva Heater {self._mac}",
                    data=data,
                    options=DEFAULT_OPTIONS | user_input,
                )
        return self.async_show_form(
            step_id="settings",
            data_schema=self.add_suggested_values_to_schema(
                _heater_schema(self.hass), DEFAULT_OPTIONS | (user_input or {})
            ),
            errors=errors,
        )

    async def async_step_local_service(self, user_input=None) -> ConfigFlowResult:
        if (
            self._broker_task is not None
            and self._broker_task.done()
            and not self._broker_error
            # Recheck: another flow may have taken the endpoint while probing.
            and not _endpoint_in_use(self.hass, self._values, self._own_entry_id)
        ):
            values = {
                key: value
                for key, value in self._values.items()
                if key != CONF_PREPARE_BROKER
            }
            return self.async_create_entry(
                title=f"Local MQTT — {values[CONF_BROKER]}",
                data={CONF_ENTRY_TYPE: ENTRY_LOCAL_SERVICE},
                options=values,
            )
        errors = {"base": self._broker_error} if self._broker_error else {}
        if self._broker_task is not None and self._broker_task.done() and not errors:
            errors = {"base": "broker_in_use"}
            self._broker_task = None
        if user_input is not None:
            user_input = {**user_input, CONF_BROKER: user_input[CONF_BROKER].strip()}
            if _endpoint_in_use(self.hass, user_input):
                errors = {"base": "broker_in_use"}
            else:
                self._values = user_input
                self._broker_task = None
                self._broker_error = None
                return await self.async_step_prepare()
        return self.async_show_form(
            step_id="local_service",
            data_schema=self.add_suggested_values_to_schema(
                _broker_schema(),
                {
                    CONF_BROKER: "core-mosquitto",
                    CONF_PORT: DEFAULT_PORT,
                }
                | (user_input or self._values),
            ),
            errors=errors,
        )


class LuxevaOptionsFlow(config_entries.OptionsFlowWithReload):
    """Edit a heater independently of the shared local-service configuration."""

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            errors = _heater_errors(
                self.hass, user_input, self.config_entry.data[CONF_MAC]
            )
            runtime = getattr(self.config_entry, "runtime_data", None)
            if (
                runtime
                and runtime.control.latched
                and user_input.get(CONF_POWER_SWITCH) != runtime.control.power_switch
            ):
                errors[CONF_POWER_SWITCH] = "reset_safety_first"
            if not errors:
                if runtime:
                    # Every explicit reconfiguration ends the old session. It
                    # cannot reappear under a new owner after the entry reloads.
                    runtime.control.turn_off()
                    await runtime.control._store.async_save(runtime.control.snapshot())
                return self.async_create_entry(
                    title="", data=DEFAULT_OPTIONS | user_input
                )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                _heater_schema(self.hass, existing=True),
                DEFAULT_OPTIONS | dict(self.config_entry.options) | (user_input or {}),
            ),
            errors=errors,
        )


class LuxevaServiceOptionsFlow(BrokerSetupMixin, config_entries.OptionsFlow):
    """Edit a shared broker. Not OptionsFlowWithReload: the service entry's
    update listener ends dependent sessions and reloads the service and heaters."""

    def __init__(self) -> None:
        self._values: dict[str, Any] = {}
        self._broker_task = None
        self._broker_error = None

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        self._own_entry_id = self.config_entry.entry_id
        return await self.async_step_local_service(user_input)

    async def async_step_local_service(self, user_input=None) -> ConfigFlowResult:
        if (
            self._broker_task is not None
            and self._broker_task.done()
            and not self._broker_error
            # Recheck: another flow may have taken the endpoint while probing.
            and not _endpoint_in_use(self.hass, self._values, self._own_entry_id)
        ):
            values = {
                key: value
                for key, value in self._values.items()
                if key != CONF_PREPARE_BROKER
            }
            return self.async_create_entry(title="", data=values)
        errors = {"base": self._broker_error} if self._broker_error else {}
        if self._broker_task is not None and self._broker_task.done() and not errors:
            errors = {"base": "broker_in_use"}
            self._broker_task = None
        if user_input is not None:
            user_input = {**user_input, CONF_BROKER: user_input[CONF_BROKER].strip()}
            if _endpoint_in_use(self.hass, user_input, self.config_entry.entry_id):
                errors = {"base": "broker_in_use"}
            else:
                self._values = user_input
                self._broker_task = None
                self._broker_error = None
                return await self.async_step_prepare()
        return self.async_show_form(
            step_id="local_service",
            data_schema=self.add_suggested_values_to_schema(
                _broker_schema(),
                dict(self.config_entry.options) | (user_input or self._values),
            ),
            errors=errors,
        )
