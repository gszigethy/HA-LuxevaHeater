"""Native Luxeva MQTT topics and push state over cloud or local brokers."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

import paho.mqtt.client as mqtt

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

from .const import (
    CONNECTION_LOCAL,
    DEFAULT_BROKER,
    DEFAULT_PORT,
    DOMAIN,
    TOPIC_IN,
    TOPIC_OUT,
)

_LOGGER = logging.getLogger(__name__)

# "Msg 1355268, Prg 0, Tmp 33, Hts 00, Tmr 00:00"
_STATUS_RE = re.compile(
    r"Msg\s+(\d+),\s*Prg\s+(\d+),\s*Tmp\s+(-?\d+),\s*Hts\s+(-?\d+),\s*Tmr\s+(\d{2}:\d{2})"
)

# Device publishes every ~2 s; 30 s without a message means it's unreachable.
AVAILABILITY_TIMEOUT = 30

# Typed config entry — platforms import this to avoid hass.data lookups.
type LuxevaConfigEntry = ConfigEntry["LuxevaCoordinator"]


def _make_mqtt_client(client_id: str) -> mqtt.Client:
    """Create a paho Client using the paho-mqtt 2.x callback API."""
    return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)


class LuxevaCoordinator:
    """Manage one heater connection without synthesizing device status."""

    def __init__(
        self,
        hass: HomeAssistant,
        mac: str,
        broker: str = DEFAULT_BROKER,
        port: int = DEFAULT_PORT,
    ) -> None:
        self.hass = hass
        self.mac = mac.upper()
        self.client_id = mac.replace(":", "").upper()
        self.device_name = f"Luxeva Heater {self.client_id}"
        self.broker = broker
        self.port = port

        self.control: Any = None
        self.username: str | None = None
        self.password: str | None = None
        self.connection = "cloud"
        self.issue_id: str | None = None

        self._client: mqtt.Client | None = None
        self._listeners: list[Callable[[], None]] = []
        self._availability_unsub: Callable[[], None] | None = None
        # Set once disconnect starts; late paho callbacks are dropped from then on.
        self._stopping = False

        # Last active heating level (1–6); shared across entities so the timer
        # can turn the heater on at the right level without knowing about climate.
        self.last_level: int = 1

        self.data: dict[str, Any] = {
            "available": False,
            "prg": 0,
            "tmp": None,
            "hts": None,
            "tmr": "00:00",
            "msg": None,
        }

    # ------------------------------------------------------------------
    # Topics
    # ------------------------------------------------------------------

    @property
    def out_topic(self) -> str:
        return TOPIC_OUT.format(mac=self.mac)

    @property
    def in_topic(self) -> str:
        return TOPIC_IN.format(mac=self.mac)

    # ------------------------------------------------------------------
    # Listener management
    # ------------------------------------------------------------------

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register a state-change listener; returns a removal callable."""
        self._listeners.append(listener)

        def _remove() -> None:
            try:
                self._listeners.remove(listener)
            except ValueError:
                pass

        return _remove

    @callback
    def _notify_listeners(self) -> None:
        """Call listeners. Must be called on the HA event loop."""
        for listener in list(self._listeners):
            listener()

    def _call_on_loop(self, func: Callable[..., None], *args: Any) -> None:
        """Schedule func on the HA event loop from paho's thread.

        Dropped once disconnect has started, and when the loop is already
        closed during Home Assistant shutdown.
        """
        if self._stopping:
            return
        try:
            self.hass.loop.call_soon_threadsafe(func, *args)
        except RuntimeError:
            _LOGGER.debug("Luxeva: event loop closed; dropping MQTT callback")

    # ------------------------------------------------------------------
    # Availability watchdog (all methods run on the HA event loop)
    # ------------------------------------------------------------------

    @callback
    def _arm_watchdog(self) -> None:
        """Reset the 30-second availability timer. Must be called on HA loop."""
        if self._availability_unsub is not None:
            self._availability_unsub()
        self._availability_unsub = async_call_later(
            self.hass, AVAILABILITY_TIMEOUT, self._watchdog_fired
        )

    @callback
    def _disarm_watchdog(self) -> None:
        """Cancel the availability timer. Must be called on HA loop."""
        if self._availability_unsub is not None:
            self._availability_unsub()
            self._availability_unsub = None

    @callback
    def _watchdog_fired(self, _now: Any) -> None:
        """No status message received for 30 s — mark device unavailable."""
        _LOGGER.warning(
            "Luxeva: no status message for %d s — marking unavailable",
            AVAILABILITY_TIMEOUT,
        )
        self._availability_unsub = None
        self.data["available"] = False
        self._notify_listeners()

    @callback
    def _set_unavailable(self) -> None:
        """Connection lost or refused. Must be called on HA loop."""
        # No point counting down when we know the connection is gone.
        self._disarm_watchdog()
        self.data["available"] = False
        self._notify_listeners()

    @callback
    def _handle_status(self, parsed: dict[str, Any]) -> None:
        """Apply a parsed status message. Must be called on HA loop."""
        if self._stopping:
            return
        previous = dict(self.data)
        self.data.update(parsed)
        self.data["available"] = True
        if parsed["prg"] > 0:
            self.last_level = parsed["prg"]
        self._arm_watchdog()
        if self.control is not None:
            self.control.on_status(previous)
        if self.issue_id and self.connection == CONNECTION_LOCAL:
            from homeassistant.helpers import issue_registry as ir

            ir.async_delete_issue(self.hass, DOMAIN, self.issue_id)
        self._notify_listeners()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_connect(self) -> None:
        """Start a reconnecting client without gating safety entities on MQTT."""
        await self.hass.async_add_executor_job(self._connect)

    def _connect(self) -> None:
        client = _make_mqtt_client(self.client_id)
        if self.username:
            client.username_pw_set(self.username, self.password)
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.on_disconnect = self._on_disconnect
        # Exponential back-off between reconnect attempts: 1 s → up to 30 s.
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        client.connect_timeout = 5
        # loop_start retries the first connection too. A dead broker must not
        # prevent the independent upstream power-cut controls loading at boot.
        client.connect_async(self.broker, self.port, keepalive=60)
        self._client = client
        client.loop_start()

    async def async_disconnect(self) -> None:
        """Disconnect from the MQTT broker and cancel the watchdog."""
        self._stopping = True
        self._disarm_watchdog()
        if self._client is not None:
            await self.hass.async_add_executor_job(self._disconnect)

    def _disconnect(self) -> None:
        if self._client is not None:
            # Send DISCONNECT while the network loop is still running.
            self._client.disconnect()
            self._client.loop_stop()
            self._client = None

    # ------------------------------------------------------------------
    # paho callbacks (run in paho's internal thread)
    #
    # These never touch coordinator state directly; every change is handed
    # to the HA event loop so entities never observe a half-applied update.
    # ------------------------------------------------------------------

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: Any,
        reason_code: Any,
        properties: Any,
    ) -> None:
        if not reason_code.is_failure:
            _LOGGER.debug("Luxeva: connected to %s:%s", self.broker, self.port)
            client.subscribe(self.out_topic)
            if self.control is not None and self.control.managed:
                client.subscribe(self.in_topic)
            # Stay unavailable until the first status message arrives;
            # a bare TCP connection without data doesn't prove the device is reachable.
        else:
            _LOGGER.warning("Luxeva: MQTT connect failed (%s)", reason_code)
            self._call_on_loop(self._set_unavailable)

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: Any,
        reason_code: Any,
        properties: Any,
    ) -> None:
        if self._stopping:
            _LOGGER.debug("Luxeva: disconnected (%s)", reason_code)
            return
        _LOGGER.warning(
            "Luxeva: disconnected (%s); paho will attempt reconnect", reason_code
        )
        self._call_on_loop(self._set_unavailable)

    def _on_message(
        self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage
    ) -> None:
        try:
            payload = msg.payload.decode("utf-8").strip()
            _LOGGER.debug("Luxeva outTopic: %s", payload)
            if getattr(msg, "retain", False):
                return
            if getattr(msg, "topic", self.out_topic) == self.in_topic:
                if self.control is not None:
                    self._call_on_loop(self.control.on_command, payload)
                return
            parsed = _parse_status(payload)
            if parsed:
                self._call_on_loop(self._handle_status, parsed)
            else:
                _LOGGER.warning("Luxeva: unrecognised message format: %s", payload)
        except Exception as exc:
            _LOGGER.error("Luxeva: error processing message: %s", exc)

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    def publish(self, command: str) -> bool:
        """Publish a command to inTopic. Must be called from the HA event loop."""
        if self.control is not None and (
            (self.control.latched and command not in ("B0", "T0", "H0"))
            # A heater being reconfigured may stop, but must not start a level.
            or (
                getattr(self.control, "suspended", False)
                and command.startswith("B")
                and command != "B0"
            )
        ):
            return False
        if self._stopping or self._client is None or not self._client.is_connected():
            _LOGGER.warning("Luxeva: cannot publish '%s' — not connected", command)
            return False
        result = self._client.publish(self.in_topic, command)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            _LOGGER.error(
                "Luxeva: publish failed (rc=%d) for command '%s'", result.rc, command
            )
            return False
        if self.control is not None:
            self.control.note_command(command)
        _LOGGER.debug("Luxeva inTopic: %s", command)
        return True


def _parse_status(message: str) -> dict[str, Any] | None:
    """Parse a Luxeva status string into a data dict."""
    match = _STATUS_RE.fullmatch(message)
    if not match:
        return None
    if not 0 <= int(match.group(2)) <= 6 or int(match.group(5).split(":")[1]) > 59:
        return None
    return {
        "msg": int(match.group(1)),
        "prg": int(match.group(2)),
        "tmp": int(match.group(3)),
        "hts": int(match.group(4)),
        "tmr": match.group(5),
    }
