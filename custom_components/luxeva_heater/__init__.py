"""Luxeva heater entries and reusable local MQTT service entries."""

from __future__ import annotations

import logging

from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store

from .const import (
    CONF_BROKER,
    CONF_CONNECTION,
    CONF_CONTROL_MODE,
    CONF_ENTRY_TYPE,
    CONF_LOCAL_SERVICE,
    CONF_MAC,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    CONNECTION_LOCAL,
    DEFAULT_BROKER,
    DEFAULT_OPTIONS,
    DEFAULT_PORT,
    DOMAIN,
    ENTRY_HEATER,
    ENTRY_LOCAL_SERVICE,
    MODE_COMPATIBILITY,
)
from .control import LuxevaControl
from .coordinator import LuxevaConfigEntry, LuxevaCoordinator
from .local import LocalServiceRuntime

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.BUTTON,
    Platform.BINARY_SENSOR,
]


async def async_migrate_entry(hass: HomeAssistant, entry: LuxevaConfigEntry) -> bool:
    """Preserve IDs and all 1.x behavior until the owner explicitly opts in."""
    if entry.version > 2:
        return False
    if entry.version == 1:
        options = (
            DEFAULT_OPTIONS
            | dict(entry.options)
            | {CONF_CONTROL_MODE: MODE_COMPATIBILITY}
        )
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_ENTRY_TYPE: ENTRY_HEATER},
            options=options,
            version=2,
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: LuxevaConfigEntry) -> bool:
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_LOCAL_SERVICE:
        runtime = LocalServiceRuntime(hass, dict(entry.options))
        entry.runtime_data = runtime
        await runtime.async_start()
        entry.async_on_unload(entry.add_update_listener(_async_service_updated))
        await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])

        async def stop_service(_event: Event) -> None:
            await runtime.async_close()

        entry.async_on_unload(
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop_service)
        )
        return True

    options = DEFAULT_OPTIONS | dict(entry.options)
    broker_options = options
    missing_service = False
    if options[CONF_CONNECTION] == CONNECTION_LOCAL:
        service = hass.config_entries.async_get_entry(
            options.get(CONF_LOCAL_SERVICE, "")
        )
        if (
            service is None
            or service.domain != DOMAIN
            or service.data.get(CONF_ENTRY_TYPE) != ENTRY_LOCAL_SERVICE
        ):
            missing_service = True
            broker_options = {CONF_BROKER: "", CONF_PORT: DEFAULT_PORT}
        else:
            broker_options = dict(service.options)
    broker = broker_options.get(CONF_BROKER, DEFAULT_BROKER)
    port = broker_options.get(CONF_PORT, DEFAULT_PORT)
    coordinator = LuxevaCoordinator(hass, entry.data[CONF_MAC], broker, port)
    coordinator.username = broker_options.get(CONF_USERNAME)
    coordinator.password = broker_options.get(CONF_PASSWORD)
    coordinator.connection = options[CONF_CONNECTION]
    coordinator.control = LuxevaControl(coordinator, entry)
    coordinator.issue_id = f"local_connection_{entry.entry_id}"
    entry.runtime_data = coordinator
    if coordinator.connection == CONNECTION_LOCAL:
        ir.async_create_issue(
            hass,
            DOMAIN,
            coordinator.issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="local_service_missing"
            if missing_service
            else "local_connection",
            translation_placeholders={"broker": str(broker), "mac": coordinator.mac},
        )
    try:
        await coordinator.control.async_start()
        if not missing_service:
            await coordinator.async_connect()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception as exc:
        await coordinator.control.async_close()
        await coordinator.async_disconnect()
        raise ConfigEntryNotReady(
            f"Cannot set up Luxeva connection ({broker}:{port}): {exc}"
        ) from exc

    async def stop(_event: Event) -> None:
        await coordinator.control.async_close()
        await coordinator.async_disconnect()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop))
    return True


async def _async_service_updated(hass: HomeAssistant, entry) -> None:
    """Apply a shared broker change: end dependent sessions, then reconnect."""
    await _async_restart_heaters(hass, entry.entry_id, reload_service=True)


async def _async_restart_heaters(
    hass: HomeAssistant, service_id: str, *, reload_service: bool
) -> None:
    """Stop every heater using a service before the first await, then reload."""
    heaters = [
        heater
        for heater in hass.config_entries.async_entries(DOMAIN)
        if heater.options.get(CONF_LOCAL_SERVICE) == service_id
    ]
    controls = []
    for heater in heaters:
        runtime = getattr(heater, "runtime_data", None)
        if runtime:
            # Starts stay refused until reload replaces this controller.
            runtime.control.suspend()
            controls.append(runtime.control)
    for control in controls:
        try:
            await control._store.async_save(control.snapshot())
        except Exception:
            _LOGGER.exception("Could not persist a stopped Luxeva session")
    entry_ids = [heater.entry_id for heater in heaters]
    if reload_service:
        entry_ids.insert(0, service_id)
    for entry_id in entry_ids:
        # One failed reload must not leave the other heaters on the old broker.
        # A heater whose reload fails stays suspended (off) until reloaded.
        try:
            if not await hass.config_entries.async_reload(entry_id):
                _LOGGER.warning("Luxeva entry %s did not reload", entry_id)
        except Exception:
            _LOGGER.exception("Could not reload Luxeva entry %s", entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: LuxevaConfigEntry) -> bool:
    service = entry.data.get(CONF_ENTRY_TYPE) == ENTRY_LOCAL_SERVICE
    unloaded = await hass.config_entries.async_unload_platforms(
        entry, [Platform.SENSOR] if service else PLATFORMS
    )
    if unloaded:
        if service:
            await entry.runtime_data.async_close()
        else:
            await entry.runtime_data.control.async_close()
            await entry.runtime_data.async_disconnect()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry) -> None:
    if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_LOCAL_SERVICE:
        ir.async_delete_issue(hass, DOMAIN, f"local_connection_{entry.entry_id}")
        # Only permanent removal discards the persisted session and latch.
        await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.control").async_remove()
    else:
        # Removing a shared service cannot leave its old heater connections
        # silently running. Re-setup reports the missing prerequisite.
        await _async_restart_heaters(hass, entry.entry_id, reload_service=False)
