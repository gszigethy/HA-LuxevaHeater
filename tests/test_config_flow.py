"""Tests for Luxeva Heater config-flow helpers."""

# Exercise the real form schemas and flow transitions, using only a small
# config-entry registry stand-in (no live Home Assistant or broker mutations).
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from homeassistant.data_entry_flow import AbortFlow

from custom_components.luxeva_heater import config_flow as module
from custom_components.luxeva_heater.const import DEFAULT_OPTIONS, DOMAIN


import pytest

from custom_components.luxeva_heater.config_flow import _normalize_mac


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("00:aa:11:bb:22:cc", "00:AA:11:BB:22:CC"),
        ("00-AA-11-BB-22-CC", "00:AA:11:BB:22:CC"),
        ("00AA11BB22CC", "00:AA:11:BB:22:CC"),
        (" 00 aa 11 bb 22 cc ", "00:AA:11:BB:22:CC"),
        ("00:AA:11:BB:22", None),
        ("not-a-mac", None),
        ("", None),
    ],
)
def test_normalize_mac(raw: str, expected: str | None) -> None:
    assert _normalize_mac(raw) == expected


def flow_hass(entries=()):
    entries = list(entries)
    registry = SimpleNamespace(
        async_entries=lambda domain: entries,
        async_get_entry=lambda entry_id: next(
            (e for e in entries if e.entry_id == entry_id), None
        ),
        async_get_known_entry=lambda entry_id: next(
            e for e in entries if e.entry_id == entry_id
        ),
        async_entry_for_domain_unique_id=lambda domain, unique_id: next(
            (e for e in entries if getattr(e, "unique_id", None) == unique_id), None
        ),
        flow=SimpleNamespace(async_progress_by_handler=lambda *args, **kwargs: []),
    )
    return SimpleNamespace(
        config_entries=registry, async_create_task=asyncio.create_task
    )


def new_flow(hass):
    flow = module.LuxevaConfigFlow()
    flow.hass = hass
    flow.handler = DOMAIN
    flow.flow_id = "flow"
    flow.context = {"source": "user"}
    return flow


def test_new_heater_flow_and_schemas():
    async def run():
        flow = new_flow(flow_hass())
        menu = await flow.async_step_user()
        assert menu["menu_options"] == ["heater", "local_service"]
        invalid = await flow.async_step_heater({"mac": "wrong"})
        assert invalid["errors"] == {"mac": "invalid_mac"}
        disclaimer = await flow.async_step_heater({"mac": "00aa11bb22cc"})
        assert disclaimer["step_id"] == "disclaimer"
        rejected = await flow.async_step_disclaimer({"disclaimer_accepted": False})
        assert rejected["errors"]
        settings = await flow.async_step_disclaimer({"disclaimer_accepted": True})
        assert settings["step_id"] == "settings"
        values = {
            key: DEFAULT_OPTIONS[key]
            for key in (
                "control_mode",
                "connection",
                "tolerance",
                "minimum_cycle_seconds",
                "sensor_timeout_minutes",
                "protect_external_starts",
            )
        }
        assert settings["data_schema"](values) == values
        result = await flow.async_step_settings(values)
        assert result["type"] == "create_entry"
        assert result["data"]["mac"] == "00:AA:11:BB:22:CC"
        assert result["version"] == 2
        assert result["options"]["control_mode"] == "climate"

    asyncio.run(run())


def test_existing_mac_is_rejected_but_different_heaters_are_allowed():
    entry = SimpleNamespace(
        entry_id="one", unique_id="00AA11BB22CC", source="user", data={}
    )
    flow = new_flow(flow_hass([entry]))
    with pytest.raises(AbortFlow, match="already_configured"):
        asyncio.run(flow.async_step_heater({"mac": "00:AA:11:BB:22:CC"}))
    result = asyncio.run(flow.async_step_heater({"mac": "00:AA:11:BB:22:DD"}))
    assert result["step_id"] == "disclaimer"


def test_local_heater_requires_separate_service():
    flow = new_flow(flow_hass())
    flow._mac = "00:AA:11:BB:22:CC"
    result = asyncio.run(
        flow.async_step_settings(DEFAULT_OPTIONS | {"connection": "local"})
    )
    assert result["errors"]["connection"] == "local_service_required"
    service = SimpleNamespace(
        entry_id="shared",
        domain=DOMAIN,
        title="Local MQTT",
        data={"entry_type": "local_service"},
    )
    flow.hass = flow_hass([service])
    result = asyncio.run(
        flow.async_step_settings(
            DEFAULT_OPTIONS | {"connection": "local", "local_service": "shared"}
        )
    )
    assert result["type"] == "create_entry"
    assert result["options"]["local_service"] == "shared"


def test_local_service_checks_broker_and_creates_no_mac_entry(monkeypatch):
    monkeypatch.setattr(module, "async_probe_broker", AsyncMock(return_value=True))
    prepare = AsyncMock()
    monkeypatch.setattr(module, "async_prepare_mosquitto", prepare)

    async def run():
        flow = new_flow(flow_hass())
        form = await flow.async_step_local_service()
        assert form["step_id"] == "local_service"
        values = {"broker": "core-mosquitto", "port": 1883, "prepare_mosquitto": True}
        progress = await flow.async_step_local_service(values)
        assert progress["type"] == "progress"
        await flow._broker_task
        done = await flow.async_step_prepare()
        assert done["type"] == "progress_done"
        result = await flow.async_step_local_service()
        assert result["data"] == {"entry_type": "local_service"}
        assert result["title"] == "Luxeva Local MQTT"
        assert "mac" not in result["data"]
        assert "prepare_mosquitto" not in result["options"]
        # Service identity is the entry itself, never a mutable endpoint.
        assert flow.unique_id is None
        prepare.assert_awaited_once()

    asyncio.run(run())


def test_broker_failure_returns_to_form_without_exposing_exception(monkeypatch):
    monkeypatch.setattr(
        module,
        "async_probe_broker",
        AsyncMock(side_effect=RuntimeError("password secret")),
    )

    async def run():
        flow = new_flow(flow_hass())
        await flow.async_step_local_service({"broker": "broker", "port": 1883})
        await flow._broker_task
        result = await flow.async_step_local_service()
        assert result["errors"] == {"base": "broker_setup_failed"}
        assert "secret" not in str(result["errors"])

    asyncio.run(run())


def test_options_stop_session_before_changing_owner():
    control = SimpleNamespace(
        latched=False,
        power_switch=None,
        turn_off=Mock(),
        snapshot=lambda: {},
        _store=SimpleNamespace(async_save=AsyncMock()),
    )
    entry = SimpleNamespace(
        entry_id="heater",
        data={"mac": "00:AA:11:BB:22:CC"},
        options=DEFAULT_OPTIONS | {"control_mode": "compatibility"},
        runtime_data=SimpleNamespace(control=control),
    )
    flow = module.LuxevaOptionsFlow()
    flow.hass = flow_hass([entry])
    flow.flow_id = "options"
    flow.handler = "heater"
    flow.context = {}
    form = asyncio.run(flow.async_step_init())
    assert form["step_id"] == "init"
    result = asyncio.run(flow.async_step_init(DEFAULT_OPTIONS))
    assert result["data"]["control_mode"] == "climate"
    control.turn_off.assert_called_once()
    control._store.async_save.assert_awaited_once()


def service_entry(entry_id, broker="core-mosquitto", port=1883):
    return SimpleNamespace(
        entry_id=entry_id,
        domain=DOMAIN,
        title=f"Local MQTT — {broker}",
        data={"entry_type": "local_service"},
        options={"broker": broker, "port": port},
    )


def test_service_options_do_not_use_automatic_reload():
    from homeassistant.config_entries import OptionsFlowWithReload

    heater = SimpleNamespace(data={"mac": "00:AA:11:BB:22:CC"})
    service = service_entry("shared")
    # The service entry owns an update listener; HA forbids combining it with
    # OptionsFlowWithReload and fails the flow when it finishes.
    assert not isinstance(
        module.LuxevaConfigFlow.async_get_options_flow(service), OptionsFlowWithReload
    )
    assert isinstance(
        module.LuxevaConfigFlow.async_get_options_flow(heater), OptionsFlowWithReload
    )


def test_service_options_leave_heater_shutdown_to_the_update_listener(monkeypatch):
    monkeypatch.setattr(module, "async_probe_broker", AsyncMock(return_value=True))
    control = SimpleNamespace(turn_off=Mock())
    heater = SimpleNamespace(
        entry_id="heater",
        data={"mac": "00:AA:11:BB:22:CC"},
        options={"local_service": "shared"},
        runtime_data=SimpleNamespace(control=control),
    )
    service = service_entry("shared")
    flow = module.LuxevaConfigFlow.async_get_options_flow(service)
    flow.hass = flow_hass([service, heater])
    flow.flow_id = "options"
    flow.handler = "shared"
    flow.context = {}

    async def run():
        await flow.async_step_init({"broker": "other", "port": 1883})
        await flow._broker_task
        return await flow.async_step_init()

    result = asyncio.run(run())
    assert result["type"] == "create_entry"
    assert result["data"] == {"broker": "other", "port": 1883}
    control.turn_off.assert_not_called()


def test_duplicate_broker_endpoint_is_rejected_on_create(monkeypatch):
    probe = AsyncMock(return_value=True)
    monkeypatch.setattr(module, "async_probe_broker", probe)
    flow = new_flow(flow_hass([service_entry("shared")]))
    result = asyncio.run(
        flow.async_step_local_service({"broker": " Core-Mosquitto ", "port": 1883})
    )
    assert result["errors"] == {"base": "broker_in_use"}
    probe.assert_not_called()


def test_duplicate_broker_endpoint_is_rejected_on_edit(monkeypatch):
    monkeypatch.setattr(module, "async_probe_broker", AsyncMock(return_value=True))
    first = service_entry("first", broker="broker-a")
    second = service_entry("second", broker="broker-b")
    flow = module.LuxevaConfigFlow.async_get_options_flow(second)
    flow.hass = flow_hass([first, second])
    flow.flow_id = "options"
    flow.handler = "second"
    flow.context = {}
    taken = asyncio.run(flow.async_step_init({"broker": "broker-a", "port": 1883}))
    assert taken["errors"] == {"base": "broker_in_use"}
    # Keeping its own endpoint while changing credentials is allowed.
    own = asyncio.run(
        flow.async_step_init(
            {"broker": "broker-b", "port": 1883, "prepare_mosquitto": True}
        )
    )
    assert own["type"] == "progress"


def test_endpoint_taken_during_broker_check_is_rejected(monkeypatch):
    entries = []
    hass = flow_hass()
    hass.config_entries.async_entries = lambda domain: entries

    async def probe(_hass, _values):
        entries.append(service_entry("raced"))  # another flow finished first
        return True

    monkeypatch.setattr(module, "async_probe_broker", probe)

    async def run():
        flow = new_flow(hass)
        await flow.async_step_local_service({"broker": "core-mosquitto", "port": 1883})
        await flow._broker_task
        return await flow.async_step_local_service()

    result = asyncio.run(run())
    assert result["type"] == "form"
    assert result["errors"] == {"base": "broker_in_use"}


def test_heater_name_becomes_title_and_device_name():
    async def run(name):
        flow = new_flow(flow_hass())
        values = {"mac": "00aa11bb22cc"} | ({"name": name} if name else {})
        await flow.async_step_heater(values)
        await flow.async_step_disclaimer({"disclaimer_accepted": True})
        return await flow.async_step_settings(
            {
                key: DEFAULT_OPTIONS[key]
                for key in (
                    "control_mode",
                    "connection",
                    "tolerance",
                    "minimum_cycle_seconds",
                    "sensor_timeout_minutes",
                    "protect_external_starts",
                )
            }
        )

    named = asyncio.run(run("  Patio "))
    assert named["title"] == "Patio"
    assert named["data"]["name"] == "Patio"
    unnamed = asyncio.run(run("   "))
    assert unnamed["title"] == "Luxeva Heater 00:AA:11:BB:22:CC"
    assert "name" not in unnamed["data"]


def test_broker_form_asks_for_no_credentials():
    # The heater's login is fixed in firmware; typing it is only a failure point.
    fields = {str(key) for key in module._broker_schema().schema}
    assert fields == {"broker", "port", "prepare_mosquitto"}


def test_broker_check_waits_for_a_restarted_mosquitto(monkeypatch):
    # Preparation may restart Mosquitto; the first checks hit a broker that is
    # still starting and must not fail the setup.
    probe = AsyncMock(side_effect=[False, False, True])
    monkeypatch.setattr(module, "async_probe_broker", probe)
    monkeypatch.setattr(module, "async_prepare_mosquitto", AsyncMock())
    monkeypatch.setattr(module.asyncio, "sleep", AsyncMock())

    async def run():
        flow = new_flow(flow_hass())
        await flow.async_step_local_service(
            {"broker": "core-mosquitto", "port": 1883, "prepare_mosquitto": True}
        )
        await flow._broker_task
        return await flow.async_step_local_service()

    assert asyncio.run(run())["type"] == "create_entry"
    assert probe.await_count == 3


def test_unprepared_broker_is_checked_once(monkeypatch):
    probe = AsyncMock(return_value=False)
    monkeypatch.setattr(module, "async_probe_broker", probe)
    monkeypatch.setattr(module.asyncio, "sleep", AsyncMock())

    async def run():
        flow = new_flow(flow_hass())
        await flow.async_step_local_service({"broker": "broker", "port": 1883})
        await flow._broker_task
        return await flow.async_step_local_service()

    assert asyncio.run(run())["errors"] == {"base": "cannot_connect"}
    assert probe.await_count == 1
