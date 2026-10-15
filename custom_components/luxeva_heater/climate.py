"""Climate entity for the Luxeva WiFi infrared heater."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, LEVEL_TO_PRESET, MODE_CLIMATE, PRESET_MODES, PRESET_TO_LEVEL
from .coordinator import LuxevaConfigEntry, LuxevaCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LuxevaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([LuxevaClimate(entry.runtime_data)])


class LuxevaClimate(ClimateEntity):
    """Preserve the climate identity across compatibility and managed modes.

    Managed control supports an optional external room sensor and HA setpoint.
    P1–P6 selects intensity; heat/off describes controller intent during cycling.
    Compatibility retains the original direct device controls and Tmp display.
    """

    _attr_has_entity_name = True
    _attr_name = None  # main entity — device name is used directly
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_preset_modes = PRESET_MODES
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_should_poll = False

    def __init__(self, coordinator: LuxevaCoordinator) -> None:
        self._coordinator = coordinator
        self._control = getattr(coordinator, "control", None)
        if (
            self._control
            and self._control.mode == MODE_CLIMATE
            and self._control.sensor
        ):
            self._attr_supported_features |= ClimateEntityFeature.TARGET_TEMPERATURE
            self._attr_min_temp = 5
            self._attr_max_temp = 35
            self._attr_target_temperature_step = 0.5
        self._attr_unique_id = f"{coordinator.client_id}_climate"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.client_id)},
            name=coordinator.device_name,
            manufacturer="Luxeva",
            model="WiFi Infrared Heater",
        )
        self._remove_listener: Callable[[], None] | None = None

    # ------------------------------------------------------------------
    # HA lifecycle
    # ------------------------------------------------------------------

    async def async_added_to_hass(self) -> None:
        self._remove_listener = self._coordinator.add_listener(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener is not None:
            self._remove_listener()

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    # ------------------------------------------------------------------
    # State properties
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        return self._coordinator.data.get("available", False)

    @property
    def hvac_mode(self) -> HVACMode:
        if self._control and self._control.mode == MODE_CLIMATE:
            return (
                HVACMode.HEAT
                if self._control.enabled and not self._control.latched
                else HVACMode.OFF
            )
        return (
            HVACMode.HEAT if self._coordinator.data.get("prg", 0) > 0 else HVACMode.OFF
        )

    @property
    def hvac_action(self) -> HVACAction | None:
        """Derive current action from Prg, Tmp and Hts."""
        prg = self._coordinator.data.get("prg", 0)
        if self._control and self._control.mode == MODE_CLIMATE:
            if not self._control.enabled or self._control.latched:
                return HVACAction.OFF
            if self._control.problem:
                return None
            return HVACAction.HEATING if prg > 0 else HVACAction.IDLE
        if prg == 0:
            return HVACAction.OFF
        hts = self._coordinator.data.get("hts", 0)
        tmp = self._coordinator.data.get("tmp")
        # Thermostat is active and room has reached the setpoint — element cycles off.
        if hts and tmp is not None and tmp >= hts:
            return HVACAction.IDLE
        return HVACAction.HEATING

    @property
    def preset_mode(self) -> str | None:
        if self._control and self._control.managed:
            return LEVEL_TO_PRESET.get(self._coordinator.last_level)
        prg = self._coordinator.data.get("prg", 0)
        return LEVEL_TO_PRESET.get(prg) if prg > 0 else None

    @property
    def current_temperature(self) -> float | None:
        if self._control and self._control.sensor:
            return self._control.temperature
        tmp = self._coordinator.data.get("tmp")
        return float(tmp) if tmp is not None else None

    @property
    def target_temperature(self) -> float | None:
        return (
            self._control.target
            if self._control
            and self._control.mode == MODE_CLIMATE
            and self._control.sensor
            else None
        )

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (
            self._control
            and self._control.mode == MODE_CLIMATE
            and self._control.sensor
            and ATTR_TEMPERATURE in kwargs
        ):
            self._control.set_target(float(kwargs[ATTR_TEMPERATURE]))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attributes = {}
        if self._control:
            attributes = {
                "control_mode": self._control.mode,
                "control_problem": self._control.problem,
                "session_ends_at": self._control.deadline.isoformat()
                if self._control.deadline
                else None,
                "safety_shutdown": self._control.latched,
            }
        return attributes | {
            # Raw countdown HH:MM — useful in automations.
            # The Timer number entity exposes this as a settable hours value.
            "timer": self._coordinator.data.get("tmr"),
            "msg_sequence": self._coordinator.data.get("msg"),
        }

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def async_turn_on(self) -> None:
        if self._control and self._control.managed:
            self._control.turn_on()
            return
        _LOGGER.debug("Turning on at level %d", self._coordinator.last_level)
        self._coordinator.publish(f"B{self._coordinator.last_level}")

    async def async_turn_off(self) -> None:
        if self._control and self._control.managed:
            self._control.turn_off()
            return
        _LOGGER.debug("Turning off")
        self._coordinator.publish("B0")

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self.async_turn_off()
        else:
            await self.async_turn_on()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        level = PRESET_TO_LEVEL.get(preset_mode)
        if level is not None:
            _LOGGER.debug("Setting preset mode: %s (B%d)", preset_mode, level)
            if self._control and self._control.managed:
                self._control.set_level(level)
                return
            self._coordinator.last_level = level
            self._coordinator.publish(f"B{level}")
