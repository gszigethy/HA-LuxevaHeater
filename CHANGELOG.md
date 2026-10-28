# Release notes

## 2.0.3 — Dependency maintenance

- Update the Home Assistant test dependency from 2026.10.2 to 2026.10.4 ([#24](https://github.com/gszigethy/HA-LuxevaHeater/pull/24)).
- Update the Supervisor test dependency from aiohasupervisor 0.7.0 to 0.8.1 ([#26](https://github.com/gszigethy/HA-LuxevaHeater/pull/26)).
- Update Ruff from 0.17.1 to 0.17.2 ([#25](https://github.com/gszigethy/HA-LuxevaHeater/pull/25)).
- Update the pinned setup-python action from 7.0.0 to 7.1.0 in CI and release validation ([#22](https://github.com/gszigethy/HA-LuxevaHeater/pull/22)).
- Update the pinned Hassfest action in CI and release validation ([#23](https://github.com/gszigethy/HA-LuxevaHeater/pull/23)).

Heater behavior and the minimum supported Home Assistant version remain unchanged.

## 2.0.2 — Dependency maintenance

- Update the Home Assistant test dependency from 2026.10.1 to 2026.10.2 ([#19](https://github.com/gszigethy/HA-LuxevaHeater/pull/19)).
- Update the Supervisor test dependency from aiohasupervisor 0.6.0 to 0.7.0 ([#20](https://github.com/gszigethy/HA-LuxevaHeater/pull/20)).
- Update Ruff from 0.17.0 to 0.17.1 ([#21](https://github.com/gszigethy/HA-LuxevaHeater/pull/21)).
- Update the pinned Hassfest action in CI and release validation ([#18](https://github.com/gszigethy/HA-LuxevaHeater/pull/18)).

Heater behavior and the minimum supported Home Assistant version remain unchanged.

## 2.0.1 — Dependency maintenance

- Update the Home Assistant test dependency from 2026.9.4 to 2026.10.1 ([#16](https://github.com/gszigethy/HA-LuxevaHeater/pull/16)).
- Update Ruff from 0.16.10 to 0.17.0 ([#15](https://github.com/gszigethy/HA-LuxevaHeater/pull/15)).
- Update the pinned Hassfest action in CI and release validation ([#14](https://github.com/gszigethy/HA-LuxevaHeater/pull/14)).

Heater behavior and the minimum supported Home Assistant version remain unchanged.

## 2.0.0 — Room thermostat, local MQTT and safety shutdown

Existing 1.x heaters keep working unchanged after the update, in **Compatibility**
mode with the same entity IDs. All new features are opt-in through **Configure**.
See the [migration guide](docs/migration.md).

### Room thermostat

- The Luxeva climate entity can now regulate the room using any HA temperature
  sensor: heat/off, target temperature and level P1–P6 in one entity.
- Hysteresis of ±0.3 °C and a minimum of five minutes between heating changes,
  both configurable. Celsius, Fahrenheit and Kelvin sensors are supported.
- A missing, invalid or silent sensor stops heating. The maximum sensor age
  defaults to 60 minutes; repeated identical readings count as fresh.
- Without a sensor, the climate entity is a manual heat/off and level control.
- Choose the heating controller per heater: **Luxeva climate**, or **Actuator** for
  an existing Generic Thermostat helper. Starts through the other one are refused;
  stop always works.
- Managed heating disables the heater's built-in thermostat. Its own temperature
  reading is shown separately as a diagnostic, since it reads hotter than the room.

### Safety countdown and timer sessions

- While HA heats, the heater always runs a one-hour countdown that HA renews every
  ten minutes. If HA, the network or MQTT fails, the heater switches itself off
  within an hour. A renewal the heater does not confirm stops that heating run.
- Optional protection for remote/app starts: heating started outside HA gets one
  one-hour countdown. HA does not take it over.
- The Timer entity sets a user session of up to nine hours that survives HA
  restarts and is not extended by idle periods. Timer 0 cancels the limit without
  stopping heating. App timers and detectable remote timer changes become sessions.
- New **User session remaining** sensor; **Timer Remaining** still shows the device
  countdown.

### Local MQTT (cloudless)

- New **Local MQTT service** entry, shared by any number of heaters. It can install
  and prepare the Mosquitto app, adding the heater's fixed login without creating an
  HA user, and waits for the broker after a restart. No credentials to enter.
- Broker health sensor, and a repair issue until the heater's status arrives
  through the local broker. You redirect `iot.luxeva.com.tr` in your own DNS (and
  firewall, across VLANs); there is no silent cloud fallback.
- Changing a service safely stops and reconnects its heaters; a failed reconnect of
  one heater does not affect the others.

### Safety shutdown (power cut)

- Optional upstream switch (plug or relay) per heater adds **Safety shutdown**,
  **Reset safety shutdown** and **Safety shutdown active**.
- Shutdown latches heating off in every mode and requests power-off without waiting
  for MQTT. The latch survives restarts; reset never restores power or heating.

### Setup and other changes

- Optional heater name at setup (for example Terrace), used for the device and
  entity IDs.
- Saving a heater's configuration ends its session and leaves it off.
- Hungarian translation updated. Minimum Home Assistant version is 2026.9.4.
- New documentation: [design](docs/design.md), [MQTT protocol](docs/mqtt-protocol.md),
  [infrared protocol](docs/ir-protocol.md) and [local MQTT setup](docs/local-mqtt.md).

### Known limitations

- Verified on hardware: local MQTT through DNS redirection with the fixed login.
  Not yet verified: repeated countdown renewal in Luxeva climate mode, MQTT start
  from standby, and upstream relay behavior.
- Remote timer resets that leave the remaining time unchanged cannot be detected.
  The final partial hour of a session is enforced by HA, so it depends on HA running.
