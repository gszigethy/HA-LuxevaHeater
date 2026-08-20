"""Actuator switch entity for the Luxeva Heater.

Wraps the heater on/off state as a plain HA switch so it can be used as the
heater entity in a Generic Thermostat helper.

Turn-on: publishes B<last_level> then T1 (arms a 1-hour safety countdown).
Turn-off: publishes T0 then B0.

Option-B safety: if the device is turned on externally (physical remote or
Luxeva app) without an active timer, the switch auto-publishes T1 to ensure
the cloud-loss safety property holds regardless of how the heater was started.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from homeassistant.components.switch import SwitchEntity
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
    async_add_entities([LuxevaActuatorSwitch(entry.runtime_data)])


class LuxevaActuatorSwitch(SwitchEntity):
    """On/off actuator switch designed for use with HA's Generic Thermostat helper.

    Turning on publishes B<last_level> + T1 (heater on, 1-hour timer armed).
    Turning off publishes T0 + B0 (timer cancelled, heater off).

    The 1-hour timer creates a heartbeat: when it expires, the device turns
    itself off and this switch reports OFF. Generic Thermostat re-calls turn_on
    if the setpoint is not yet reached, restarting the timer. If the MQTT
    connection drops instead, the device shuts off within one hour on its own
    — without any action from HA.

    External turn-on safety (Option B): if the device transitions from off to
    on via the physical remote or app and no timer is active, this switch
    auto-publishes T1 so the safety property holds unconditionally.
    """

    _attr_has_entity_name = True
    _attr_name = "Actuator"
    _attr_should_poll = False
    _attr_icon = "mdi:toggle-switch"

    def __init__(self, coordinator: LuxevaCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.client_id}_actuator"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.client_id)},
        )
        self._remove_listener: Callable[[], None] | None = None
        self._prev_prg: int = 0
        self._ha_turn_on_pending: bool = False

    async def async_added_to_hass(self) -> None:
        self._remove_listener = self._coordinator.add_listener(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener is not None:
            self._remove_listener()

    @callback
    def _handle_update(self) -> None:
        prg = self._coordinator.data.get("prg", 0)
        tmr: str = self._coordinator.data.get("tmr", "00:00")
        available = self._coordinator.data.get("available", False)

        if not available:
            # Reset stale state on disconnect so the next prg 0→>0 transition
            # is detected cleanly after reconnect, regardless of what happened
            # to the device while HA was disconnected.
            self._ha_turn_on_pending = False
            self._prev_prg = 0
        else:
            if prg > 0 and self._prev_prg == 0:
                if self._ha_turn_on_pending:
                    # Our own turn_on confirmed by device — clear the flag.
                    self._ha_turn_on_pending = False
                elif tmr == "00:00":
                    # Device turned on externally without a timer — arm safety timer.
                    _LOGGER.debug(
                        "Luxeva actuator: external turn-on without active timer — arming T1"
                    )
                    self._coordinator.publish("T1")
            self._prev_prg = prg

        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return self._coordinator.data.get("available", False)

    @property
    def is_on(self) -> bool:
        return self._coordinator.data.get("prg", 0) > 0

    async def async_turn_on(self, **kwargs) -> None:
        _LOGGER.debug(
            "Luxeva actuator: turning on at level %d with 1-hour timer",
            self._coordinator.last_level,
        )
        self._ha_turn_on_pending = True
        self._coordinator.publish(f"B{self._coordinator.last_level}")
        self._coordinator.publish("T1")

    async def async_turn_off(self, **kwargs) -> None:
        _LOGGER.debug("Luxeva actuator: turning off")
        self._coordinator.publish("T0")
        self._coordinator.publish("B0")
