# Release notes

## 2.0.0-beta.1 — major-version preview

This preview adds external room-temperature regulation and local MQTT setup while
preserving existing 1.x installations in Compatibility mode. Background on the
behavior is in the [design document](docs/design.md).

### New thermostat and control ownership

- The existing Luxeva climate can regulate an external HA temperature sensor,
  exposing target temperature, heat/off and P1–P6 intensity in one entity.
- Without an external sensor, it remains a manual heat/off and level controller.
- Configure selects Luxeva climate or an external-controller actuator. Starts
  through the unselected controller are rejected; stop remains available.
- Hysteresis defaults to ±0.3°C with a five-minute minimum switching interval.
  Missing/invalid temperature requests shutdown. Optional sensor-age checking and
  Celsius/Fahrenheit/Kelvin conversion are supported.
- Managed heating disables the device thermostat (`H0`). Its reported setpoint
  remains visible, and raw `Tmp` has a separate internal-temperature diagnostic.
  The built-in temperature is not presented as accurate room sensing.

### Renewable safety countdown and persisted user sessions

- Luxeva climate starts with `T1` and renews it every ten minutes while heating is
  needed and device/sensor data remain valid. Unconfirmed timer renewal requests
  shutdown and disables regulation until a new explicit start. Later remote or app
  starts are not blocked by that fault.
- Heating started by the remote or app receives one protective one-hour interval
  when external-start protection is enabled. HA does not take over or renew it.
- Device status silence stops renewals without itself shutting the heater down.
  Shutdown sends `B0` alone, leaving the device countdown in place until it is
  confirmed off.
- Long user timers become persisted absolute HA deadlines, implemented through
  one-hour device intervals. Thermostat idle periods and HA restarts do not reset
  or extend the session.
- Timer zero cancels a managed session limit without stopping active heating or
  removing its safety countdown. In Compatibility mode it retains the old off action.
- MQTT timer commands and detectable IR timer changes are adopted as user sessions.
  Own MQTT echoes do not create sessions. MAC topics remain native and independent.
- At a user deadline, heating is stopped and regulation ends. Actuator restart
  requests are blocked until the user explicitly clears or replaces the session.
- Existing Timer Remaining still exposes device minutes; User session remaining
  separately exposes the HA deadline. The firmware's whole-hour resolution means
  exact partial-hour shutdown depends on HA being available at the deadline.

### Shared local MQTT service

- The Add integration menu now offers Heater or Local MQTT service. A heater can
  be given a name such as Terrace or Patio during setup, which also names its
  entities.
- Each heater remains a separate MAC-based config entry/device with independent
  settings, sessions and safety state. Multiple heaters can reuse one service.
  Each broker address and port can belong to only one service entry. Changing a
  service's broker ends the sessions of its heaters, then reconnects them.
- Local service entries configure the broker address and expose broker health.
  Home Assistant connects with the heater's fixed login, so no credentials are typed.
  They do not synthesize heater status or replace HA's own MQTT configuration.
- Optional Supervisor setup checks/installs Mosquitto, provisions the observed
  firmware login, preserves existing options/users, rejects password conflicts,
  and starts/restarts the broker only as necessary. Setup checks CONNACK.
- DNS redirection remains user-managed, with instructions and a repair issue
  until fresh local status for the selected heater arrives. No silent cloud fallback.

### Manual power-cut shutdown

- Configure an optional upstream HA switch, then use Safety shutdown to latch
  heating off, cancel the session and request power-off independently of heater MQTT.
- Latch state survives restart and blocks further heating publications, including
  in Compatibility mode. Status distinguishes confirmed off, unconfirmed and failure.
- Safety controls remain available when MQTT is unreachable at HA startup, or
  when a referenced local service is missing.
- Reset requires the upstream switch to report off; it never restores power or
  heating. No automatic power-cut policy is introduced.

### Migration and compatibility

- Existing entries migrate in place to Compatibility mode. Device identity, MAC,
  entity unique IDs and old timer/actuator behavior are preserved.
- Generic Thermostat helpers remain separate user configuration. Moving to the
  Luxeva thermostat is opt-in; disable the old helper first.
- Changing configuration ends the current session and leaves heating off.
- Minimum HA version for this preview is 2026.9.4. See [migration](docs/migration.md)
  and [local setup](docs/local-mqtt.md).

### Protocol documentation

- Added the saved manufacturer manual, an [MQTT protocol](docs/mqtt-protocol.md)
  description, the full [IR specification](docs/ir-protocol.md), a machine-readable
  button map, decoder, capture evidence, MQTT correlations and PCAP findings.
- IR encoding matches the protocol named Xiaomi in IrpTransmogrifier, verified
  against 298 received frames. No generated IR transmission has been heater-tested.

### Validation and remaining device acceptance

Automated tests cover migration, ownership, thermostat regulation, sensor failure,
renewal confirmation, session persistence/expiry, command echoes, external timers,
power-cut failure/latching, provisioning and independent heaters sharing a broker.
These are software checks, not proof of physical operation.

Before stable release, verify MQTT activation from standby, repeated `T1` renewal,
local DNS/broker operation and upstream relay behavior on the real device. IR-only
same-value timer resets can be indistinguishable from ordinary status; external
long timers cannot be shortened while HA is absent. The official app's full backend
and OTA protocol are not implemented or claimed.
