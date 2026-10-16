"""Persistent safety shutdown state, available even when the heater is offline."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    if entry.runtime_data.control.power_switch:
        async_add_entities([LuxevaSafetySensor(entry.runtime_data)])


class LuxevaSafetySensor(BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "safety_shutdown"
    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator):
        self.coordinator = coordinator
        self._attr_unique_id = f"{coordinator.client_id}_safety_shutdown_active"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.client_id)}
        )

    async def async_added_to_hass(self):
        self.async_on_remove(self.coordinator.add_listener(self.async_write_ha_state))

    @property
    def is_on(self):
        return self.coordinator.control.latched

    @property
    def extra_state_attributes(self):
        return {
            "power_cut_status": self.coordinator.control.power_cut_status,
            "upstream_switch": self.coordinator.control.power_switch,
        }
