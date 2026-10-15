"""Tests for Luxeva Heater config-entry setup and unload."""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.exceptions import ConfigEntryNotReady
import pytest

from custom_components import luxeva_heater
from custom_components.luxeva_heater.const import CONF_MAC


@pytest.fixture(autouse=True)
def device_registry():
    with patch.object(luxeva_heater.dr, "async_get") as registry:
        yield registry


def make_hass() -> Mock:
    hass = Mock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    return hass


def make_entry() -> Mock:
    entry = Mock()
    entry.data = {CONF_MAC: "00:AA:11:BB:22:CC"}
    entry.options = {}
    entry.entry_id = "heater"
    return entry


def test_setup_disconnects_on_home_assistant_stop() -> None:
    hass = make_hass()
    entry = make_entry()
    coordinator = Mock(async_connect=AsyncMock(), async_disconnect=AsyncMock())

    with (
        patch.object(luxeva_heater, "LuxevaCoordinator", return_value=coordinator),
        patch.object(
            luxeva_heater,
            "LuxevaControl",
            return_value=Mock(async_start=AsyncMock(), async_close=AsyncMock()),
        ),
    ):
        assert asyncio.run(luxeva_heater.async_setup_entry(hass, entry)) is True

    assert entry.runtime_data is coordinator
    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        entry, luxeva_heater.PLATFORMS
    )
    event_type, stop_listener = hass.bus.async_listen_once.call_args.args
    assert event_type == EVENT_HOMEASSISTANT_STOP
    entry.async_on_unload.assert_called_once_with(
        hass.bus.async_listen_once.return_value
    )

    asyncio.run(stop_listener(Mock()))
    coordinator.async_disconnect.assert_awaited_once_with()


def test_setup_not_ready_when_broker_unreachable() -> None:
    hass = make_hass()
    coordinator = Mock(
        async_connect=AsyncMock(side_effect=OSError("unreachable")),
        async_disconnect=AsyncMock(),
    )

    with (
        patch.object(luxeva_heater, "LuxevaCoordinator", return_value=coordinator),
        patch.object(
            luxeva_heater,
            "LuxevaControl",
            return_value=Mock(async_start=AsyncMock(), async_close=AsyncMock()),
        ),
        pytest.raises(ConfigEntryNotReady),
    ):
        asyncio.run(luxeva_heater.async_setup_entry(hass, make_entry()))

    hass.config_entries.async_forward_entry_setups.assert_not_called()


def test_unload_disconnects() -> None:
    hass = make_hass()
    entry = make_entry()
    entry.runtime_data = Mock(
        async_disconnect=AsyncMock(), control=Mock(async_close=AsyncMock())
    )

    assert asyncio.run(luxeva_heater.async_unload_entry(hass, entry)) is True

    entry.runtime_data.async_disconnect.assert_awaited_once_with()


def test_migration_preserves_identity_and_selects_compatibility():
    entry = make_entry()
    entry.version = 1
    entry.unique_id = "00AA11BB22CC"
    hass = make_hass()
    assert asyncio.run(luxeva_heater.async_migrate_entry(hass, entry))
    args = hass.config_entries.async_update_entry.call_args
    assert args.args == (entry,)
    assert args.kwargs["version"] == 2
    assert args.kwargs["options"]["control_mode"] == "compatibility"
    assert args.kwargs["data"][CONF_MAC] == "00:AA:11:BB:22:CC"
    assert "unique_id" not in args.kwargs
    entry.version = 3
    assert not asyncio.run(luxeva_heater.async_migrate_entry(hass, entry))


def test_local_service_is_separate_from_heater_platforms():
    hass = make_hass()
    entry = make_entry()
    entry.data = {"entry_type": "local_service"}
    runtime = Mock(async_start=AsyncMock(), async_close=AsyncMock())
    with patch.object(luxeva_heater, "LocalServiceRuntime", return_value=runtime):
        assert asyncio.run(luxeva_heater.async_setup_entry(hass, entry))
    from homeassistant.const import Platform

    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        entry, [Platform.SENSOR]
    )
    assert entry.runtime_data is runtime


def test_two_heaters_reuse_service_but_keep_their_native_mac_topics():
    from custom_components.luxeva_heater.coordinator import LuxevaCoordinator

    service = Mock(
        domain="luxeva_heater",
        options={
            "broker": "local-broker",
            "port": 1883,
            "username": "u",
            "password": "p",
        },
    )
    service.data = {"entry_type": "local_service"}
    hass = make_hass()
    hass.config_entries.async_get_entry.return_value = service
    coordinators = []

    def coordinator_factory(hass, mac, broker, port):
        coordinator = LuxevaCoordinator(hass, mac, broker, port)
        coordinator.async_connect = AsyncMock()
        coordinators.append(coordinator)
        return coordinator

    with (
        patch.object(
            luxeva_heater, "LuxevaCoordinator", side_effect=coordinator_factory
        ),
        patch.object(
            luxeva_heater,
            "LuxevaControl",
            side_effect=lambda *args: Mock(
                async_start=AsyncMock(), async_close=AsyncMock()
            ),
        ),
        patch.object(luxeva_heater.ir, "async_create_issue"),
    ):
        for mac in ("00:AA:11:BB:22:CC", "00:AA:11:BB:22:DD"):
            entry = make_entry()
            entry.data = {CONF_MAC: mac}
            entry.options = {"connection": "local", "local_service": "shared"}
            assert asyncio.run(luxeva_heater.async_setup_entry(hass, entry))
    assert coordinators[0].broker == coordinators[1].broker == "local-broker"
    assert coordinators[0].out_topic == "outTopic/00:AA:11:BB:22:CC"
    assert coordinators[1].out_topic == "outTopic/00:AA:11:BB:22:DD"
    assert coordinators[0].client_id != coordinators[1].client_id


def test_missing_local_service_keeps_safety_platforms_without_cloud_fallback():
    hass = make_hass()
    hass.config_entries.async_get_entry.return_value = None
    entry = make_entry()
    entry.options = {"connection": "local", "local_service": "missing"}
    coordinator = Mock(async_connect=AsyncMock(), async_disconnect=AsyncMock())
    with (
        patch.object(luxeva_heater, "LuxevaCoordinator", return_value=coordinator),
        patch.object(
            luxeva_heater,
            "LuxevaControl",
            return_value=Mock(async_start=AsyncMock(), async_close=AsyncMock()),
        ),
        patch.object(luxeva_heater.ir, "async_create_issue") as issue,
    ):
        assert asyncio.run(luxeva_heater.async_setup_entry(hass, entry))
    coordinator.async_connect.assert_not_called()
    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        entry, luxeva_heater.PLATFORMS
    )
    assert issue.call_args.kwargs["translation_key"] == "local_service_missing"


def test_service_change_ends_dependent_sessions_and_reloads():
    hass = make_hass()
    hass.config_entries.async_reload = AsyncMock()
    service = Mock(entry_id="shared", data={"entry_type": "local_service"})
    dependent = Mock(entry_id="patio", options={"local_service": "shared"})
    other = Mock(entry_id="terrace", options={"connection": "cloud"})
    hass.config_entries.async_entries.return_value = [service, dependent, other]
    dependent.runtime_data.control._store.async_save = AsyncMock()
    asyncio.run(luxeva_heater._async_service_updated(hass, service))
    dependent.runtime_data.control.suspend.assert_called_once()
    other.runtime_data.control.suspend.assert_not_called()
    reloaded = [
        call.args[0] for call in hass.config_entries.async_reload.await_args_list
    ]
    assert reloaded == ["shared", "patio"]


def test_removing_a_heater_deletes_its_control_storage():
    hass = make_hass()
    entry = make_entry()
    store = Mock(async_remove=AsyncMock())
    with (
        patch.object(luxeva_heater, "Store", return_value=store) as factory,
        patch.object(luxeva_heater.ir, "async_delete_issue"),
    ):
        asyncio.run(luxeva_heater.async_remove_entry(hass, entry))
    assert factory.call_args.args[1:] == (1, "luxeva_heater.heater.control")
    store.async_remove.assert_awaited_once()


def test_one_failed_reload_does_not_skip_other_heaters():
    hass = make_hass()
    service = Mock(entry_id="shared", data={"entry_type": "local_service"})
    patio = Mock(entry_id="patio", options={"local_service": "shared"})
    terrace = Mock(entry_id="terrace", options={"local_service": "shared"})
    hass.config_entries.async_entries.return_value = [service, patio, terrace]
    for heater in (patio, terrace):
        heater.runtime_data.control._store.async_save = AsyncMock()
    hass.config_entries.async_reload = AsyncMock(
        side_effect=[RuntimeError("broker"), False, True]
    )
    asyncio.run(luxeva_heater._async_service_updated(hass, service))
    reloaded = [c.args[0] for c in hass.config_entries.async_reload.await_args_list]
    assert reloaded == ["shared", "patio", "terrace"]


def test_removing_a_service_suspends_every_heater_despite_reload_failure():
    hass = make_hass()
    service = Mock(entry_id="shared", data={"entry_type": "local_service"})
    patio = Mock(entry_id="patio", options={"local_service": "shared"})
    terrace = Mock(entry_id="terrace", options={"local_service": "shared"})
    for heater in (patio, terrace):
        heater.runtime_data.control._store.async_save = AsyncMock()
    hass.config_entries.async_entries.return_value = [patio, terrace]
    hass.config_entries.async_reload = AsyncMock(
        side_effect=[RuntimeError("unload"), True]
    )
    asyncio.run(luxeva_heater.async_remove_entry(hass, service))
    patio.runtime_data.control.suspend.assert_called_once()
    terrace.runtime_data.control.suspend.assert_called_once()
    reloaded = [c.args[0] for c in hass.config_entries.async_reload.await_args_list]
    assert reloaded == ["patio", "terrace"]


@pytest.mark.parametrize(
    ("data_name", "device_name"),
    [("Patio", "Patio"), (None, "Luxeva Heater 00AA11BB22CC")],
)
def test_setup_names_the_device_before_entities_are_added(data_name, device_name):
    hass = make_hass()
    entry = make_entry()
    if data_name:
        entry.data = entry.data | {"name": data_name}
    coordinator = Mock(
        async_connect=AsyncMock(),
        async_disconnect=AsyncMock(),
        client_id="00AA11BB22CC",
        device_name="Luxeva Heater 00AA11BB22CC",
    )
    registry = Mock()
    order = []
    registry.async_get_or_create.side_effect = lambda **kw: order.append("device")
    hass.config_entries.async_forward_entry_setups.side_effect = lambda *a: (
        order.append("platforms")
    )
    with (
        patch.object(luxeva_heater, "LuxevaCoordinator", return_value=coordinator),
        patch.object(
            luxeva_heater,
            "LuxevaControl",
            return_value=Mock(async_start=AsyncMock(), async_close=AsyncMock()),
        ),
        patch.object(luxeva_heater.dr, "async_get", return_value=registry),
    ):
        assert asyncio.run(luxeva_heater.async_setup_entry(hass, entry))
    kwargs = registry.async_get_or_create.call_args.kwargs
    assert kwargs["name"] == device_name
    assert kwargs["identifiers"] == {("luxeva_heater", "00AA11BB22CC")}
    assert order == ["device", "platforms"]
    assert coordinator.device_name == device_name
