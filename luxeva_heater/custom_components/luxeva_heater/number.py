"""Number entity for the Luxeva Heater timer."""
from __future__ import annotations

import logging
import math
from collections.abc import Callable

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, TIMER_MAX_HOURS
from .coordinator import LuxevaConfigEntry, LuxevaCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LuxevaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([LuxevaTimer(entry.runtime_data)])


class LuxevaTimer(NumberEntity):
    """Countdown timer for the Luxeva heater.

    Setting a value 1–9 publishes B<last_level> (if heater is off) then T<N>.
    Setting 0 publishes T0 to cancel an active timer.
    The displayed value tracks remaining time (ceiling to nearest hour); resets
    to 0 automatically when the device reports Tmr 00:00.
    """

    _attr_has_entity_name = True
    _attr_name = "Timer"
    _attr_device_class = NumberDeviceClass.DURATION
    _attr_native_min_value = 0      # 0 = no active timer (read-only state)
    _attr_native_max_value = TIMER_MAX_HOURS
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_mode = NumberMode.AUTO
    _attr_should_poll = False
    _attr_icon = "mdi:timer"

    def __init__(self, coordinator: LuxevaCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.client_id}_timer"
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
    def native_value(self) -> float:
        """Return remaining hours (ceiling of HH:MM countdown); 0 when no timer is set."""
        tmr: str = self._coordinator.data.get("tmr", "00:00")
        try:
            h, m = (int(x) for x in tmr.split(":"))
            total_minutes = h * 60 + m
            return min(math.ceil(total_minutes / 60), TIMER_MAX_HOURS) if total_minutes else 0
        except (ValueError, AttributeError):
            return 0

    async def async_set_native_value(self, value: float) -> None:
        hours = int(value)
        if hours > 0 and self._coordinator.data.get("prg", 0) == 0:
            _LOGGER.debug("Heater off — turning on at level %d before setting timer", self._coordinator.last_level)
            self._coordinator.publish(f"B{self._coordinator.last_level}")
        _LOGGER.debug("Setting timer: %d hour(s)", hours)
        self._coordinator.publish(f"T{hours}")
