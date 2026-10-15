# Luxeva heater MQTT protocol

This describes the device-facing MQTT protocol of Luxeva Wi-Fi heaters, as
observed on a SMART-FR BLACK in October 2026. It is enough to monitor and control
a heater, or to replace the Luxeva cloud broker with a local one. Evidence and
method: [MQTT capture](mqtt-capture.md) and [PCAP findings](pcap-findings.md).
Other models and firmware versions are untested.

## Connection

| Item | Observed value |
| --- | --- |
| Broker | `iot.luxeva.com.tr`, TCP port 1883, plain MQTT (no TLS) |
| Protocol | MQTT 3.1.1, clean session, no Last Will |
| Device keepalive | 15 seconds |
| Device client ID | `LuxevaClient-xxxx`; the suffix changes between connections |
| Device login | Username `luxeva@us`, password `luxeva@pw`, sent in plain text |
| QoS / retain | QoS 0, not retained, in both directions |

The device resolves the broker hostname through DNS, which is what makes local
redirection possible (see [Local MQTT setup](local-mqtt.md)). The login was the
same on two captured connections of one heater; whether it is universal across
models is not established. The cloud broker also accepts anonymous subscribers.

## Topics

`<MAC>` is the heater's MAC address in uppercase, colon-separated hexadecimal,
for example `AA:BB:CC:DD:EE:01`.

| Topic | Direction | Content |
| --- | --- | --- |
| `outTopic/<MAC>` | heater → broker | Status, about every 1.9 seconds |
| `inTopic/<MAC>` | broker → heater | Commands; the heater subscribes |
| `OTA_Ready/<MAC>` | broker → heater | Subscribed by the heater; no message observed, purpose unknown |

MQTT does not identify a message's publisher: a command on `inTopic` may come from
the app, Home Assistant or anything else with access to the broker.

## Status message

Plain ASCII, no JSON:

```text
Msg 1353, Prg 1, Tmp 33, Hts 29, Tmr 02:59
```

| Field | Meaning |
| --- | --- |
| `Msg` | Sequence-like counter. Reset to 1 was observed on a new connection. Not an acknowledgement ID. |
| `Prg` | Selected heating level `1`–`6`, or `0` for standby. A selected level, not measured output: the element may be cycling under the device thermostat. |
| `Tmp` | Reading of the device's built-in temperature sensor, °C. Substantially hotter than the room. |
| `Hts` | Device thermostat setpoint in °C, `00` when disabled. |
| `Tmr` | Remaining countdown `HH:MM`, `00:00` when no timer is active. |

The integration accepts only complete messages with `Prg` 0–6 and minutes 0–59.

## Commands

Plain ASCII payloads on `inTopic/<MAC>`. All observed families are absolute settings.

| Command | Effect | Observed |
| --- | --- | --- |
| `B1`–`B6` | Select heating level P1–P6 | `Prg` changes accordingly; selecting the current level changes nothing |
| `B0` | Standby (off) | `Prg 0`; also clears an active timer |
| `T1`–`T9` | Countdown of 1–9 hours | Reported as `HH:59` right away, e.g. `T2` → `01:59` |
| `T0` | Cancel the countdown | `Tmr 00:00`; heating continues |
| `H18`–`H37` | Device thermostat setpoint in °C | `Hts` changes accordingly (manual range; `H28`, `H29` captured) |
| `H0` | Disable the device thermostat | `Hts 00` |

Notes:

- Status confirmed the commands within 0.34–1.68 seconds in the captures.
- A `T2` sent in standby did not start a countdown. When the countdown expires,
  the heater goes to standby.
- The official app cannot switch the heater on from standby; the user has to use
  the remote. Whether the firmware accepts `B1`–`B6` from standby has not been
  verified on hardware.
- The physical remote sends infrared only; remote button presses appear as status
  changes, never as `inTopic` commands. See the [infrared protocol](ir-protocol.md).
- The manual documents levels P1–P6, timers 0–9 h and thermostat 18–37 °C. These
  are manual ranges, not exhaustively tested MQTT acceptance ranges.

## How this integration uses the protocol

- Its own client ID is derived from the heater MAC without separators; it never
  copies the device's `LuxevaClient-` ID, and it uses its own keepalive.
- It subscribes to `outTopic/<MAC>`, and in the managed modes also to
  `inTopic/<MAC>` to recognize app commands. Its own publications are recognized
  by their echo and ignored.
- Retained messages are ignored, so stale status can never make a heater available.
- 30 seconds without status marks the heater unavailable.
- Command policy (when `T1`, `B0` or `H0` is sent) is described in the
  [design document](design.md).
