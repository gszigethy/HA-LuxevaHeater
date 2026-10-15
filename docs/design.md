# Design: control, sessions and safety

This document describes how the integration behaves (functional design) and how
it is built (technical design). For the wire formats see the
[MQTT protocol](mqtt-protocol.md) and [infrared protocol](ir-protocol.md).

## Goals

- Model each heater as one Home Assistant climate entity, optionally regulating
  an external room temperature sensor.
- Keep the heater safe when Home Assistant, the network or MQTT disappears: the
  device must stop on its own within one hour.
- Allow the Luxeva cloud to be replaced by a local MQTT broker, with no change to
  the heater's firmware or its native topics.
- Upgrade existing 1.x installations without changing their behavior or entity IDs.

## Architecture

```text
 Luxeva heater ──MQTT──▶ broker (Luxeva cloud or local Mosquitto) ◀──MQTT── HA
   outTopic/<MAC>  status every ~1.9 s                         LuxevaCoordinator
   inTopic/<MAC>   commands B/T/H                                    │
                                                                LuxevaControl
                                                         (one policy per heater)
                                                                     │
                     climate · number · sensors · switch · buttons · binary sensor
```

| Component | Responsibility |
| --- | --- |
| `LuxevaCoordinator` ([coordinator.py](../custom_components/luxeva_heater/coordinator.py)) | One paho-mqtt client per heater. Parses status, publishes commands, marks the heater unavailable after 30 s of silence. Never synthesizes device status. |
| `LuxevaControl` ([control.py](../custom_components/luxeva_heater/control.py)) | The single owner of heating decisions for a heater: thermostat regulation, safety-timer renewal, user sessions and the safety latch. All entities call into it, so they cannot issue conflicting commands. |
| Entities | Thin views and inputs over the coordinator and controller. |
| Local service entry ([local.py](../custom_components/luxeva_heater/local.py)) | Broker address shared by several heaters, optional Mosquitto preparation, broker health sensor. It owns no heater state. |

Each heater is its own config entry and device, identified by its MAC. Several
heaters may share one local service. The controller runs on the HA event loop and
persists its intentions (mode, target, level, session deadline, latch) per heater
in HA storage. It never persists optimistic device state or sensor samples.

## Control modes

One controller owns heating at a time, selected in the heater's configuration.

| Mode | Use it when | Behavior |
| --- | --- | --- |
| **Luxeva climate** | The integration should regulate room temperature | With an external sensor: target temperature and Level 1–6, hysteresis regulation. Without a sensor: manual heat/off and level. Renews `T1` every ten minutes while heating. |
| **Actuator** | An external thermostat helper (Generic Thermostat) regulates | The actuator switch arms `T1` on each turn-on and lets it expire; it does not renew it. |
| **Compatibility** | Existing 1.x installations | Preserves the old climate, timer and actuator behavior. Offered only to migrated entries. |

In the managed modes (climate and actuator), a start through the controller that
was not selected is rejected with an explanation; stop is always accepted. The
integration never edits or deletes Generic Thermostat helpers or automations.

## Thermostat regulation

- Room temperature comes from a selected HA temperature sensor. Celsius, Fahrenheit
  and Kelvin are converted to Celsius.
- Heating starts at or below `target − tolerance` and stops at or above
  `target + tolerance`. The default tolerance is ±0.3 °C; targets are 5–35 °C.
- Normal heating changes are at least the minimum cycle apart (default 300 s).
- The selected level P1–P6 is kept while cycling. `heat` means regulation is
  enabled, including while idle.
- Missing, unavailable, non-numeric, non-finite or restored sensor readings stop
  heating and renewals. When valid readings return, regulation resumes. An
  optional maximum reading age uses the sensor's last-reported time.
- Managed heating sends `H0` to disable the device's own thermostat. The built-in
  `Tmp` reading is exposed as an internal device temperature only: it reads
  substantially hotter than the room, as the manual also notes.

## Safety timer

The heater's only fallback is its own countdown. The integration keeps a one-hour
countdown (`T1`) running whenever it heats:

- Luxeva climate renews `T1` every ten minutes while heating is needed and both
  device and sensor data are valid. If HA, the network or MQTT fails, renewals stop
  and the heater switches itself off within one hour.
- A renewal must be confirmed by fresh device status within 15 seconds. An
  unconfirmed renewal stops that heating run and disables regulation until the
  next explicit start in HA. It does not block later starts from the remote or app.
- A confirmation that was pending when status went silent keeps its original
  deadline; a countdown that has run out never counts as confirmation.
- 30 seconds without status marks the heater unavailable. That alone does not stop
  the heater: renewals stop and the last applied countdown remains the fallback.
- With external-start protection enabled, heating started by the remote or app
  receives one protective `T1` interval. HA does not take over or renew it.
- Shutdown sends `B0` alone, which also clears the device timer. `T0` is never sent
  separately, so a lost `B0` cannot leave the heater running without a countdown.

## User sessions

In the managed modes, the Timer entity sets a user session rather than a native
device timer.

- Timer 1–9 h sets an absolute deadline stored in HA. The device keeps receiving
  one-hour intervals, so the safety timer stays in place. Setting a timer does not
  itself start heating.
- Timer 0 cancels the session limit and keeps active heating protected.
- Session time includes idle periods and survives HA restarts; a restart never
  restarts a session's full duration.
- At the deadline, heating stops and regulation ends. In actuator mode further
  automatic starts are refused until the user clears or replaces the session,
  so a Generic Thermostat cannot immediately undo the deadline.
- Timer commands from the official app, and detectable timer changes from the IR
  remote, become user sessions. HA's own command echoes do not.
- The firmware accepts whole hours only. The exact final partial hour is enforced
  by HA (checked every five seconds); if HA is down then, shutdown happens when the
  last one-hour interval expires.

**Timer Remaining** keeps showing the device countdown; **User session remaining**
shows the HA deadline.

## Restart and reconfiguration

- After a restart, mode, target, level, session deadline and safety latch are
  restored. Regulation resumes only after valid room data and fresh, non-retained
  heater status arrive. An expired session stays off.
- Saving a heater's configuration ends its session and leaves heating off.
- Changing a shared local service suspends its heaters (stop accepted, starts
  refused), then reloads the service and each heater. A failed reload does not
  skip the others; a heater that fails to reload stays off until reloaded.

## Safety shutdown (power cut)

An optional upstream HA `switch` (a plug or relay rated for the heater's load)
adds **Safety shutdown**, **Reset safety shutdown** and **Safety shutdown active**.

- Pressing Safety shutdown latches control off, ends the session and requests the
  upstream switch to turn off without waiting for heater MQTT. A slow or failing
  disk cannot delay the power-off request.
- The indicator reports whether the switch confirmed off, did not confirm, or the
  request failed. A reported off state is not an independent electrical measurement.
- While latched, only stop commands reach the heater, in every mode. The latch
  survives restarts.
- Reset requires the upstream switch to report off and only clears the latch. Power
  is never restored automatically and heating never resumes on its own.
- Activation is manual; there is no automatic power-cut policy.

## Local MQTT service

The local replacement is an ordinary MQTT broker, typically the Mosquitto app.
Heaters keep publishing on their native topics; the integration adds no topic
namespace, MAC rewriting, synthetic status or cloud bridge. Each broker address and
port belongs to one service entry. There is no automatic cloud fallback. Setup,
DNS redirection and troubleshooting are in [Local MQTT setup](local-mqtt.md).

## Known limitations

- Not yet verified on hardware: MQTT start from standby, repeated `T1` renewal, DNS
  redirection to a local broker, and upstream relay behavior.
- IR-only timer resets that leave the remaining time unchanged cannot be detected.
  Long timers set while HA is down cannot be shortened by HA.
- The official app's account and provisioning backend, and the firmware's OTA
  channel, are not implemented.
- HA's storage helper logs write errors instead of raising them, so a failed save
  of the safety latch may not be reported in the UI.
