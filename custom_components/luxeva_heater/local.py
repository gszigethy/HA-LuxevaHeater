"""Shared local MQTT service configuration; never replace native MAC topics."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import threading
from typing import Any

import paho.mqtt.client as mqtt

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_time_interval
from datetime import timedelta

from .const import (
    CONF_BROKER,
    CONF_PORT,
    DEVICE_PASSWORD,
    DEVICE_USERNAME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def async_prepare_mosquitto(hass) -> None:
    """Explicit setup action: preserve all options and existing broker logins."""
    if "hassio" not in hass.config.components:
        raise HomeAssistantError(
            "Mosquitto installation requires Supervisor. Configure an existing broker instead."
        )
    from aiohasupervisor import SupervisorNotFoundError
    from aiohasupervisor.models import AddonsOptions
    from homeassistant.components.hassio.handler import get_supervisor_client

    lock = hass.data.setdefault(f"{DOMAIN}_broker_setup_lock", asyncio.Lock())
    async with lock:
        client = get_supervisor_client(hass)
        try:
            info = await client.addons.addon_info("core_mosquitto")
        except SupervisorNotFoundError:
            await client.store.install_addon("core_mosquitto")
            info = await client.addons.addon_info("core_mosquitto")
        options = dict(info.options)
        logins = list(options.get("logins", []))
        existing = next(
            (login for login in logins if login.get("username") == DEVICE_USERNAME),
            None,
        )
        if existing and existing.get("password") != DEVICE_PASSWORD:
            raise HomeAssistantError(
                "The device username already has a different password. Resolve the broker login conflict manually."
            )
        changed = existing is None
        if changed:
            logins.append({"username": DEVICE_USERNAME, "password": DEVICE_PASSWORD})
            options["logins"] = logins
            await client.addons.set_addon_options(
                "core_mosquitto", AddonsOptions(config=options)
            )
        state = getattr(info.state, "value", info.state)
        if state != "started":
            await client.addons.start_addon("core_mosquitto")
        elif changed:
            await client.addons.restart_addon("core_mosquitto")


async def async_probe_broker(hass, options: dict[str, Any]) -> bool:
    """Check CONNACK, not just an open TCP port. No subscriptions or commands."""

    def probe() -> bool:
        done = threading.Event()
        accepted = False
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id="luxeva-check-" + __import__("uuid").uuid4().hex[:12],
        )
        client.connect_timeout = 5
        # The broker must accept the heater's fixed login anyway, so HA uses it
        # too: there is no separately typed credential to get wrong.
        client.username_pw_set(DEVICE_USERNAME, DEVICE_PASSWORD)

        def connected(_client, _userdata, _flags, reason, _properties):
            nonlocal accepted
            accepted = not reason.is_failure
            done.set()

        client.on_connect = connected
        try:
            client.connect(options[CONF_BROKER], options[CONF_PORT], keepalive=15)
            client.loop_start()
            done.wait(5)
            return accepted
        except OSError:
            return False
        finally:
            client.disconnect()
            client.loop_stop()

    return await hass.async_add_executor_job(probe)


@dataclass
class LocalServiceRuntime:
    """Shared broker health, with no device ownership or synthetic status stream."""

    hass: Any
    options: dict[str, Any]
    connected: bool = False

    def __post_init__(self):
        self.listeners = []
        self._unsub = None
        self._closed = False
        self._checking = False

    async def async_start(self):
        await self._check()
        self._unsub = async_track_time_interval(
            self.hass, self._check, timedelta(seconds=60)
        )

    async def _check(self, _now=None):
        if self._checking or self._closed:
            return
        self._checking = True
        try:
            self.connected = await async_probe_broker(self.hass, self.options)
            if not self._closed:
                for listener in list(self.listeners):
                    listener()
        finally:
            self._checking = False

    def add_listener(self, listener):
        self.listeners.append(listener)
        return lambda: (
            self.listeners.remove(listener) if listener in self.listeners else None
        )

    async def async_close(self):
        self._closed = True
        if self._unsub:
            self._unsub()
