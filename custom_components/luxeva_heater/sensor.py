"""Sensor entities for the Luxeva Heater: thermostat status and countdown timer."""
from __future__ import annotations

import logging
from collections.abc import Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import LuxevaConfigEntry, LuxevaCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LuxevaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([
        LuxevaTimerSensor(entry.runtime_data),
        LuxevaThermostatSensor(entry.runtime_data),
    ])


class LuxevaThermostatSensor(SensorEntity):
    """Reports the in-device thermostat setpoint as a plain-text state.

    Returns the active setpoint ("18 °C" – "37 °C") when the thermostat is
    enabled, or "Disabled" when it is off (device reports Hts 00).
    Mirrors the H17 / H18–H37 commands sent via the climate entity slider.
    """

    _attr_has_entity_name = True
    _attr_name = "Thermostat"
    _attr_should_poll = False
    _attr_icon = "mdi:thermostat"

    def __init__(self, coordinator: LuxevaCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.client_id}_thermostat"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.client_id)},
        )
        self._remove_listener: Callable[[], None] | None = None

    async def async_added_to_hass(self) -> None:
        self._remove_listener = self._coordinator.add_listener(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener is not None:
            self._remove_listener()

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return self._coordinator.data.get("available", False)

    @property
    def native_value(self) -> str:
        hts = self._coordinator.data.get("hts", 0)
        if not hts:
            return "Disabled"
        return f"{hts} °C"


class LuxevaTimerSensor(SensorEntity):
    """Remaining countdown time in minutes, read directly from outTopic Tmr field.

    Updates every ~2 s as the device publishes status. Returns 0 when no
    timer is active (Tmr == 00:00).
    """

    _attr_has_entity_name = True
    _attr_name = "Timer Remaining"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_should_poll = False
    _attr_icon = "mdi:timer-outline"

    def __init__(self, coordinator: LuxevaCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.client_id}_timer_remaining"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.client_id)},
        )
        self._remove_listener: Callable[[], None] | None = None

    async def async_added_to_hass(self) -> None:
        self._remove_listener = self._coordinator.add_listener(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener is not None:
            self._remove_listener()

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return self._coordinator.data.get("available", False)

    @property
    def native_value(self) -> int:
        """Return remaining minutes from the outTopic Tmr HH:MM field."""
        tmr: str = self._coordinator.data.get("tmr", "00:00")
        try:
            h, m = (int(x) for x in tmr.split(":"))
            return h * 60 + m
        except (ValueError, AttributeError):
            _LOGGER.warning("Unexpected Tmr format: %r", tmr)
            return 0
