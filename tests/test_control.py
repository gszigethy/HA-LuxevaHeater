"""Policy tests with controlled time, temperature, transport and persistent storage."""

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from homeassistant.exceptions import HomeAssistantError
import pytest

from custom_components.luxeva_heater import control as module
from custom_components.luxeva_heater.const import (
    CONF_CONTROL_MODE,
    CONF_MIN_CYCLE,
    CONF_POWER_SWITCH,
    CONF_SENSOR,
    CONF_SENSOR_TIMEOUT,
    MODE_ACTUATOR,
    MODE_CLIMATE,
    MODE_COMPATIBILITY,
)


class MemoryStore:
    saved = None

    def __init__(self, *args):
        self.data = deepcopy(type(self).saved)

    async def async_load(self):
        return self.data

    async def async_save(self, data):
        self.data = deepcopy(data)
        type(self).saved = deepcopy(data)

    def async_delay_save(self, callback, delay):
        self.data = deepcopy(callback())
        type(self).saved = deepcopy(self.data)


class Rig:
    def __init__(
        self, monkeypatch, mode=MODE_CLIMATE, sensor=True, power=False, **options
    ):
        self.now = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
        monkeypatch.setattr(module.dt_util, "utcnow", lambda: self.now)
        self.states = {}
        self.hass = SimpleNamespace(
            states=SimpleNamespace(get=self.states.get),
            services=SimpleNamespace(async_call=AsyncMock()),
        )
        self.commands = []
        self.notifications = 0
        self.coordinator = SimpleNamespace(
            hass=self.hass,
            mac="00:AA:11:BB:22:CC",
            data={"available": True, "prg": 0, "tmp": 36, "hts": 0, "tmr": "00:00"},
            last_level=2,
            publish=self.publish,
            _notify_listeners=self.notify,
        )
        values = {CONF_CONTROL_MODE: mode, CONF_MIN_CYCLE: 0} | options
        if sensor:
            values[CONF_SENSOR] = "sensor.room"
            self.temperature(18)
        if power:
            values[CONF_POWER_SWITCH] = "switch.plug"
            self.power("on")
        self.entry = SimpleNamespace(options=values, entry_id="heater")
        self.control = module.LuxevaControl(self.coordinator, self.entry)

    def publish(self, command):
        if self.control.latched and command not in ("B0", "T0", "H0"):
            return False
        self.commands.append(command)
        self.control.note_command(command)
        return True

    def notify(self):
        self.notifications += 1

    def temperature(self, value, unit="°C", age=0):
        self.states["sensor.room"] = SimpleNamespace(
            state=str(value),
            attributes={"unit_of_measurement": unit},
            last_reported=self.now - timedelta(minutes=age),
        )

    def power(self, value):
        self.states["switch.plug"] = SimpleNamespace(state=value)

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)
        self.control._tick(self.now)

    def report(self, **values):
        previous = dict(self.coordinator.data)
        self.coordinator.data.update(values)
        self.control.on_status(previous)


@pytest.fixture(autouse=True)
def storage(monkeypatch):
    MemoryStore.saved = None
    monkeypatch.setattr(module, "Store", MemoryStore)
    monkeypatch.setattr(module, "async_track_time_interval", lambda *args: lambda: None)
    monkeypatch.setattr(
        module, "async_track_state_change_event", lambda *args: lambda: None
    )


def test_thermostat_cycles_and_renews_only_with_valid_sensor(monkeypatch):
    r = Rig(monkeypatch)
    r.control.turn_on()
    assert r.commands == ["H0", "B2", "T1"]
    r.report(prg=2, tmr="00:59")
    r.commands.clear()
    r.advance(600)
    assert r.commands == ["T1"]
    r.report(tmr="00:59")
    r.temperature(22)
    r.advance(5)
    assert r.commands[-1] == "B0"
    r.report(prg=0, tmr="00:00")
    assert r.control.enabled  # idle is not HVAC off
    r.temperature(18)
    r.advance(5)
    assert r.commands[-3:] == ["H0", "B2", "T1"]
    r.report(prg=2, tmr="00:59")
    r.temperature("unavailable")
    r.advance(5)
    assert r.commands[-1] == "B0"
    assert r.control.problem == "temperature_unavailable"
    r.commands.clear()
    r.advance(600)
    assert "T1" not in r.commands


def test_sensor_conversion_nonfinite_and_freshness(monkeypatch):
    r = Rig(monkeypatch, **{CONF_SENSOR_TIMEOUT: 10})
    r.temperature(68, "°F")
    assert r.control.temperature == 20
    r.temperature(20, age=11)
    assert r.control.temperature is None
    for bad in ("nan", "inf", "unknown", "unavailable"):
        r.temperature(bad)
        assert r.control.temperature is None
    r.temperature(20, unit="W")
    assert r.control.temperature is None
    with pytest.raises(HomeAssistantError):
        r.control.turn_on()


def test_hysteresis_and_minimum_cycle(monkeypatch):
    r = Rig(monkeypatch, **{CONF_MIN_CYCLE: 300})
    r.control.turn_on()
    r.report(prg=2, tmr="00:59")
    r.commands.clear()
    r.temperature(21.1)
    r.advance(5)
    assert not r.commands
    r.temperature(22)
    r.advance(5)
    assert not r.commands
    r.advance(290)
    assert r.commands == ["B0"]


def test_no_sensor_manual_mode_still_has_safety_timer(monkeypatch):
    r = Rig(monkeypatch, sensor=False)
    r.control.turn_on()
    assert r.commands == ["H0", "B2", "T1"]
    r.report(prg=2, tmr="00:59")
    r.advance(600)
    assert r.commands[-1] == "T1"


def test_missing_timer_ack_stops_and_requires_new_start(monkeypatch):
    r = Rig(monkeypatch)
    r.control.turn_on()
    r.report(prg=2, tmr="00:00")
    r.advance(16)
    assert r.control.problem == "timer_unconfirmed"
    assert r.control.enabled is False
    assert r.commands[-1] == "B0"
    r.report(prg=0, tmr="00:00")
    r.commands.clear()
    r.advance(600)
    assert not r.commands


def test_session_deadline_survives_cycles_and_expires(monkeypatch):
    r = Rig(monkeypatch)
    r.control.set_session(3)
    deadline = r.control.deadline
    r.control.turn_on()
    r.report(prg=2, tmr="00:59")
    assert "T3" not in r.commands
    r.temperature(22)
    r.advance(5)
    r.report(prg=0, tmr="00:00")
    assert r.control.deadline == deadline
    r.temperature(18)
    r.advance(5)
    r.report(prg=2, tmr="00:59")
    r.advance(10800)
    assert r.control.deadline is None
    assert r.control.enabled is False
    assert r.control.session_finished
    assert r.commands[-1] == "B0"


def test_session_cancellation_keeps_heat_and_protection(monkeypatch):
    r = Rig(monkeypatch)
    r.control.turn_on()
    r.report(prg=2, tmr="00:59")
    r.control.set_session(3)
    r.commands.clear()
    r.control.set_session(0)
    assert r.control.deadline is None
    assert r.control.enabled
    assert r.commands == ["T1"]


def test_command_echo_does_not_create_session_but_external_same_value_does(monkeypatch):
    r = Rig(monkeypatch)
    r.control.turn_on()
    r.control.on_command("T1")
    assert r.control.deadline is None
    r.control.on_command("T1")
    assert r.control.session_minutes == 60
    r.control.on_command("T3")
    assert r.control.session_minutes == 180
    assert "T3" not in r.commands


def test_ir_long_timer_becomes_bounded_session(monkeypatch):
    r = Rig(monkeypatch)
    r.control.turn_on()
    r.report(prg=2, tmr="00:59")
    r.commands.clear()
    r.report(tmr="02:59")
    assert r.control.session_minutes == 179
    assert r.commands == ["T1"]


def test_actuator_does_not_renew_and_blocks_wrong_controller(monkeypatch):
    r = Rig(monkeypatch, mode=MODE_ACTUATOR)
    with pytest.raises(HomeAssistantError, match="actuator owns"):
        r.control.turn_on("climate")
    r.control.turn_on("actuator")
    r.report(prg=2, tmr="00:59")
    r.commands.clear()
    r.advance(600)
    assert not r.commands
    r.report(prg=0, tmr="00:00")
    assert not r.commands
    r.control.turn_on("actuator")
    assert r.commands[-1] == "T1"
    other = Rig(monkeypatch)
    with pytest.raises(HomeAssistantError, match="climate owns"):
        other.control.turn_on("actuator")


def test_user_session_expiry_cannot_be_overridden_by_generic_thermostat(monkeypatch):
    r = Rig(monkeypatch, mode=MODE_ACTUATOR)
    r.control.set_session(2)
    r.control.turn_on("actuator")
    r.report(prg=2, tmr="00:59")
    r.advance(7201)
    r.report(prg=0, tmr="00:00")
    with pytest.raises(HomeAssistantError, match="countdown has ended"):
        r.control.turn_on("actuator")
    r.control.set_session(0)
    r.control.turn_on("actuator")


def test_restart_waits_for_both_inputs_and_honours_expired_session(monkeypatch):
    r = Rig(monkeypatch)
    r.control.set_session(3)
    r.control.turn_on()
    saved = r.control.snapshot()
    r.coordinator.data["available"] = False
    restored = module.LuxevaControl(r.coordinator, r.entry)
    r.control = restored
    MemoryStore.saved = saved
    r.commands.clear()
    asyncio.run(restored.async_start())
    assert restored.enabled
    assert not r.commands
    r.temperature("unavailable")
    r.report(available=True)
    assert not r.commands
    r.temperature(18)
    r.advance(5)
    assert r.commands[-1] == "T1"
    assert restored.deadline.isoformat() == saved["deadline"]
    # Expired while HA was stopped: no heating restart is permitted.
    r.now += timedelta(hours=4)
    MemoryStore.saved = saved
    newer = module.LuxevaControl(r.coordinator, r.entry)
    r.control = newer
    r.commands.clear()
    asyncio.run(newer.async_start())
    assert not newer.enabled
    assert newer.session_finished
    assert "B2" not in r.commands


def test_configuration_change_does_not_restore_heating(monkeypatch):
    r = Rig(monkeypatch)
    r.control.turn_on()
    saved = r.control.snapshot()
    saved["sensor"] = "sensor.old_room"
    MemoryStore.saved = saved
    changed = module.LuxevaControl(r.coordinator, r.entry)
    asyncio.run(changed.async_start())
    assert not changed.enabled


def test_safety_shutdown_persists_blocks_starts_and_never_restores_power(monkeypatch):
    r = Rig(monkeypatch, power=True)
    r.control.turn_on()
    r.report(prg=2, tmr="00:59")

    async def cut(*args, **kwargs):
        assert r.control.latched
        assert MemoryStore.saved["latched"]
        r.power("off")

    r.hass.services.async_call.side_effect = cut
    asyncio.run(r.control.async_safety_shutdown())
    assert r.control.power_cut_status == "confirmed_off"
    assert not r.control.enabled
    assert MemoryStore.saved["latched"]
    with pytest.raises(HomeAssistantError, match="Safety shutdown"):
        r.control.turn_on()
    restored = module.LuxevaControl(r.coordinator, r.entry)
    asyncio.run(restored.async_start())
    assert restored.latched
    asyncio.run(r.control.async_reset_safety())
    assert not r.control.latched
    assert not r.control.enabled
    r.hass.services.async_call.assert_called_once_with(
        "switch", "turn_off", {"entity_id": "switch.plug"}, blocking=True
    )


def test_power_cut_failure_remains_latched_and_reset_requires_off(monkeypatch):
    r = Rig(monkeypatch, power=True)
    r.hass.services.async_call.side_effect = HomeAssistantError("offline")
    with pytest.raises(HomeAssistantError, match="Power-off failed"):
        asyncio.run(r.control.async_safety_shutdown())
    assert r.control.latched
    assert r.control.power_cut_status == "failed"
    with pytest.raises(HomeAssistantError, match="switch is off"):
        asyncio.run(r.control.async_reset_safety())


def test_latch_blocks_remote_adoption_and_session_changes(monkeypatch):
    r = Rig(monkeypatch, sensor=False)
    r.control.latched = True
    r.control.on_command("T9")
    r.report(prg=2, tmr="08:59")
    assert not r.control.enabled
    assert r.control.deadline is None
    assert not any(command in ("B2", "T1") for command in r.commands)


def test_compatibility_controller_is_passive(monkeypatch):
    r = Rig(monkeypatch, mode=MODE_COMPATIBILITY)
    r.control.on_command("T9")
    r.report(prg=2, tmr="08:59")
    r.advance(600)
    assert not r.commands
    assert r.control.deadline is None


def test_managed_entities_share_policy_and_keep_original_unique_ids(monkeypatch):
    from custom_components.luxeva_heater.climate import LuxevaClimate
    from custom_components.luxeva_heater.number import LuxevaTimer
    from custom_components.luxeva_heater.switch import LuxevaActuatorSwitch
    from custom_components.luxeva_heater.sensor import (
        LuxevaInternalTemperature,
        LuxevaSessionSensor,
    )
    from custom_components.luxeva_heater.button import LuxevaSafetyButton
    from custom_components.luxeva_heater.binary_sensor import LuxevaSafetySensor
    from homeassistant.components.climate import (
        ClimateEntityFeature,
        HVACMode,
        HVACAction,
    )

    r = Rig(monkeypatch, power=True)
    r.coordinator.client_id = "00AA11BB22CC"
    r.coordinator.device_name = "Luxeva Heater 00AA11BB22CC"
    r.coordinator.control = r.control
    climate = LuxevaClimate(r.coordinator)
    timer = LuxevaTimer(r.coordinator)
    actuator = LuxevaActuatorSwitch(r.coordinator)
    assert climate.unique_id == "00AA11BB22CC_climate"
    assert timer.unique_id == "00AA11BB22CC_timer"
    assert actuator.unique_id == "00AA11BB22CC_actuator"
    assert climate.supported_features & ClimateEntityFeature.TARGET_TEMPERATURE
    assert climate.current_temperature == 18
    assert climate.target_temperature == 21
    asyncio.run(climate.async_set_temperature(temperature=23))
    assert climate.target_temperature == 23
    asyncio.run(climate.async_turn_on())
    assert climate.hvac_mode == HVACMode.HEAT
    assert climate.hvac_action == HVACAction.IDLE
    r.report(prg=2, tmr="00:59")
    assert climate.hvac_action == HVACAction.HEATING
    asyncio.run(climate.async_set_preset_mode("Level 4"))
    assert climate.preset_mode == "Level 4"
    assert r.commands[-1] == "B4"
    asyncio.run(timer.async_set_native_value(3))
    assert timer.native_value == 3
    assert LuxevaSessionSensor(r.coordinator).native_value == 180
    assert LuxevaInternalTemperature(r.coordinator).native_value == 36
    assert climate.extra_state_attributes["session_ends_at"]
    with pytest.raises(HomeAssistantError):
        asyncio.run(actuator.async_turn_on())
    shutdown = LuxevaSafetyButton(r.coordinator, False)
    reset = LuxevaSafetyButton(r.coordinator, True)
    indicator = LuxevaSafetySensor(r.coordinator)
    r.hass.services.async_call.side_effect = lambda *args, **kwargs: r.power("off")
    asyncio.run(shutdown.async_press())
    assert indicator.is_on
    assert indicator.extra_state_attributes["power_cut_status"] == "confirmed_off"
    asyncio.run(reset.async_press())
    assert not indicator.is_on
    asyncio.run(climate.async_turn_off())
    assert climate.hvac_mode == HVACMode.OFF


def test_unavailable_upstream_power_prevents_new_heating(monkeypatch):
    r = Rig(monkeypatch, power=True)
    r.power("unavailable")
    with pytest.raises(HomeAssistantError, match="upstream power"):
        r.control.turn_on()
    r.control._tick(r.now)
    assert r.control.problem == "power_unavailable"


def test_external_power_off_cancels_session_and_does_not_restart_on_restore(
    monkeypatch,
):
    r = Rig(monkeypatch, power=True)
    r.control.turn_on()
    r.control.set_session(3)
    r.power("off")
    r.control._sensor_changed(SimpleNamespace(data={"entity_id": "switch.plug"}))
    assert not r.control.enabled
    assert r.control.deadline is None
    r.power("on")
    r.control._sensor_changed(SimpleNamespace(data={"entity_id": "switch.plug"}))
    assert not r.control.enabled


def test_storage_failure_does_not_prevent_power_cut(monkeypatch):
    r = Rig(monkeypatch, power=True)
    r.control._store.async_save = AsyncMock(side_effect=OSError("disk full"))
    with pytest.raises(HomeAssistantError, match="could not be saved"):
        asyncio.run(r.control.async_safety_shutdown())
    r.hass.services.async_call.assert_awaited_once()
    assert r.control.latched


def test_reset_storage_failure_keeps_latch(monkeypatch):
    r = Rig(monkeypatch, power=True)
    r.control.latched = True
    r.power("off")
    r.control._store.async_save = AsyncMock(side_effect=OSError("disk full"))
    with pytest.raises(HomeAssistantError, match="remains active"):
        asyncio.run(r.control.async_reset_safety())
    assert r.control.latched


def test_actuator_thermostat_cycles_preserve_user_deadline(monkeypatch):
    r = Rig(monkeypatch, mode=MODE_ACTUATOR)
    r.control.set_session(3)
    deadline = r.control.deadline
    r.control.turn_on("actuator")
    r.report(prg=2, tmr="00:59")
    r.control.turn_off("actuator")
    r.report(prg=0, tmr="00:00")
    assert r.control.deadline == deadline
    r.control.turn_on("actuator")
    assert r.control.deadline == deadline


def test_later_remote_start_gets_a_new_safety_interval(monkeypatch):
    r = Rig(monkeypatch, mode=MODE_ACTUATOR)
    r.control.turn_on("actuator")
    r.report(prg=2, tmr="00:59")
    assert r.control._timer_confirmed
    r.report(prg=0, tmr="00:00")
    r.commands.clear()
    r.report(prg=2, tmr="00:00")
    assert r.commands == ["T1"]


def test_ir_long_timer_racing_renewal_is_adopted_once(monkeypatch):
    r = Rig(monkeypatch)
    r.control.turn_on()
    r.report(prg=2, tmr="02:59")
    deadline = r.control.deadline
    assert r.control.session_minutes == 179
    r.now += timedelta(seconds=2)
    r.report(tmr="02:59")
    assert r.control.deadline == deadline


def test_command_observation_cannot_renew_without_fresh_device_status(monkeypatch):
    r = Rig(monkeypatch)
    r.coordinator.data.update(available=False, prg=2)
    r.control.on_command("T3")
    assert r.control.session_minutes == 180
    assert not r.commands


def advance_ticks(r, seconds):
    for _ in range(seconds // 5):
        r.advance(5)


def test_remote_start_after_session_expiry_gets_one_safety_interval(monkeypatch):
    r = Rig(monkeypatch)
    r.control.set_session(1)
    r.control.turn_on()
    r.report(prg=2, tmr="00:59")
    r.advance(3600)
    r.report(prg=0, tmr="00:00")
    r.advance(5)
    r.commands.clear()
    r.report(prg=3, tmr="00:00")
    assert r.commands == ["T1"]
    r.report(tmr="00:59")
    advance_ticks(r, 3600)
    assert r.commands == ["T1"]
    assert not r.control.enabled
    assert r.control.session_finished


def test_actuator_remote_start_after_session_expiry_is_protected(monkeypatch):
    r = Rig(monkeypatch, mode=MODE_ACTUATOR, sensor=False)
    r.control.set_session(1)
    r.control.turn_on("actuator")
    r.report(prg=2, tmr="00:59")
    r.advance(3600)
    r.report(prg=0, tmr="00:00")
    r.advance(5)
    r.commands.clear()
    r.report(prg=3, tmr="00:00")
    assert r.commands == ["T1"]
    with pytest.raises(HomeAssistantError, match="countdown has ended"):
        r.control.turn_on("actuator")


def test_sensorless_remote_start_gets_one_hour_without_adoption(monkeypatch):
    r = Rig(monkeypatch, sensor=False)
    r.report(prg=2, tmr="00:00")
    assert r.commands == ["T1"]
    assert not r.control.enabled
    r.report(tmr="00:59")
    advance_ticks(r, 1800)
    assert r.commands == ["T1"]


def test_stale_timer_fault_does_not_lock_out_the_remote(monkeypatch):
    r = Rig(monkeypatch)
    r.control.turn_on()
    r.report(prg=2, tmr="00:00")
    r.advance(16)
    assert r.control.problem == "timer_unconfirmed"
    r.report(prg=0, tmr="00:00")
    r.advance(5)
    r.commands.clear()
    r.report(prg=1, tmr="00:00")
    r.advance(5)
    assert r.commands == ["T1"]
    r.report(tmr="00:59")
    advance_ticks(r, 60)
    assert r.commands == ["T1"]
    assert not r.control.enabled


def test_fault_without_device_start_does_not_lock_out_the_remote(monkeypatch):
    r = Rig(monkeypatch)
    r.control.turn_on()  # the heater never leaves standby
    r.advance(16)
    assert r.control.problem == "timer_unconfirmed"
    r.report(prg=0, tmr="00:00")
    r.commands.clear()
    r.report(prg=1, tmr="00:00")
    r.advance(5)
    assert r.commands == ["T1"]


def test_unprotected_remote_start_is_left_alone_after_a_fault(monkeypatch):
    r = Rig(monkeypatch, protect_external_starts=False)
    r.control.turn_on()
    r.report(prg=2, tmr="00:00")
    r.advance(16)
    r.report(prg=0, tmr="00:00")
    r.advance(5)
    r.commands.clear()
    r.report(prg=1, tmr="00:00")
    advance_ticks(r, 60)
    assert r.commands == []


def test_status_gap_stops_renewal_without_forcing_shutdown(monkeypatch):
    r = Rig(monkeypatch, sensor=False)
    r.control.turn_on()
    r.report(prg=2, tmr="00:59")
    r.commands.clear()
    r.coordinator.data["available"] = False
    r.advance(600)
    r.advance(5)
    assert r.commands == []
    assert r.control.problem == "device_unavailable"
    r.report(available=True, prg=2, tmr="00:49")
    r.advance(5)
    assert r.commands == ["T1"]
    assert r.control.enabled


def test_timer_applied_during_status_gap_is_confirmed_on_recovery(monkeypatch):
    r = Rig(monkeypatch, mode=MODE_ACTUATOR, sensor=False)
    r.control.turn_on("actuator")
    r.commands.clear()
    r.coordinator.data["available"] = False
    r.advance(60)
    r.report(available=True, prg=2, tmr="00:58")
    r.advance(5)
    assert r.commands == []
    assert r.control.problem is None


def test_reconnects_cannot_postpone_an_unconfirmed_timer(monkeypatch):
    r = Rig(monkeypatch, sensor=False)
    r.control.turn_on()
    for _ in range(12):
        r.report(available=True, prg=2, tmr="00:00")
        r.advance(5)
        r.coordinator.data["available"] = False
        r.advance(5)
    assert "B0" in r.commands
    assert r.control.problem == "timer_unconfirmed"
    assert not r.control.enabled


def test_suspended_controller_rejects_starts_and_persists_off(monkeypatch):
    r = Rig(monkeypatch, mode=MODE_ACTUATOR, sensor=False)
    r.control.turn_on("actuator")
    r.report(prg=2, tmr="00:59")
    r.control.suspend()
    assert r.commands[-1] == "B0"
    r.report(prg=0, tmr="00:00")
    r.advance(5)
    with pytest.raises(HomeAssistantError, match="reconfigured"):
        r.control.turn_on("actuator")
    assert MemoryStore.saved["enabled"] is False


def test_stop_keeps_the_device_countdown(monkeypatch):
    r = Rig(monkeypatch, sensor=False)
    r.control.turn_on()
    r.report(prg=2, tmr="00:59")
    r.commands.clear()
    r.control.turn_off()
    assert r.commands == ["B0"]
    r.advance(5)
    assert r.commands == ["B0", "B0"]


def test_hung_storage_does_not_delay_power_cut(monkeypatch):
    r = Rig(monkeypatch, power=True)
    monkeypatch.setattr(module, "SAFETY_SAVE_TIMEOUT", 0.01)

    async def hang(_data):
        await asyncio.Event().wait()

    r.control._store.async_save = hang
    with pytest.raises(HomeAssistantError, match="could not be saved"):
        asyncio.run(r.control.async_safety_shutdown())
    r.hass.services.async_call.assert_awaited_once()
    assert r.control.latched


def test_ack_window_never_accepts_an_expired_interval(monkeypatch):
    r = Rig(monkeypatch, mode=MODE_ACTUATOR, sensor=False)
    r.control.turn_on("actuator")
    r.coordinator.data["available"] = False
    r.advance(3600)
    r.report(available=True, prg=2, tmr="00:00")
    r.advance(5)
    assert r.commands[-1] == "B0"
    assert r.control.problem == "timer_unconfirmed"


def test_level_change_cannot_restart_a_stopping_heater(monkeypatch):
    r = Rig(monkeypatch, sensor=False)
    r.control.turn_on()
    r.report(prg=2, tmr="00:59")
    r.control.turn_off()
    r.commands.clear()
    r.control.set_level(4)  # status still reports Prg 2 until B0 is confirmed
    assert r.commands == []
    assert r.coordinator.last_level == 4


def test_suspended_flag_is_exposed_for_the_transport(monkeypatch):
    r = Rig(monkeypatch)
    assert r.control.suspended is False
    r.control.suspend()
    assert r.control.suspended is True


def test_silent_sensor_is_rejected_by_default(monkeypatch):
    # A sensor that keeps showing its last value but stops reporting must not
    # regulate the heater indefinitely; the default limit is 60 minutes.
    r = Rig(monkeypatch)
    r.temperature(18, age=59)
    assert r.control.temperature == 18
    r.temperature(18, age=61)
    assert r.control.temperature is None


def test_stale_sensor_does_not_stop_a_remote_start_while_climate_is_off(monkeypatch):
    r = Rig(monkeypatch)
    r.temperature(18, age=120)  # not regulating, so the room sensor is irrelevant
    r.report(prg=2, tmr="00:00")
    r.advance(5)
    assert r.commands == ["T1"]
    assert r.control.problem is None


def test_stale_sensor_stops_regulated_heating(monkeypatch):
    r = Rig(monkeypatch)
    r.control.turn_on()
    r.report(prg=2, tmr="00:59")
    r.temperature(18, age=61)
    r.advance(5)
    assert r.commands[-1] == "B0"
    assert r.control.problem == "temperature_unavailable"
