"""Luxeva WiFi Infrared Heater integration."""
from __future__ import annotations

import logging

from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONF_MAC, DEFAULT_BROKER, DEFAULT_PORT
from .coordinator import LuxevaConfigEntry, LuxevaCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.CLIMATE, Platform.NUMBER, Platform.SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: LuxevaConfigEntry) -> bool:
    mac = entry.data[CONF_MAC]

    _LOGGER.debug("Setting up Luxeva Heater for MAC %s (broker: %s:%d)", mac, DEFAULT_BROKER, DEFAULT_PORT)

    coordinator = LuxevaCoordinator(hass, mac, DEFAULT_BROKER, DEFAULT_PORT)
    try:
        await coordinator.async_connect()
    except Exception as exc:
        raise ConfigEntryNotReady(f"Cannot connect to Luxeva broker ({DEFAULT_BROKER}:{DEFAULT_PORT}): {exc}") from exc

    entry.runtime_data = coordinator

    # Config entries are not unloaded when Home Assistant stops; close the
    # MQTT connection explicitly so paho's thread does not outlive the loop.
    async def _async_stop(_event: Event) -> None:
        await coordinator.async_disconnect()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_stop))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.info("Luxeva Heater %s set up successfully", mac)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LuxevaConfigEntry) -> bool:
    mac = entry.data[CONF_MAC]
    _LOGGER.debug("Unloading Luxeva Heater for MAC %s", mac)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_disconnect()
        _LOGGER.info("Luxeva Heater %s unloaded", mac)
    return unload_ok
