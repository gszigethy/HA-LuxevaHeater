"""Shared thermostat, session and emergency-stop policy (HA event loop only)."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta
import logging
import math
from typing import Any

from homeassistant.const import STATE_OFF, STATE_ON, UnitOfTemperature
from homeassistant.core import Event, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import (
    CONF_CONTROL_MODE,
    CONF_MIN_CYCLE,
    CONF_POWER_SWITCH,
    CONF_PROTECT_EXTERNAL,
    CONF_SENSOR,
    CONF_SENSOR_TIMEOUT,
    CONF_TOLERANCE,
    CONTROL_INTERVAL,
    DEFAULT_OPTIONS,
    DOMAIN,
    MODE_ACTUATOR,
    MODE_CLIMATE,
    MODE_COMPATIBILITY,
    RENEW_SECONDS,
    TIMER_ACK_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

# A hung disk must not hold back the upstream power-off request.
SAFETY_SAVE_TIMEOUT = 5


def timer_minutes(value: str) -> int:
    """Decode the device's whole-minute countdown."""
    hours, minutes = (int(part) for part in value.split(":"))
    return hours * 60 + minutes


class LuxevaControl:
    """One owner for a device, independent of which entities are enabled."""

    def __init__(self, coordinator, entry) -> None:
        self.coordinator = coordinator
        self.hass = coordinator.hass
        self.options = DEFAULT_OPTIONS | dict(entry.options)
        self.mode = self.options[CONF_CONTROL_MODE]
        self.sensor = self.options.get(CONF_SENSOR)
        self.power_switch = self.options.get(CONF_POWER_SWITCH)
        self.enabled = False
        self.target = 21.0  # Celsius, just like the heater's protocol
        self.deadline: datetime | None = None
        self.latched = False
        self.power_cut_status = "not_requested"
        self.problem: str | None = None
        self.demand = False
        self.session_finished = False
        self._timer_fault = False
        self._suspended = False
        self._last_toggle: datetime | None = None
        self._last_lease: datetime | None = None
        self._awaiting_timer: datetime | None = None
        self._timer_confirmed = False
        self._own_commands: deque[tuple[str, datetime]] = deque(maxlen=100)
        self._last_report: tuple[int, datetime] | None = None
        self._seen_status = False
        self._pending_stop = False
        self._last_stop: datetime | None = None
        self._unsubs: list[Callable[[], None]] = []
        self._store = Store(self.hass, 1, f"{DOMAIN}.{entry.entry_id}.control")
        self._safety_lock = asyncio.Lock()
        self._closing = False

    @property
    def managed(self) -> bool:
        return self.mode != MODE_COMPATIBILITY

    def snapshot(self) -> dict[str, Any]:
        """Persist intentions, never optimistic device state or sensor samples."""
        return {
            "mode": self.mode,
            "sensor": self.sensor,
            "enabled": self.enabled,
            "target": self.target,
            "level": self.coordinator.last_level,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "latched": self.latched,
            "pending_stop": self._pending_stop,
            "power_cut_status": self.power_cut_status,
            "session_finished": self.session_finished,
        }

    def _save(self) -> None:
        self._store.async_delay_save(self.snapshot, 1)

    async def async_start(self) -> None:
        saved = await self._store.async_load() or {}
        self.latched = bool(saved.get("latched", False))
        self.power_cut_status = saved.get("power_cut_status", "not_requested")
        self._pending_stop = bool(saved.get("pending_stop", False))
        self.session_finished = bool(saved.get("session_finished", False))
        target = saved.get("target", 21)
        self.target = (
            float(target)
            if isinstance(target, (int, float)) and math.isfinite(target)
            else 21
        )
        self.coordinator.last_level = max(1, min(6, int(saved.get("level", 1))))
        # Configuration changes cannot transfer a running session to a new owner/sensor.
        if saved.get("mode") == self.mode and saved.get("sensor") == self.sensor:
            self.enabled = bool(saved.get("enabled", False)) and not self.latched
            raw_deadline = saved.get("deadline")
            self.deadline = (
                dt_util.parse_datetime(raw_deadline) if raw_deadline else None
            )
            if self.deadline is not None and self.deadline.tzinfo is None:
                self.deadline = None
                self.enabled = False
                self._pending_stop = True
        elif saved:
            self._pending_stop = True
        self._unsubs.append(
            async_track_time_interval(
                self.hass, self._tick, timedelta(seconds=CONTROL_INTERVAL)
            )
        )
        entities = [entity for entity in (self.sensor, self.power_switch) if entity]
        if entities:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, entities, self._sensor_changed
                )
            )
        self._tick(dt_util.utcnow())

    async def async_close(self) -> None:
        self._closing = True
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await self._store.async_save(self.snapshot())

    @property
    def temperature(self) -> float | None:
        if not self.sensor:
            return None
        state = self.hass.states.get(self.sensor)
        if state is None or state.attributes.get("restored"):
            return None
        try:
            value = float(state.state)
            if not math.isfinite(value):
                return None
            unit = state.attributes.get("unit_of_measurement")
            if unit not in (
                UnitOfTemperature.CELSIUS,
                UnitOfTemperature.FAHRENHEIT,
                UnitOfTemperature.KELVIN,
            ):
                return None
            timeout = self.options[CONF_SENSOR_TIMEOUT]
            if (
                timeout
                and (dt_util.utcnow() - state.last_reported).total_seconds()
                > timeout * 60
            ):
                return None
            return TemperatureConverter.convert(value, unit, UnitOfTemperature.CELSIUS)
        except (ValueError, TypeError):
            return None

    @property
    def session_minutes(self) -> int:
        if self.deadline is None:
            return 0
        return max(
            0, math.ceil((self.deadline - dt_util.utcnow()).total_seconds() / 60)
        )

    @callback
    def _sensor_changed(self, event: Event) -> None:
        if event.data["entity_id"] == self.power_switch:
            state = self.hass.states.get(self.power_switch)
            if state and state.state == STATE_OFF:
                self.enabled = False
                self.demand = False
                self.deadline = None
                self._pending_stop = True
                self._save()
            if self.latched:
                self.power_cut_status = (
                    "confirmed_off"
                    if state and state.state == STATE_OFF
                    else "not_confirmed"
                )
        self._tick(dt_util.utcnow())

    @callback
    def note_command(self, command: str) -> None:
        """Remember our publications to ignore their broker echoes."""
        self._own_commands.append((command, dt_util.utcnow()))

    @callback
    def on_command(self, command: str) -> None:
        now = dt_util.utcnow()
        while (
            self._own_commands and (now - self._own_commands[0][1]).total_seconds() > 15
        ):
            self._own_commands.popleft()
        for item in list(self._own_commands):
            if item[0] == command:
                self._own_commands.remove(item)
                return
        if (
            self.managed
            and not self.latched
            and command.startswith("T")
            and command[1:].isdigit()
        ):
            hours = int(command[1:])
            if 0 <= hours <= 9:
                self.set_session(hours, external=True)

    @callback
    def on_status(self, previous: dict[str, Any]) -> None:
        now = dt_util.utcnow()
        data = self.coordinator.data
        minutes = timer_minutes(data["tmr"])
        if (previous.get("prg", 0) > 0) != (data["prg"] > 0):
            # A renewal fault belongs to the heating episode that failed. It
            # must not keep stopping later remote or app operation.
            self._timer_fault = False
        if previous.get("prg", 0) > 0 and data["prg"] == 0:
            self._timer_confirmed = False
            self._awaiting_timer = None
            self._last_lease = None
            self._last_toggle = now
        if data["prg"] > 0 and previous.get("prg") != data["prg"]:
            self._save()
        own_ack = self._awaiting_timer is not None
        if own_ack:
            # A T1 applied during a status gap has already counted down.
            elapsed = (now - self._awaiting_timer).total_seconds()
            # Zero never confirms: an expired interval protects nothing.
            if max(1, 59 - int(elapsed // 60)) <= minutes <= 60:
                self._timer_confirmed = True
                self._awaiting_timer = None
                if self.problem == "timer_unconfirmed":
                    self.problem = None
            elif (
                minutes > 60
                and self.managed
                and not self.latched
                and (self._last_report is None or minutes > self._last_report[0] + 1.5)
            ):
                # A physical long timer can race our pending T1. Adopt it once,
                # without extending the deadline on each unchanged status.
                self.set_session(
                    min(9, math.ceil(minutes / 60)), external=True, seconds=minutes * 60
                )
        elif self.managed and not self.latched:
            # IR changes have no command-topic publication. Detect jumps beyond
            # minute rounding; MQTT command observation also catches equal-value resets.
            if self._last_report:
                old_minutes, old_time = self._last_report
                expected = max(0, old_minutes - (now - old_time).total_seconds() / 60)
                if minutes > expected + 1.5:
                    self.set_session(
                        min(9, math.ceil(minutes / 60)),
                        external=True,
                        seconds=minutes * 60,
                    )
                elif minutes == 0 and old_minutes > 1 and data["prg"] > 0:
                    self.set_session(0, external=True)
            elif minutes > 60:
                self.set_session(
                    min(9, math.ceil(minutes / 60)), external=True, seconds=minutes * 60
                )
        self._last_report = (minutes, now)
        if (
            self.managed
            and not self.latched
            and not self._pending_stop
            and self.options[CONF_PROTECT_EXTERNAL]
            and data["prg"] > 0
        ):
            # Protect an external start with one bounded interval. This neither
            # enables HA regulation nor revives a finished user session.
            if previous.get("prg", 0) == 0 or not self._seen_status:
                if not own_ack and not self._timer_confirmed:
                    self._arm_lease(now)
        self._seen_status = True
        self._tick(now)

    def _arm_lease(self, now: datetime) -> None:
        if not self.coordinator.data["available"] or self.latched or self._timer_fault:
            return
        if self.coordinator.publish("T1"):
            self._last_lease = now
            self._awaiting_timer = now
            self._timer_confirmed = False

    def _stop_device(self, now: datetime) -> None:
        # Retry unconfirmed shutdowns at a bounded rate, including after reconnect.
        if not self.coordinator.data["available"]:
            self._pending_stop = True
            return
        if self._last_stop and (now - self._last_stop).total_seconds() < 5:
            return
        self._last_stop = now
        # B0 also clears the device timer. Never send T0 separately: if B0 were
        # lost, the heater would keep running without its fallback countdown.
        self.coordinator.publish("B0")
        self._awaiting_timer = None
        self._timer_confirmed = False
        self._last_lease = None
        self._last_toggle = now
        self._pending_stop = self.coordinator.data["prg"] > 0

    @callback
    def _tick(self, now: datetime) -> None:
        if self._closing:
            return
        data = self.coordinator.data
        if self.deadline and now >= self.deadline:
            self.enabled = False
            self.demand = False
            self.deadline = None
            self.session_finished = True
            self._pending_stop = True
            self._save()
        if self.latched or self._pending_stop:
            if data["available"]:
                if data["prg"] == 0 and self._seen_status:
                    self._pending_stop = False
                    self._save()
                else:
                    self._stop_device(now)
            self.coordinator._notify_listeners()
            return
        if not self.managed:
            return
        self.problem = None
        power = self.hass.states.get(self.power_switch) if self.power_switch else None
        if self.power_switch and (power is None or power.state != STATE_ON):
            self.problem = "power_unavailable"
        elif (
            # The room sensor only matters while HA regulates; it must not stop
            # heating started by the remote while the climate is off.
            self.mode == MODE_CLIMATE
            and self.sensor
            and self.enabled
            and self.temperature is None
        ):
            self.problem = "temperature_unavailable"
        elif not data["available"]:
            # Silence alone does not require shutdown: renewals stop and the
            # last applied device countdown remains the fallback. A pending
            # timer confirmation keeps its original deadline across the gap.
            self.problem = "device_unavailable"
            self.demand = False
            self.coordinator._notify_listeners()
            return
        elif self._timer_fault or (
            self._awaiting_timer
            and (now - self._awaiting_timer).total_seconds() >= TIMER_ACK_SECONDS
        ):
            if not self._timer_fault:
                _LOGGER.warning(
                    "Luxeva %s did not confirm its safety timer; stopping heating",
                    self.coordinator.mac,
                )
            self.problem = "timer_unconfirmed"
            self._timer_fault = True
            self._awaiting_timer = None
            self.enabled = False
            self._save()
        if self.problem:
            self.demand = False
            if data["prg"] > 0:
                self._stop_device(now)
            self.coordinator._notify_listeners()
            return
        if self.mode != MODE_CLIMATE or not self.enabled:
            self.coordinator._notify_listeners()
            return
        if self.sensor:
            temperature = self.temperature
            if temperature is None:
                return
            tolerance = self.options[CONF_TOLERANCE]
            if temperature <= self.target - tolerance:
                self.demand = True
            elif temperature >= self.target + tolerance:
                self.demand = False
        else:
            self.demand = True
        running = data["prg"] > 0
        if running != self.demand:
            elapsed = (
                (now - self._last_toggle).total_seconds()
                if self._last_toggle
                else math.inf
            )
            if elapsed >= self.options[CONF_MIN_CYCLE]:
                if self.demand:
                    if (
                        self._last_lease is None
                        or (now - self._last_lease).total_seconds() >= 5
                    ):
                        self.coordinator.publish("H0")
                        if self.coordinator.publish(f"B{self.coordinator.last_level}"):
                            self._arm_lease(now)
                            self._last_toggle = now
                else:
                    self._stop_device(now)
        elif running:
            if data.get("hts"):
                self.coordinator.publish("H0")
            if (
                self._last_lease is None
                or (now - self._last_lease).total_seconds() >= RENEW_SECONDS
            ):
                self._arm_lease(now)
        self.coordinator._notify_listeners()

    @property
    def suspended(self) -> bool:
        return self._suspended

    @callback
    def suspend(self) -> None:
        """Stop heating and refuse starts until this controller is replaced."""
        self._suspended = True
        self.turn_off()

    def _assert_start(self, source: str) -> None:
        if self._suspended:
            raise HomeAssistantError(
                "The heater is being reconfigured. Start it again once it reconnects, "
                "or reload the heater entry if this persists."
            )
        if self.latched:
            raise HomeAssistantError(
                "Safety shutdown is active. Restore power separately and reset the latch before heating."
            )
        if self._pending_stop:
            raise HomeAssistantError("Waiting for the heater to confirm shutdown.")
        if self.mode == MODE_CLIMATE and source == "actuator":
            raise HomeAssistantError(
                "The Luxeva climate owns heating. Select actuator control in Configure to use this switch."
            )
        if self.mode == MODE_ACTUATOR and source == "climate":
            raise HomeAssistantError(
                "The actuator owns heating. Use its thermostat or select Luxeva climate control in Configure."
            )
        if source == "actuator" and self.session_finished:
            raise HomeAssistantError(
                "The user countdown has ended. Clear or set a new session timer before restarting the actuator."
            )
        if not self.coordinator.data["available"]:
            raise HomeAssistantError("Waiting for fresh heater status.")
        if self.mode == MODE_CLIMATE and self.sensor and self.temperature is None:
            raise HomeAssistantError(
                "The configured room temperature sensor has no valid reading."
            )
        if self.power_switch:
            power = self.hass.states.get(self.power_switch)
            if power is None or power.state != STATE_ON:
                raise HomeAssistantError(
                    "The upstream power switch is not on. Restore power manually."
                )

    @callback
    def turn_on(self, source: str = "climate") -> None:
        self._assert_start(source)
        self._timer_fault = False
        self.session_finished = False
        self.enabled = True
        self._save()
        if self.mode == MODE_ACTUATOR:
            self.coordinator.publish("H0")
            self.coordinator.publish(f"B{self.coordinator.last_level}")
            self._arm_lease(dt_util.utcnow())
        else:
            self._tick(dt_util.utcnow())

    @callback
    def turn_off(self, source: str = "climate") -> None:
        self.enabled = False
        self.demand = False
        if source != "actuator":
            self.deadline = None
        self._pending_stop = True
        self._save()
        self._tick(dt_util.utcnow())

    @callback
    def set_target(self, temperature: float) -> None:
        if not math.isfinite(temperature) or not 5 <= temperature <= 35:
            raise HomeAssistantError("Choose a room target between 5 and 35 °C.")
        self.target = temperature
        self._save()
        self._tick(dt_util.utcnow())

    @callback
    def set_level(self, level: int) -> None:
        self.coordinator.last_level = level
        self._save()
        # During a pending stop, status still shows the old level; B<n> would
        # restart a heater whose B0 already cleared its countdown.
        if (
            not self.latched
            and not self._pending_stop
            and not self._suspended
            and self.coordinator.data["prg"] > 0
        ):
            self.coordinator.publish(f"B{level}")
        self.coordinator._notify_listeners()

    @callback
    def set_session(
        self, hours: int, *, external: bool = False, seconds: int | None = None
    ) -> None:
        if self.latched:
            if external:
                return
            raise HomeAssistantError("Safety shutdown is active.")
        now = dt_util.utcnow()
        self.session_finished = False
        self.deadline = (
            now + timedelta(seconds=seconds if seconds is not None else hours * 3600)
            if hours
            else None
        )
        self._save()
        if self.coordinator.data["prg"] > 0:
            # T0 cancels a user limit, not actuator protection. Never leave an
            # active managed heater without its device fallback countdown.
            self._arm_lease(now)
        self.coordinator._notify_listeners()

    async def _save_safety(self, timeout: float | None = None) -> bool:
        """A storage fault must never prevent the physical power-off attempt."""
        try:
            async with asyncio.timeout(timeout):
                await self._store.async_save(self.snapshot())
            return True
        except (HomeAssistantError, OSError, TimeoutError):
            _LOGGER.exception("Could not persist safety shutdown state")
            return False

    async def async_safety_shutdown(self) -> None:
        async with self._safety_lock:
            self.latched = True
            self.enabled = False
            self.demand = False
            self.deadline = None
            self._pending_stop = True
            self.power_cut_status = "requested"
            # Record the latch first when storage is healthy, but do not let a
            # disk failure prevent the independent upstream power-off action.
            persisted = await self._save_safety(SAFETY_SAVE_TIMEOUT)
            self.coordinator._notify_listeners()
            try:
                async with asyncio.timeout(10):
                    await self.hass.services.async_call(
                        "switch",
                        "turn_off",
                        {"entity_id": self.power_switch},
                        blocking=True,
                    )
                state = self.hass.states.get(self.power_switch)
                self.power_cut_status = (
                    "confirmed_off"
                    if state and state.state == STATE_OFF
                    else "not_confirmed"
                )
            except (HomeAssistantError, TimeoutError):
                self.power_cut_status = "failed"
                _LOGGER.exception("Upstream power-off request failed")
                raise HomeAssistantError(
                    "Power-off failed. The shutdown latch remains active; check the upstream switch."
                ) from None
            finally:
                self._stop_device(dt_util.utcnow())
                persisted = await self._save_safety(SAFETY_SAVE_TIMEOUT) and persisted
                self.coordinator._notify_listeners()
            if not persisted:
                raise HomeAssistantError(
                    "Power-off was requested, but the shutdown latch could not be saved. Check HA storage before restarting HA."
                )

    async def async_reset_safety(self) -> None:
        async with self._safety_lock:
            state = self.hass.states.get(self.power_switch)
            if state is None or state.state != STATE_OFF:
                raise HomeAssistantError(
                    "Confirm the upstream switch is off before resetting safety shutdown."
                )
            self.latched = False
            self.enabled = False
            self.demand = False
            self.deadline = None
            self.power_cut_status = "not_requested"
            if not await self._save_safety():
                self.latched = True
                self.coordinator._notify_listeners()
                raise HomeAssistantError(
                    "Could not save the reset. Safety shutdown remains active."
                )
            self.coordinator._notify_listeners()
