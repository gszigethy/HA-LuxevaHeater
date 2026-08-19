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
| Set thermostat temperature (17–37 °C) | Climate → Target temperature | Drag to 18–37 to enable; drag to minimum (17) to disable |
| View in-device thermostat status | Thermostat (sensor) | Shows active setpoint (`18 °C`–`37 °C`) or `Disabled` |
| View current room temperature | Climate → Current temperature | Live reading from the device's built-in sensor |
| View heating action (Heating / Idle / Off) | Climate → HVAC action | Derived from heater state + thermostat |
| Set auto-off countdown (0–9 h) | Timer (number) | Sends T0–T9 to the device; 0 cancels the timer |
| View remaining countdown (hours) | Timer (number) | Shows remaining whole hours; 0 = no active timer |
| View remaining countdown (precise) | Timer Remaining (sensor) | Exact remaining minutes from the device, updates every ~2 s |

### Example use cases

**Night-time comfort schedule**
Use an automation to set the heater to Level 2 at 21:00 with a 9-hour auto-off timer so it shuts off by 06:00 regardless.

**Eco thermostat**
Set a target temperature of 21 °C so the heater stays at Level 3 but stops heating once the room is warm enough, resuming if the temperature drops.

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

Each device provides four entities:

### Climate (`climate.luxeva_heater_00aa11bb22cc`)

| Attribute | Values | Description |
|---|---|---|
| HVAC mode | `off`, `heat` | Master power switch |
| Preset mode | `Level 1` – `Level 6` | Heating intensity |
| Target temperature | `17`–`37 °C` | Thermostat setpoint; `17` = thermostat disabled (slider off position) |
| Current temperature | °C | Room temperature from device sensor |
| HVAC action | `off`, `heating`, `idle` | What the heater is actively doing right now |
| `timer` attribute | `HH:MM` | Raw countdown string (useful in automations) |
| `msg_sequence` attribute | integer | Sequence counter from the device (for debugging) |

**Thermostat behaviour:** The temperature slider runs from 17 to 37 °C. The bottom stop (17) is the off position — dragging there sends `H17` and the device disables its thermostat (`Hts 00`). Dragging to any value from 18 to 37 enables the thermostat at that setpoint. Setting a temperature while the heater is off automatically turns it on first (at the last used level), because the device ignores `H` commands when `Prg == 0`.

The **Thermostat sensor** (`sensor.luxeva_heater_00aa11bb22cc_thermostat`) reads the `Hts` field from the device's outTopic every ~2 s and reports the current state back independently of the slider. It shows `Disabled` when the thermostat is off, or the active setpoint (e.g. `22 °C`) when enabled. This lets you verify at a glance — and in automations — whether the in-device thermostat is actually running, regardless of what the slider position shows.

### Timer (`number.luxeva_heater_00aa11bb22cc_timer`)

| Attribute | Values | Description |
|---|---|---|
| Value | `0`–`9` hours | Set `1`–`9` to start a countdown; `0` sends T0 to cancel |

Setting the timer to `1`–`9` publishes T1–T9 to the device. If the heater is off when the timer is set, it is automatically turned on at the last used level first — so setting the timer alone is enough to start a timed heating session. Setting the value to `0` sends T0 to cancel an active timer. The displayed value tracks the remaining time rounded up to the nearest whole hour, and resets to 0 automatically when the device timer expires.

### Thermostat (`sensor.luxeva_heater_00aa11bb22cc_thermostat`)

| Attribute | Values | Description |
|---|---|---|
| State | `Disabled` / `18 °C`–`37 °C` | In-device thermostat setpoint, or `Disabled` when off |

Read-only sensor updated every ~2 s directly from the device's `Hts` field. The state is `Disabled` whenever `Hts 00` is reported — this happens at startup, when `H17` is sent via the climate slider, or when the heater is turned off (`B0` resets the thermostat). Use this sensor in automations or dashboards to confirm the thermostat is genuinely active on the device, not just the slider position.

### Timer Remaining (`sensor.luxeva_heater_00aa11bb22cc_timer_remaining`)

| Attribute | Values | Description |
|---|---|---|
| Value | `0`–`540` minutes | Exact remaining minutes from the device; 0 = no active timer |

Read-only sensor updated every ~2 s directly from the device's outTopic `Tmr` field. Useful in automations where minute-level precision matters (e.g. trigger when less than 10 minutes remain).

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

```yaml
# Eco mode: set thermostat to 22 °C on Level 2
action:
  - service: climate.set_temperature
    target:
      entity_id: climate.luxeva_heater_00aa11bb22cc
    data:
      temperature: 22
      # The integration turns the heater on at the last used level first if needed
  - service: climate.set_preset_mode
    target:
      entity_id: climate.luxeva_heater_00aa11bb22cc
    data:
      preset_mode: "Level 2"
```

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
    ├── LuxevaClimate             ← climate entity (power, level, thermostat, temp)
    ├── LuxevaTimer               ← number entity (countdown timer, hours)
    ├── LuxevaTimerSensor         ← sensor entity (countdown timer, precise minutes)
    └── LuxevaThermostatSensor    ← sensor entity (in-device thermostat state)
```

### MQTT protocol

| Parameter | Value |
|---|---|
| Broker | `iot.luxeva.com.tr:1883` |
| Transport | Plain TCP (no TLS) |
| Authentication | None |
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
| `H17` | Disable thermostat (device reports `Hts 00`) |
| `H18`–`H37` | Enable thermostat at setpoint in °C (requires heater to be on) |

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

**Temperature jumps unexpectedly**
- The `Tmp` field is the room temperature from the device's sensor. It can fluctuate if the sensor is near a heat source.

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
