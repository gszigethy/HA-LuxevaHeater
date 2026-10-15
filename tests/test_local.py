"""Broker prerequisite setup must preserve shared users and options."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from aiohasupervisor import SupervisorNotFoundError
from homeassistant.exceptions import HomeAssistantError
import pytest

from custom_components.luxeva_heater import local
from custom_components.luxeva_heater.const import DEVICE_PASSWORD, DEVICE_USERNAME


def broker_hass(monkeypatch, logins, state="started"):
    info = SimpleNamespace(
        options={
            "logins": logins,
            "customize": {"active": True, "folder": "mosquitto"},
        },
        state=state,
    )
    client = SimpleNamespace(
        addons=SimpleNamespace(
            addon_info=AsyncMock(return_value=info),
            set_addon_options=AsyncMock(),
            start_addon=AsyncMock(),
            restart_addon=AsyncMock(),
        ),
        store=SimpleNamespace(install_addon=AsyncMock()),
    )
    # The HA hassio handler has unrelated platform dependencies; patch its
    # import boundary while testing the actual Supervisor request models.
    import sys

    monkeypatch.setitem(
        sys.modules,
        "homeassistant.components.hassio.handler",
        SimpleNamespace(get_supervisor_client=lambda hass: client),
    )
    return (
        SimpleNamespace(config=SimpleNamespace(components={"hassio"}), data={}),
        client,
        info,
    )


def test_preparation_preserves_existing_users_and_configuration(monkeypatch):
    hass, client, info = broker_hass(
        monkeypatch, [{"username": "other", "password": "existing"}]
    )
    asyncio.run(local.async_prepare_mosquitto(hass))
    client.store.install_addon.assert_not_called()
    model = client.addons.set_addon_options.call_args.args[1]
    assert model.config["logins"] == info.options["logins"] + [
        {"username": DEVICE_USERNAME, "password": DEVICE_PASSWORD}
    ]
    assert model.config["customize"] == info.options["customize"]
    assert len(info.options["logins"]) == 1  # no mutation of the old configuration
    client.addons.restart_addon.assert_awaited_once_with("core_mosquitto")


def test_preparation_is_idempotent_and_does_not_restart_existing_broker(monkeypatch):
    hass, client, _ = broker_hass(
        monkeypatch, [{"username": DEVICE_USERNAME, "password": DEVICE_PASSWORD}]
    )
    asyncio.run(local.async_prepare_mosquitto(hass))
    client.addons.set_addon_options.assert_not_called()
    client.addons.restart_addon.assert_not_called()


def test_preparation_rejects_conflicting_login_without_modifying_it(monkeypatch):
    hass, client, _ = broker_hass(
        monkeypatch, [{"username": DEVICE_USERNAME, "password": "different"}]
    )
    with pytest.raises(HomeAssistantError, match="different password"):
        asyncio.run(local.async_prepare_mosquitto(hass))
    client.addons.set_addon_options.assert_not_called()
    client.addons.restart_addon.assert_not_called()


def test_missing_mosquitto_is_installed_and_started(monkeypatch):
    hass, client, info = broker_hass(monkeypatch, [], state="stopped")
    client.addons.addon_info.side_effect = [SupervisorNotFoundError("missing"), info]
    asyncio.run(local.async_prepare_mosquitto(hass))
    client.store.install_addon.assert_awaited_once_with("core_mosquitto")
    client.addons.start_addon.assert_awaited_once_with("core_mosquitto")


def test_without_supervisor_existing_broker_is_required():
    hass = SimpleNamespace(config=SimpleNamespace(components=set()))
    with pytest.raises(HomeAssistantError, match="Supervisor"):
        asyncio.run(local.async_prepare_mosquitto(hass))


def test_probe_checks_authentication_and_cleans_up(monkeypatch):
    client = Mock()

    def start():
        client.on_connect(client, None, None, SimpleNamespace(is_failure=False), None)

    client.loop_start.side_effect = start
    monkeypatch.setattr(local.mqtt, "Client", lambda *args, **kwargs: client)
    hass = SimpleNamespace(
        async_add_executor_job=AsyncMock(side_effect=lambda fn: fn())
    )
    options = {"broker": "broker", "port": 1883, "username": "u", "password": "p"}
    assert asyncio.run(local.async_probe_broker(hass, options))
    client.username_pw_set.assert_called_once_with("u", "p")
    client.subscribe.assert_not_called()
    client.publish.assert_not_called()
    client.disconnect.assert_called_once()
    client.loop_stop.assert_called_once()


def test_probe_rejects_refused_connection(monkeypatch):
    client = Mock()
    client.loop_start.side_effect = lambda: client.on_connect(
        client, None, None, SimpleNamespace(is_failure=True), None
    )
    monkeypatch.setattr(local.mqtt, "Client", lambda *args, **kwargs: client)
    hass = SimpleNamespace(
        async_add_executor_job=AsyncMock(side_effect=lambda fn: fn())
    )
    assert not asyncio.run(
        local.async_probe_broker(hass, {"broker": "broker", "port": 1883})
    )
