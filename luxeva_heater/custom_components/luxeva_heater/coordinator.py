"""MQTT coordinator for Luxeva Heater — connects to the Luxeva cloud broker."""
from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

import paho.mqtt.client as mqtt

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

from .const import DEFAULT_BROKER, DEFAULT_PORT, TOPIC_IN, TOPIC_OUT

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
    """Create a paho Client compatible with both paho-mqtt 1.x and 2.x."""
    try:
        from paho.mqtt.client import CallbackAPIVersion  # type: ignore[attr-defined]
        return mqtt.Client(CallbackAPIVersion.VERSION1, client_id=client_id)
    except (ImportError, AttributeError):
        return mqtt.Client(client_id=client_id)


class LuxevaCoordinator:
    """Manages the persistent MQTT connection to the Luxeva cloud broker."""

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
        self.broker = broker
        self.port = port

        self._client: mqtt.Client | None = None
        self._listeners: list[Callable[[], None]] = []
        self._availability_unsub: Callable[[], None] | None = None

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

    def _notify_listeners(self) -> None:
        """Thread-safe: schedule listener calls on the HA event loop (paho thread → HA loop)."""
        for listener in list(self._listeners):
            self.hass.loop.call_soon_threadsafe(listener)

    def _notify_listeners_on_loop(self) -> None:
        """Call listeners directly — use only when already running on the HA event loop."""
        for listener in list(self._listeners):
            listener()

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
            "Luxeva: no status message for %d s — marking unavailable", AVAILABILITY_TIMEOUT
        )
        self._availability_unsub = None
        self.data["available"] = False
        # Already on HA loop — call directly, no need for call_soon_threadsafe.
        self._notify_listeners_on_loop()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_connect(self) -> None:
        """Connect to the MQTT broker (blocking I/O runs in executor)."""
        await self.hass.async_add_executor_job(self._connect)

    def _connect(self) -> None:
        client = _make_mqtt_client(self.client_id)
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.on_disconnect = self._on_disconnect
        # Exponential back-off between reconnect attempts: 1 s → up to 30 s.
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        try:
            client.connect(self.broker, self.port, keepalive=60)
        except Exception as exc:
            _LOGGER.error("Luxeva: failed to connect to %s:%s — %s", self.broker, self.port, exc)
            raise
        self._client = client
        client.loop_start()

    async def async_disconnect(self) -> None:
        """Disconnect from the MQTT broker and cancel the watchdog."""
        self._disarm_watchdog()
        if self._client is not None:
            await self.hass.async_add_executor_job(self._disconnect)

    def _disconnect(self) -> None:
        if self._client is not None:
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None

    # ------------------------------------------------------------------
    # paho callbacks (run in paho's internal thread)
    # ------------------------------------------------------------------

    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: Any, rc: int) -> None:
        if rc == 0:
            _LOGGER.debug("Luxeva: connected to %s:%s", self.broker, self.port)
            client.subscribe(self.out_topic)
            # Stay unavailable until the first status message arrives;
            # a bare TCP connection without data doesn't prove the device is reachable.
        else:
            _LOGGER.warning("Luxeva: MQTT connect failed (rc=%d)", rc)
            self.data["available"] = False
            self._notify_listeners()

    def _on_disconnect(self, client: mqtt.Client, userdata: Any, rc: int) -> None:
        _LOGGER.warning("Luxeva: disconnected (rc=%d); paho will attempt reconnect", rc)
        self.data["available"] = False
        # Disarm watchdog — no point counting down when we know the connection is gone.
        self.hass.loop.call_soon_threadsafe(self._disarm_watchdog)
        self._notify_listeners()

    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        try:
            payload = msg.payload.decode("utf-8").strip()
            _LOGGER.debug("Luxeva outTopic: %s", payload)
            parsed = _parse_status(payload)
            if parsed:
                self.data.update(parsed)
                self.data["available"] = True
                if parsed["prg"] > 0:
                    self.last_level = parsed["prg"]
                # Reset the 30-second watchdog on the HA event loop.
                self.hass.loop.call_soon_threadsafe(self._arm_watchdog)
                self._notify_listeners()
            else:
                _LOGGER.warning("Luxeva: unrecognised message format: %s", payload)
        except Exception as exc:
            _LOGGER.error("Luxeva: error processing message: %s", exc)

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    def publish(self, command: str) -> None:
        """Publish a command to inTopic. Must be called from the HA event loop."""
        if self._client is None or not self._client.is_connected():
            _LOGGER.warning("Luxeva: cannot publish '%s' — not connected", command)
            return
        result = self._client.publish(self.in_topic, command)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            _LOGGER.error("Luxeva: publish failed (rc=%d) for command '%s'", result.rc, command)
        else:
            _LOGGER.debug("Luxeva inTopic: %s", command)


def _parse_status(message: str) -> dict[str, Any] | None:
    """Parse a Luxeva status string into a data dict."""
    match = _STATUS_RE.match(message)
    if not match:
        return None
    return {
        "msg": int(match.group(1)),
        "prg": int(match.group(2)),
        "tmp": int(match.group(3)),
        "hts": int(match.group(4)),
        "tmr": match.group(5),
    }
