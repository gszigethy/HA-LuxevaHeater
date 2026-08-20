# Luxeva Heater

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2024.3%2B-blue)](https://home-assistant.io)
[![IoT Class](https://img.shields.io/badge/IoT%20Class-Cloud%20Push-green)](https://developers.home-assistant.io/docs/creating_integration_manifest#iot-class)

Control and monitor your **Luxeva WiFi infrared carbon heater** from Home Assistant. The integration connects to Luxeva's cloud MQTT broker and provides real-time two-way control — changes made on the physical remote are reflected in HA instantly, and HA commands take effect immediately.

---

## What you can do

| Capability | Entity | Notes |
|---|---|---|
| Turn on / off | Climate | Sets heater to the last used level or turns it off |
| Set heating level (1–6) | Climate → Preset mode | Level 1 = lowest, Level 6 = highest intensity |
| View in-device thermostat status | Thermostat (sensor) | Shows active setpoint (`18 °C`–`37 °C`) or `Disabled` |
| View current room temperature | Climate → Current temperature | Live reading from the device's built-in sensor |
| View heating action (Heating / Idle / Off) | Climate → HVAC action | Derived from heater state + thermostat |
| Set auto-off countdown (0–9 h) | Timer (number) | Sends T0–T9 to the device; 0 cancels the timer and turns the heater off |
| View remaining countdown (hours) | Timer (number) | Shows remaining whole hours; 0 = no active timer |
| View remaining countdown (precise) | Timer Remaining (sensor) | Exact remaining minutes from the device, updates every ~2 s |
| Simple on/off actuator for Generic Thermostat | Actuator (switch) | Arms a 1-hour safety timer on each turn-on; designed for use with HA's Generic Thermostat helper |

### Example use cases

**Night-time comfort schedule**
Use an automation to set the heater to Level 2 at 21:00 with a 9-hour auto-off timer so it shuts off by 06:00 regardless.

**Follow the remote**
No configuration needed — when someone changes the level with the physical remote, the HA entity updates within 2 seconds and automations react to the real device state.

**Energy monitoring**
Use HA's energy dashboard together with a smart plug on the heater circuit. The integration exposes the current level (1–6) as a preset so you can correlate power draw with heating intensity in dashboards.

---

## Requirements

- Home Assistant 2024.3 or newer
- The Luxeva heater must be connected to the Luxeva mobile app (Wi-Fi provisioning done via the app)
- The device MAC address (from the label on the unit)

---

## Installation

### Via HACS (recommended)

1. In Home Assistant: **HACS → Integrations → ⋮ → Custom repositories**
2. Add URL: `https://github.com/gszigethy/luxeva_heater`  Type: **Integration**
3. Find **Luxeva Heater** in HACS and click **Download**
4. Restart Home Assistant

### Manual

1. Copy the `custom_components/luxeva_heater/` folder into your HA config directory under `custom_components/`
2. Restart Home Assistant

---

## Setup

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Luxeva Heater**
3. Enter the **MAC address** from the sticker on your heater
   - Accepted formats: `00:AA:11:BB:22:CC`, `00-AA-11-BB-22-CC`, or `00AA11BB22CC`
4. Read and accept the **safety disclaimer**
5. Click **Submit** — the device appears immediately and begins receiving live updates

> **Multiple heaters:** Run the setup flow once per device MAC address. Each heater becomes a separate device in HA.

---

## Entities

Each device provides five entities:

### Climate (`climate.luxeva_heater_00aa11bb22cc`)

| Attribute | Values | Description |
|---|---|---|
| HVAC mode | `off`, `heat` | Master power switch |
| Preset mode | `Level 1` – `Level 6` | Heating intensity |
| Current temperature | °C | Room temperature from device sensor |
| HVAC action | `off`, `heating`, `idle` | What the heater is actively doing right now |
| `timer` attribute | `HH:MM` | Raw countdown string (useful in automations) |
| `msg_sequence` attribute | integer | Sequence counter from the device (for debugging) |

The in-device thermostat (`Hts`) is not controlled from HA. It can still be set via the physical remote or the Luxeva app; the **Thermostat sensor** reports its current state.

> **Why thermostat control is not implemented**
>
> The heater's built-in temperature sensor (`Tmp`) is located inside the unit, close to the heating element. It reads significantly higher than actual room temperature — typically by 10–20 °C or more depending on the heating level and airflow. Because the device's own thermostat compares against this sensor, setting a target of e.g. 21 °C causes the heater to shut off long before the room reaches that temperature, making the feature practically unusable.
>
> For this reason, thermostat control has been intentionally omitted from the integration. The `Tmp` reading is still surfaced as the climate entity's current temperature for reference, but should not be treated as an accurate room temperature.
>
> **Recommended alternative:** use Home Assistant's built-in [Generic Thermostat](https://www.home-assistant.io/integrations/generic_thermostat/) helper with a dedicated external room temperature sensor (Zigbee, Z-Wave, Bluetooth, etc.) placed away from the heater. Use the **Actuator switch** (see below) as the `heater` entity — it is specifically designed for this purpose and includes a 1-hour safety timer. See the [Using with Generic Thermostat](#using-with-generic-thermostat) section for a complete example.

### Timer (`number.luxeva_heater_00aa11bb22cc_timer`)

| Attribute | Values | Description |
|---|---|---|
| Value | `0`–`9` hours | Set `1`–`9` to start a countdown; `0` sends T0+B0 to cancel and turn off |

Setting the timer to `1`–`9` publishes T1–T9 to the device. If the heater is off when the timer is set, it is automatically turned on at the last used level first — so setting the timer alone is enough to start a timed heating session. Setting the value to `0` sends T0 followed by B0: the timer is cancelled and the heater is turned off, matching the behaviour when the device's own timer expires naturally. The displayed value tracks the remaining time rounded up to the nearest whole hour, and resets to 0 automatically when the device timer expires.

### Thermostat (`sensor.luxeva_heater_00aa11bb22cc_thermostat`)

| Attribute | Values | Description |
|---|---|---|
| State | `Disabled` / `18 °C`–`37 °C` | In-device thermostat setpoint, or `Disabled` when off |

Read-only sensor updated every ~2 s directly from the device's `Hts` field. The state is `Disabled` whenever `Hts 00` is reported — this happens at startup, when the thermostat is cleared via the physical remote or app, or when the heater is turned off (`B0` resets the thermostat on the device). Use this sensor in automations or dashboards to confirm the thermostat is genuinely active on the device.

### Timer Remaining (`sensor.luxeva_heater_00aa11bb22cc_timer_remaining`)

| Attribute | Values | Description |
|---|---|---|
| Value | `0`–`540` minutes | Exact remaining minutes from the device; 0 = no active timer |

Read-only sensor updated every ~2 s directly from the device's outTopic `Tmr` field. Useful in automations where minute-level precision matters (e.g. trigger when less than 10 minutes remain).

### Actuator (`switch.luxeva_heater_00aa11bb22cc_actuator`)

| Attribute | Values | Description |
|---|---|---|
| State | `on` / `off` | Mirrors the heater's power state (`Prg > 0` = on) |

A plain on/off switch designed to serve as the `heater` entity in HA's [Generic Thermostat](https://www.home-assistant.io/integrations/generic_thermostat/) helper. Unlike the Climate entity, it presents the heater as a simple binary actuator, which is what Generic Thermostat expects.

**Turn-on:** publishes `B<last_level>` (restores the last used heating level) then `T1` (arms a 1-hour safety countdown timer).
**Turn-off:** publishes `T0` (cancels the timer) then `B0` (turns the heater off).

**1-hour heartbeat:** when the device timer expires, the device turns itself off and the Actuator reports `off`. If a Generic Thermostat is in heating mode and the setpoint has not been reached, it calls turn-on again — restarting the 1-hour timer. This loop continues until the setpoint is reached or the Generic Thermostat is turned off. If the cloud MQTT connection drops instead, the device shuts off within one hour on its own without any input from HA.

**External turn-on safety:** if the device is turned on via the physical remote or the Luxeva app while the Actuator is off, and no timer is active on the device, the Actuator automatically publishes `T1` to arm the safety timer. This ensures the cloud-loss safety property holds regardless of how the heater was started.

> **Note:** when using the Actuator with Generic Thermostat, avoid controlling the heater directly via the Climate entity or Timer number entity at the same time. Generic Thermostat tracks the switch state independently, and direct commands from other entities can cause state inconsistencies.

---

## Automation examples

```yaml
# Set Level 3 and a 2-hour timer every weekday morning
# (setting the timer also turns the heater on if it was off)
automation:
  alias: "Morning warmup"
  trigger:
    - platform: time
      at: "06:30:00"
  condition:
    - condition: time
      weekday: [mon, tue, wed, thu, fri]
  action:
    - service: climate.set_preset_mode
      target:
        entity_id: climate.luxeva_heater_00aa11bb22cc
      data:
        preset_mode: "Level 3"
    - service: number.set_value
      target:
        entity_id: number.luxeva_heater_00aa11bb22cc_timer
      data:
        value: 2
```

---

## Using with Generic Thermostat

The **Actuator switch** is designed to act as the `heater` entity in HA's [Generic Thermostat](https://www.home-assistant.io/integrations/generic_thermostat/) helper. This is the recommended way to implement room-temperature-based control with the Luxeva heater.

> **Why not use the Climate entity directly?** Generic Thermostat's `heater` parameter expects a switch entity — it calls `turn_on` and `turn_off` and tracks the switch state. The Luxeva Climate entity is a full climate entity and cannot be used as a Generic Thermostat heater. The Actuator switch bridges this gap.

> **Which temperature sensor to use:** use a dedicated external room temperature sensor as `target_sensor`. Do **not** use the Climate entity's current temperature — the device's built-in sensor reads well above actual room temperature (see the note in the Climate entity section).

### Configuration example

```yaml
climate:
  - platform: generic_thermostat
    name: "Living Room"
    heater: switch.luxeva_heater_00aa11bb22cc_actuator
    target_sensor: sensor.living_room_temperature   # external sensor, not the Luxeva Tmp
    min_temp: 17
    max_temp: 28
    target_temp: 21
    min_cycle_duration:
      minutes: 5
    cold_tolerance: 0.3
    hot_tolerance: 0.3
```

### How the 1-hour heartbeat works

1. Generic Thermostat calls `turn_on` → Actuator sends `B<last_level>` + `T1` (heater on, 1-hour countdown armed)
2. Device heats; Generic Thermostat monitors room temperature via the external sensor
3. If the room reaches setpoint before the timer expires: Generic Thermostat calls `turn_off` → Actuator sends `T0` + `B0`
4. If the timer expires before setpoint is reached: device turns itself off → Actuator reports `off` → Generic Thermostat calls `turn_on` again → 1-hour timer restarts

**`min_cycle_duration`:** set this to at least 5 minutes. Without it, Generic Thermostat may re-trigger turn-on immediately when the timer expires, preventing the room temperature from stabilising between cycles. Adjust higher if the heater takes a long time to affect room temperature.

---

## Availability

The integration marks the device **unavailable** if no status message is received for **30 seconds**. The device normally publishes its state every ~2 seconds, so 30 seconds means it is genuinely unreachable (network loss, power cut, or cloud broker outage). The entity becomes available again automatically once messages resume — no restart needed.

---

## Technical design

### Architecture

```
Home Assistant
└── LuxevaConfigEntry (runtime_data = LuxevaCoordinator)
    ├── LuxevaCoordinator         ← MQTT client + state store
    │   ├── paho-mqtt client      ← persistent TCP connection to Luxeva cloud
    │   ├── Listener callbacks    ← push notifications to entities
    │   └── 30 s watchdog timer   ← marks device unavailable on silence
    ├── LuxevaClimate             ← climate entity (power, level, current temp)
    ├── LuxevaTimer               ← number entity (countdown timer, hours)
    ├── LuxevaTimerSensor         ← sensor entity (countdown timer, precise minutes)
    ├── LuxevaThermostatSensor    ← sensor entity (in-device thermostat state)
    └── LuxevaActuatorSwitch      ← switch entity (actuator for Generic Thermostat)
```

### MQTT protocol

| Parameter | Value |
|---|---|
| Client ID | Device MAC without colons, e.g. `00AA11BB22CC` |
| Status topic (`outTopic`) | `outTopic/00:AA:11:BB:22:CC` — device publishes every ~2 s |
| Command topic (`inTopic`) | `inTopic/00:AA:11:BB:22:CC` — HA publishes commands here |

**Status message format** (`outTopic`):
```
Msg 1355268, Prg 0, Tmp 33, Hts 00, Tmr 00:00
```

| Field | Meaning | Notes |
|---|---|---|
| `Msg` | Sequence counter | Increments every ~2 s |
| `Prg` | Heating level | `0` = off; `1`–`6` = active level |
| `Tmp` | Current room temperature (°C) | From device's built-in sensor |
| `Hts` | Thermostat setpoint (°C) | `00` = thermostat disabled; `18`–`37` = active |
| `Tmr` | Countdown timer | `HH:MM` remaining; `00:00` = no active timer |

**Command messages** (`inTopic`):

| Command | Effect |
|---|---|
| `B0` | Turn heater off (also resets `Hts` to `00`) |
| `B1`–`B6` | Set heating level 1–6 |
| `T0` | Cancel active timer |
| `T1`–`T9` | Set auto-off countdown (integer hours) |

### Connection management

The integration uses paho-mqtt with `loop_start()` which runs a background thread. Reconnect attempts use exponential back-off (1 s minimum, 30 s maximum). All MQTT callbacks run in paho's thread; state updates and watchdog timer operations are marshalled to the HA event loop via `call_soon_threadsafe`.

The integration does **not** depend on HA's built-in MQTT component — it manages its own connection to the Luxeva cloud broker. This means you do not need to configure MQTT in HA and the integration works alongside an existing HA MQTT setup without conflict.

---

## Troubleshooting

**Entity shows "unavailable"**
- Check that the heater is powered on and connected to Wi-Fi
- Verify the MAC address matches the sticker on the unit (not the router's ARP table)
- The Luxeva app should show the device as online; if it doesn't, the cloud broker is unreachable

**Commands don't reach the device**
- Check HA logs for `Luxeva: cannot publish` warnings — this indicates the MQTT connection dropped
- The integration reconnects automatically; wait ~30 seconds and try again

**Temperature reads high or jumps unexpectedly**
- The `Tmp` field comes from the device's internal sensor, which sits near the heating element and reads well above actual room temperature. This is expected behaviour — see the note in the Climate entity section for context and the recommended alternative.

**Enable debug logging**
Add to `configuration.yaml`:
```yaml
logger:
  logs:
    custom_components.luxeva_heater: debug
    paho: debug
```

---

## License

MIT
