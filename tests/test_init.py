"""Tests for Luxeva Heater config-entry setup and unload."""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.exceptions import ConfigEntryNotReady
import pytest

from custom_components import luxeva_heater
from custom_components.luxeva_heater.const import CONF_MAC


def make_hass() -> Mock:
    hass = Mock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    return hass


def make_entry() -> Mock:
    entry = Mock()
    entry.data = {CONF_MAC: "00:AA:11:BB:22:CC"}
    return entry


def test_setup_disconnects_on_home_assistant_stop() -> None:
    hass = make_hass()
    entry = make_entry()
    coordinator = Mock(async_connect=AsyncMock(), async_disconnect=AsyncMock())

    with patch.object(luxeva_heater, "LuxevaCoordinator", return_value=coordinator):
        assert asyncio.run(luxeva_heater.async_setup_entry(hass, entry)) is True

    assert entry.runtime_data is coordinator
    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        entry, luxeva_heater.PLATFORMS
    )
    event_type, stop_listener = hass.bus.async_listen_once.call_args.args
    assert event_type == EVENT_HOMEASSISTANT_STOP
    entry.async_on_unload.assert_called_once_with(hass.bus.async_listen_once.return_value)

    asyncio.run(stop_listener(Mock()))
    coordinator.async_disconnect.assert_awaited_once_with()


def test_setup_not_ready_when_broker_unreachable() -> None:
    hass = make_hass()
    coordinator = Mock(async_connect=AsyncMock(side_effect=OSError("unreachable")))

    with (
        patch.object(luxeva_heater, "LuxevaCoordinator", return_value=coordinator),
        pytest.raises(ConfigEntryNotReady),
    ):
        asyncio.run(luxeva_heater.async_setup_entry(hass, make_entry()))

    hass.config_entries.async_forward_entry_setups.assert_not_called()


def test_unload_disconnects() -> None:
    hass = make_hass()
    entry = make_entry()
    entry.runtime_data = Mock(async_disconnect=AsyncMock())

    assert asyncio.run(luxeva_heater.async_unload_entry(hass, entry)) is True

    entry.runtime_data.async_disconnect.assert_awaited_once_with()
