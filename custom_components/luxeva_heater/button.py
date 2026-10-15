"""Explicit power cut and reset actions; neither action restores power."""

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    control = entry.runtime_data.control
    if control.power_switch:
        async_add_entities(
            [
                LuxevaSafetyButton(entry.runtime_data, False),
                LuxevaSafetyButton(entry.runtime_data, True),
            ]
        )


class LuxevaSafetyButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator, reset):
        self.control = coordinator.control
        self.reset = reset
        key = "reset_safety_shutdown" if reset else "safety_shutdown"
        self._attr_unique_id = f"{coordinator.client_id}_{key}"
        self._attr_translation_key = key
        self._attr_icon = "mdi:lock-reset" if reset else "mdi:power-plug-off"
        self._attr_entity_category = EntityCategory.CONFIG if reset else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.client_id)}
        )

    async def async_press(self):
        if self.reset:
            await self.control.async_reset_safety()
        else:
            await self.control.async_safety_shutdown()
