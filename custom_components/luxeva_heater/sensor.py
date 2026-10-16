"""Sensor entities for the Luxeva Heater: thermostat status and countdown timer."""

from __future__ import annotations

import logging
from collections.abc import Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CONF_BROKER,
    CONF_ENTRY_TYPE,
    CONF_LOCAL_SERVICE,
    CONF_PORT,
    DOMAIN,
    ENTRY_LOCAL_SERVICE,
)
from .coordinator import LuxevaConfigEntry, LuxevaCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LuxevaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_LOCAL_SERVICE:
        async_add_entities([LuxevaLocalServiceSensor(entry)])
        return
    async_add_entities(
        [
            LuxevaInternalTemperature(entry.runtime_data),
            LuxevaSessionSensor(entry.runtime_data),
            LuxevaTimerSensor(entry.runtime_data),
            LuxevaThermostatSensor(entry.runtime_data),
        ]
    )


class LuxevaThermostatSensor(SensorEntity):
    """Reports the in-device thermostat setpoint as a plain-text state.

    Returns the active setpoint ("18 °C" – "37 °C") when the thermostat is
    enabled, or "Disabled" when it is off (device reports Hts 00).
    Read-only — the thermostat can only be changed via the physical remote or the Luxeva app.
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


class _LuxevaDeviceSensor(SensorEntity):
    """Push-updated heater sensor. Defines no _attr_name, so subclasses can
    take their name from a translation_key."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: LuxevaCoordinator) -> None:
        self._coordinator = coordinator
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


class LuxevaTimerSensor(_LuxevaDeviceSensor):
    """Remaining countdown time in minutes, read directly from outTopic Tmr field.

    Updates every ~2 s as the device publishes status. Returns 0 when no
    timer is active (Tmr == 00:00).
    """

    _attr_name = "Timer Remaining"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_icon = "mdi:timer-outline"

    def __init__(self, coordinator: LuxevaCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.client_id}_timer_remaining"

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


class LuxevaInternalTemperature(_LuxevaDeviceSensor):
    """Raw internal reading, deliberately not presented as room temperature."""

    _attr_translation_key = "internal_temperature"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:thermometer"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.client_id}_internal_temperature"

    @property
    def native_value(self):
        return self._coordinator.data.get("tmp")


class LuxevaSessionSensor(_LuxevaDeviceSensor):
    """HA session time is distinct from the device safety countdown."""

    _attr_translation_key = "session_remaining"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_icon = "mdi:timer-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.client_id}_session_remaining"

    @property
    def native_value(self):
        return self._coordinator.control.session_minutes

    @property
    def extra_state_attributes(self):
        deadline = self._coordinator.control.deadline
        return {"ends_at": deadline.isoformat() if deadline else None}


class LuxevaLocalServiceSensor(SensorEntity):
    """One reusable service entry; heaters remain separate devices/entries."""

    _attr_has_entity_name = True
    _attr_translation_key = "local_service"
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:server-network"

    def __init__(self, entry):
        self.entry = entry
        self.runtime = entry.runtime_data
        self._attr_unique_id = f"local_service_{entry.entry_id}_status"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"local_service_{entry.entry_id}")},
            name=entry.title,
            manufacturer="HA-LuxevaHeater",
            model="Local MQTT service",
        )

    async def async_added_to_hass(self):
        self.async_on_remove(self.runtime.add_listener(self.async_write_ha_state))

    @property
    def native_value(self):
        return "connected" if self.runtime.connected else "unreachable"

    @property
    def extra_state_attributes(self):
        heaters = [
            entry.title
            for entry in self.hass.config_entries.async_entries(DOMAIN)
            if entry.options.get(CONF_LOCAL_SERVICE) == self.entry.entry_id
        ]
        return {
            "broker": self.runtime.options[CONF_BROKER],
            "port": self.runtime.options[CONF_PORT],
            "heaters": heaters,
        }
