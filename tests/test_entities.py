"""Tests for Luxeva Heater entities."""

import asyncio
from homeassistant.components.climate import HVACAction, HVACMode

from custom_components.luxeva_heater.climate import LuxevaClimate
from custom_components.luxeva_heater.number import LuxevaTimer
from custom_components.luxeva_heater.sensor import (
    LuxevaThermostatSensor,
    LuxevaTimerSensor,
)
from custom_components.luxeva_heater.switch import LuxevaActuatorSwitch


class FakeCoordinator:
    """Minimal coordinator implementation used by entity tests."""

    def __init__(self) -> None:
        self.client_id = "00AA11BB22CC"
        self.last_level = 3
        self.data = {
            "available": True,
            "prg": 0,
            "tmp": 20,
            "hts": 0,
            "tmr": "00:00",
            "msg": 12,
        }
        self.commands: list[str] = []
        self.listener = None

    def publish(self, command: str) -> None:
        self.commands.append(command)

    def add_listener(self, listener):
        self.listener = listener

        def remove() -> None:
            self.listener = None

        return remove


def test_climate_state_and_commands() -> None:
    coordinator = FakeCoordinator()
    entity = LuxevaClimate(coordinator)

    assert entity.available is True
    assert entity.hvac_mode == HVACMode.OFF
    assert entity.hvac_action == HVACAction.OFF
    assert entity.preset_mode is None
    assert entity.current_temperature == 20.0
    assert entity.target_temperature is None
    assert entity.extra_state_attributes == {"timer": "00:00", "msg_sequence": 12}

    coordinator.data.update(prg=2, hts=24, tmp=20)
    assert entity.hvac_mode == HVACMode.HEAT
    assert entity.hvac_action == HVACAction.HEATING
    assert entity.preset_mode == "Level 2"

    coordinator.data["tmp"] = 25
    assert entity.hvac_action == HVACAction.IDLE

    asyncio.run(entity.async_set_preset_mode("Level 5"))
    assert coordinator.last_level == 5
    assert coordinator.commands == ["B5"]

    asyncio.run(entity.async_turn_off())
    asyncio.run(entity.async_turn_on())
    assert coordinator.commands[-2:] == ["B0", "B5"]

    asyncio.run(entity.async_set_hvac_mode(HVACMode.OFF))
    asyncio.run(entity.async_set_hvac_mode(HVACMode.HEAT))
    assert coordinator.commands[-2:] == ["B0", "B5"]


def test_timer_value_conversion_and_commands() -> None:
    coordinator = FakeCoordinator()
    timer = LuxevaTimer(coordinator)

    coordinator.data["tmr"] = "01:01"
    assert timer.native_value == 2

    coordinator.data["tmr"] = "09:59"
    assert timer.native_value == 9

    coordinator.data["tmr"] = "invalid"
    assert timer.native_value == 0

    coordinator.data.update(prg=0, tmr="00:00")
    asyncio.run(timer.async_set_native_value(2))
    assert coordinator.commands == ["B3", "T2"]

    coordinator.commands.clear()
    coordinator.data["prg"] = 2
    asyncio.run(timer.async_set_native_value(2))
    assert coordinator.commands == ["T2"]

    coordinator.commands.clear()
    asyncio.run(timer.async_set_native_value(0))
    assert coordinator.commands == ["T0", "B0"]


def test_sensor_values() -> None:
    coordinator = FakeCoordinator()
    thermostat = LuxevaThermostatSensor(coordinator)
    remaining = LuxevaTimerSensor(coordinator)

    assert thermostat.native_value == "Disabled"
    coordinator.data["hts"] = 23
    assert thermostat.native_value == "23 °C"

    coordinator.data["tmr"] = "02:15"
    assert remaining.native_value == 135
    coordinator.data["tmr"] = "invalid"
    assert remaining.native_value == 0


def test_actuator_commands_and_external_turn_on(monkeypatch) -> None:
    coordinator = FakeCoordinator()
    actuator = LuxevaActuatorSwitch(coordinator)
    monkeypatch.setattr(
        LuxevaActuatorSwitch,
        "async_write_ha_state",
        lambda self: None,
    )

    assert actuator.is_on is False
    asyncio.run(actuator.async_turn_on())
    assert coordinator.commands == ["B3", "T1"]

    # Confirmation of our own turn-on must not arm a second timer.
    coordinator.data.update(prg=3, tmr="00:59")
    actuator._handle_update()
    assert coordinator.commands == ["B3", "T1"]

    asyncio.run(actuator.async_turn_off())
    assert coordinator.commands[-2:] == ["T0", "B0"]

    # Fresh external off -> on transition without a timer gets a safety timer.
    external = FakeCoordinator()
    external_actuator = LuxevaActuatorSwitch(external)
    external.data.update(prg=4, tmr="00:00")
    external_actuator._handle_update()
    assert external.commands == ["T1"]

    # Repeated status updates while still on do not re-arm it.
    external_actuator._handle_update()
    assert external.commands == ["T1"]


def test_actuator_resets_transition_state_when_unavailable(monkeypatch) -> None:
    coordinator = FakeCoordinator()
    actuator = LuxevaActuatorSwitch(coordinator)
    monkeypatch.setattr(
        LuxevaActuatorSwitch,
        "async_write_ha_state",
        lambda self: None,
    )
    actuator._prev_prg = 4
    coordinator.data.update(available=False, prg=4)

    actuator._handle_update()

    assert actuator.available is False
    assert actuator._prev_prg == 0


def test_actuator_turn_on_while_already_on_keeps_safety_timer(monkeypatch) -> None:
    coordinator = FakeCoordinator()
    actuator = LuxevaActuatorSwitch(coordinator)
    monkeypatch.setattr(
        LuxevaActuatorSwitch,
        "async_write_ha_state",
        lambda self: None,
    )
    coordinator.data.update(prg=2, tmr="00:30")
    actuator._handle_update()

    # turn_on while the heater is already running produces no off -> on
    # transition to confirm it.
    asyncio.run(actuator.async_turn_on())
    coordinator.data.update(prg=2, tmr="01:00")
    actuator._handle_update()

    # Later external off -> on without a timer must still arm T1.
    coordinator.data.update(prg=0, tmr="00:00")
    actuator._handle_update()
    coordinator.commands.clear()
    coordinator.data.update(prg=3, tmr="00:00")
    actuator._handle_update()

    assert coordinator.commands == ["T1"]


def test_actuator_dropped_turn_on_keeps_safety_timer(monkeypatch) -> None:
    coordinator = FakeCoordinator()
    actuator = LuxevaActuatorSwitch(coordinator)
    monkeypatch.setattr(
        LuxevaActuatorSwitch,
        "async_write_ha_state",
        lambda self: None,
    )

    # turn_on whose commands never reach the device.
    asyncio.run(actuator.async_turn_on())
    coordinator.commands.clear()

    # External turn-on without a timer must still arm T1.
    coordinator.data.update(prg=3, tmr="00:00")
    actuator._handle_update()

    assert coordinator.commands == ["T1"]
