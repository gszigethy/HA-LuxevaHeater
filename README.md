# Luxeva Heater

Control Luxeva Wi-Fi infrared heaters from Home Assistant using the Luxeva cloud
or a local MQTT broker. Each heater has its own device and climate entity;
one local MQTT service can serve multiple heaters.

**2.0.0-beta.1 is a major-version preview.** Existing installations keep their
1.x behavior until explicitly reconfigured. See the [release notes](CHANGELOG.md)
and [migration guide](docs/migration.md) before changing control modes.

## Features

- Room thermostat using an external HA temperature sensor, with heat/off,
  target temperature and P1–P6 heating intensity.
- Manual heat/off and level control when no external sensor is selected.
- A renewable one-hour device countdown: loss of HA or MQTT stops renewal,
  leaving the device to stop when its last successfully applied timer expires.
- User sessions up to nine hours, persisted as an absolute deadline and broken
  into one-hour device safety intervals. Thermostat cycling does not restart
  the user session.
- An actuator switch for advanced users with a separate Generic Thermostat helper.
- Optional manual safety shutdown through a separate HA-managed power plug or relay,
  with a persistent latch that never automatically restores power or heating.
- Separate shared local MQTT service entries, with optional Mosquitto preparation
  and device-login provisioning on installations with Supervisor.
- Live reported device state, internal temperature, device countdown, and separate
  user-session time remaining.

## Install

Requires **Home Assistant 2026.9.4 or newer** for this preview.

In HACS, add `https://github.com/gszigethy/HA-LuxevaHeater` as a custom Integration
repository. Install the integration and restart HA. Alternatively, copy
`custom_components/luxeva_heater` into your HA configuration's
`custom_components` directory and restart.

For a published beta, enable prerelease versions in HACS. This source checkout
and its release notes do not themselves publish a release.

## Add a heater

1. Provision its Wi-Fi using the official Luxeva app.
2. Open **Settings → Devices & services → Add integration → Luxeva Heater**.
3. Choose **Heater**, enter its MAC address and optionally a name such as Terrace
   or Patio, then accept the disclaimer.
4. Choose the heating controller and cloud or local connection.
5. Optionally select an external room temperature sensor and upstream power switch.
6. Repeat for each heater.

The name becomes the device name, so entity IDs read `climate.patio` rather than
carrying the MAC address; without a name the device is called `Luxeva Heater <MAC>`.
The MAC can be entered with colons, hyphens or without separators. Native MQTT
topics always use uppercase, colon-separated MAC addresses.

### Choose one heating controller

| Controller | Use it when | Behavior |
| --- | --- | --- |
| **Luxeva climate** | You want the integration to regulate room temperature | Select an external sensor; choose target temperature and Level 1–6. Without a sensor, it provides manual level control. It renews `T1` every ten minutes while heating is needed. |
| **Actuator** | You already use an external thermostat helper | Connect the actuator switch to your Generic Thermostat. It arms `T1` on each turn-on and lets that interval expire; it does not periodically renew it. |
| **Compatibility** | You are keeping an existing 1.x installation | Preserves the old climate, timer and actuator behavior. Available to existing entries through Configure. |

The room sensor is selected from your HA temperature sensors. Celsius,
Fahrenheit and Kelvin inputs are converted to Celsius for regulation. Default
hysteresis is ±0.3°C and the minimum interval between normal heating changes is
five minutes; both are configurable. Temperature targets are 5–35°C.

The selected P level is maintained during thermostat cycling. With an external
sensor, `heat` means regulation is enabled even while the device is idle.
The raw `Prg` value reports a selected program, not measured element output;
heating action is an estimate, especially if the device thermostat is enabled.

**Use one controller at a time.** Switching to Luxeva climate requires disabling
any Generic Thermostat helper controlling that actuator. The integration does
not delete or rewrite helpers or automations. In managed modes, attempts to start
through the unselected controller produce an explanatory error. Stop remains
available through either interface. Compatibility mode preserves the old overlap.

### Temperature and loss of data

The built-in `Tmp` reading can be substantially hotter than the room. It is
exposed as **Internal device temperature**, not used for external regulation.
The built-in thermostat is read-only; managed heating sends `H0` so a previous
internal setpoint does not compete with HA control.

Missing, unavailable, nonnumeric, nonfinite or restored room readings prevent
heating. A running heater receives a shutdown request; renewals stop. When a
valid sensor returns, an enabled Luxeva thermostat can evaluate demand again.
An optional maximum sensor-data age uses the last reported time, rather than
requiring the temperature value to change. The default 0 disables age checking.
Choose an age appropriate for the sensor's reporting schedule.

## Timer and safety behavior

In managed modes, **Timer** controls a user session, while **Timer Remaining**
continues to show the physical device countdown for automation compatibility.
**User session remaining** shows the independent HA deadline in minutes.

- Set Timer to 1–9 hours to establish a deadline; this does not itself start an
  off heater. Turn on the chosen controller to begin heating.
- Set Timer to 0 to cancel the session limit while keeping active heating protected.
- Session time includes idle periods. Reaching room temperature does not reset it.
- At session expiry, Luxeva climate regulation is disabled and shutdown is requested.
  In actuator mode, further automatic turn-on requests are rejected until the user
  clears or sets a new session through Timer.
- MQTT timer changes from the app, and detectable timer changes from the IR remote,
  become user sessions. Long native timers are replaced with `T1` after observation.
- Timer renewals require confirmation in fresh device status. An unconfirmed renewal
  stops that heating run and requires a new explicit start in HA. It does not block
  later starts from the remote or app.
- With external-start protection enabled, heating started by the remote or app gets
  one one-hour device interval. HA does not take over or renew it, including after
  a user session has ended.
- Sessions, selected level, target, requested climate mode and the shutdown latch are
  stored per heater. HA restart never restarts a session's full duration. Regulation
  resumes only after valid room input and fresh non-retained heater status arrive.
- Explicit configuration changes end the old session and leave heating off.

The firmware accepts **whole-hour timers only** in the observed protocol. HA
sends `T1` even for the final partial hour and requests shutdown at the exact
session deadline while running (evaluated every five seconds). If HA fails during that final interval, shutdown
can occur after the requested deadline, bounded by the last applied one-hour
countdown. No sub-hour firmware command has been established.

External changes made while HA is unavailable cannot be shortened by HA. IR-only
resets that produce an indistinguishable remaining value cannot be identified
reliably. Command-topic observation catches app timer commands, including repeated
values, but MQTT delivery does not identify the original publisher.

### Optional power-cut safety shutdown

Choose a separate HA `switch` entity supplying power to the heater. It must be
rated for the heater's electrical load. Luxeva actuator switches are rejected.

The device gains **Safety shutdown**, **Reset safety shutdown** and a
**Safety shutdown active** indicator. Pressing Safety shutdown latches control off,
ends the session and requests upstream power-off without waiting for heater MQTT.
The indicator reports whether the upstream switch confirmed off, did not confirm,
or the service call failed. A reported off state is not an independent electrical
measurement.

Safety controls load even when MQTT is unreachable at HA startup.
The latch survives HA restarts. Reset requires the upstream switch to report off;
it only clears the latch. Restore power manually and explicitly start heating.
No automatic power cut or power restoration is implemented. The button requires
HA and the upstream switch to be reachable; the device countdown remains the
fallback when HA is down.

## Local MQTT setup

See [Local MQTT setup](docs/local-mqtt.md) for the shared-service wizard, automatic
Mosquitto preparation, DNS instructions, multiple heaters and troubleshooting.

Cloud and local use the same control policy and native topics. Local mode never
silently falls back to the cloud. No custom broker or Luxeva service app is needed.

## Existing users and Generic Thermostat

Existing config entries, MAC-based device identities and the five original entity
unique IDs are preserved. Existing Generic Thermostat helpers remain external HA
configuration. Compatibility mode keeps their actuator semantics and old timer-zero
shutdown behavior. See [migration instructions](docs/migration.md).

## Protocol reference and validation

- [MQTT command correlation](docs/mqtt-capture.md)
- [PCAP connection contract](docs/pcap-findings.md)
- [Complete infrared protocol](docs/ir-protocol.md), including all nine remote buttons,
  timings, checksum and repeats, verified against 298 captured frames
- [Machine-readable IR code map](docs/ir-codes.json) and [offline decoder](scripts/decode_ir.py)
- [Saved manufacturer manual](docs/manuals/luxeva-pro-smart-smarty-instruction.pdf)

Captured MQTT is plain MQTT 3.1.1 on port 1883, QoS 0, non-retained. Device status
normally arrives about every 1.9 seconds; the firmware requests a 15-second
keepalive. The integration does not synthesize device status or copy the device
client ID; its own HA connection has an independent keepalive. Device status
silence for 30 seconds marks the heater unavailable. Renewals stop while status is
silent; silence alone does not shut the heater down, and the last applied device
countdown remains the fallback.

Automated tests validate software policy and protocol parsing. MQTT power-on from
standby, repeated timer renewal on physical hardware, DNS redirection and power-cut
hardware operation still require acceptance testing before a stable release.
The official app's restriction on starting heating is not proof of the firmware's
MQTT behavior. The beta must not be presented as hardware-validated cloudless control.

## Development

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements_test.txt
.venv/bin/python -m pytest tests --cov=custom_components/luxeva_heater --cov-branch
.venv/bin/ruff check --select E4,E7,E9,F,B custom_components tests
.venv/bin/mypy custom_components/luxeva_heater --ignore-missing-imports --follow-imports skip
```

License: MIT.
