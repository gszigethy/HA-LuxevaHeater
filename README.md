# Luxeva Heater for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![Home Assistant 2026.9.4+](https://img.shields.io/badge/Home%20Assistant-2026.9.4%2B-blue)](https://www.home-assistant.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Control and monitor **Luxeva Wi-Fi infrared heaters** (such as the SMART-FR
series) from Home Assistant, through the Luxeva cloud or your own local MQTT
broker.

The official app only sets a heating level, timer and the heater's built-in
thermostat, and that thermostat measures the heater's own temperature rather than
the room's. This integration turns the heater into a proper room thermostat
using any HA temperature sensor, and always keeps a safety countdown running on
the device: if Home Assistant or the network fails, the heater switches itself
off within an hour.

> [!WARNING]
> **Remotely operating a heater can cause fire, injury or property damage.**
> Use it only with heaters suitable for unattended operation, keep combustible
> materials away, and follow the manufacturer's instructions. You accept these
> risks during setup. Version 2.0 is a beta that has not yet been fully tested on
> hardware; see the [release notes](CHANGELOG.md).

> [!NOTE]
> This is an independent community project. It is **not affiliated with, endorsed
> by or supported by Luxeva** or its manufacturer. "Luxeva" is used only to identify
> compatible devices. Use of the Luxeva cloud remains subject to Luxeva's terms.

## Features

- **Room thermostat**: heat/off, target temperature and heating level P1–P6 in one
  climate entity, regulated by an external sensor of your choice.
- **Safety countdown**: a one-hour device timer renewed while heating, so a lost
  connection always ends in shutdown.
- **Timer sessions** of up to nine hours that survive HA restarts.
- **Generic Thermostat support** through an actuator switch, for existing setups.
- **Cloudless operation** with a local MQTT broker shared by several heaters.
- **Safety shutdown** that cuts power through a separate smart plug or relay.
- Live device state, also reflecting changes made with the remote or the app.

## Requirements

- Home Assistant 2026.9.4 or newer.
- A heater already connected to Wi-Fi with the official Luxeva app.
- The heater's MAC address, printed on its label.

## Installation

**HACS (recommended)**

1. In HACS, search for **Luxeva Heater**. If it is not listed, add
   `https://github.com/gszigethy/HA-LuxevaHeater` under **⋮ → Custom repositories**
   with type **Integration**.
2. Download it. Beta versions appear when **Show beta versions** is enabled for the
   repository.
3. Restart Home Assistant.

**Manual**: copy `custom_components/luxeva_heater` into your configuration's
`custom_components` folder and restart Home Assistant.

## Configuration

Go to **Settings → Devices & services → Add integration → Luxeva Heater**, choose
**Heater**, and enter:

1. **MAC address**, with or without separators, and an optional **name** such as
   Terrace or Patio. The name becomes the device name, so entity IDs read
   `climate.patio`.
2. Accept the safety disclaimer.
3. Heater settings:

| Setting | Description |
| --- | --- |
| Heating controller | **Luxeva climate** (recommended) regulates by itself. **Actuator** is for an existing Generic Thermostat helper. |
| Connection | Luxeva cloud, or a Local MQTT service you added first. |
| External room temperature sensor | Enables temperature regulation. Leave empty for manual level control. |
| Upstream power switch | Optional plug or relay that powers the heater; enables safety shutdown. |
| Temperature tolerance | Hysteresis around the target, default ±0.3 °C. |
| Minimum time between heating changes | Default 300 seconds. |
| Maximum sensor reading age | Stop heating if the sensor stops reporting; 0 disables the check. |
| Safety timer for remote/app starts | Give heating started outside HA a one-hour countdown. |

Add each heater separately. Change these settings later with **Configure**; saving
ends the current heating session and leaves the heater off.

Use only one controller per heater: before switching to Luxeva climate, turn off
any Generic Thermostat helper that controls it.

### Local MQTT (cloudless)

Add **Luxeva Heater → Local MQTT service** once, optionally letting it install and
prepare the Mosquitto app, then select it in each heater's settings. You must
redirect `iot.luxeva.com.tr` to your broker in your own DNS. See
[Local MQTT setup](docs/local-mqtt.md).

## Entities

| Entity | Description |
| --- | --- |
| Climate | Heat/off, level P1–P6 (preset) and, with a sensor, target temperature |
| Timer | User session of 0–9 hours; 0 cancels the limit |
| Timer Remaining | Device countdown, in minutes |
| User session remaining | Time left until the session deadline, in minutes |
| Thermostat | Device thermostat setpoint, or Disabled |
| Internal device temperature | The heater's own sensor (diagnostic, reads hotter than the room) |
| Actuator | On/off switch for a Generic Thermostat helper |
| Safety shutdown, Reset safety shutdown, Safety shutdown active | Only with an upstream power switch |

How these behave in detail (regulation, renewals, sessions, restarts, power cut)
is described in the [design document](docs/design.md).

## Upgrading from 1.x

Existing heaters keep working unchanged in **Compatibility** mode, with the same
entity IDs. New features are opt-in through **Configure**. Do not remove and re-add
your heaters. See the [migration guide](docs/migration.md).

## Documentation

| Document | Contents |
| --- | --- |
| [Release notes](CHANGELOG.md) | What changed in each version |
| [Migration guide](docs/migration.md) | Moving from 1.x, behavior changes, rollback |
| [Local MQTT setup](docs/local-mqtt.md) | Shared broker, Mosquitto preparation, DNS, troubleshooting |
| [Design](docs/design.md) | Functional and technical design: control modes, safety timer, sessions, power cut |
| [MQTT protocol](docs/mqtt-protocol.md) | Topics, status format, commands, connection details |
| [Infrared protocol](docs/ir-protocol.md) | Complete remote control specification, timings, checksum, encoder and decoder |
| [IR code map](docs/ir-codes.json) | Machine-readable button codes |
| [MQTT capture](docs/mqtt-capture.md) | How the MQTT commands were captured and correlated |
| [PCAP findings](docs/pcap-findings.md) | Device network behavior and connection details |
| [IR research](docs/ir-research.md) | How the remote was captured and identified |
| [IR captures](captures/smart-fr/2026-10-15/README.md) | Raw captured frames and decoding results |
| [Manufacturer manual](docs/manuals/luxeva-pro-smart-smarty-instruction.pdf) | Original heater manual; the remote is on printed page 14 |

## Troubleshooting

Enable debug logging and check **Settings → System → Logs**:

```yaml
logger:
  logs:
    custom_components.luxeva_heater: debug
```

A heater becomes unavailable after 30 seconds without status messages. Check that it
is powered and online, and for local MQTT, that DNS points it at your broker.

## Development

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements_test.txt
.venv/bin/python -m pytest tests --cov=custom_components/luxeva_heater --cov-branch
.venv/bin/ruff check --select E4,E7,E9,F,B custom_components tests
.venv/bin/mypy custom_components/luxeva_heater --ignore-missing-imports --follow-imports skip
```

## Credits

- [IrpTransmogrifier](https://github.com/bengtmartensson/IrpTransmogrifier) by
  Bengt Mårtensson, whose protocol database identified the remote's encoding.
- [IRremoteESP8266](https://github.com/crankyoldgit/IRremoteESP8266), used for
  comparison during IR analysis.
- [Eclipse Paho](https://eclipse.dev/paho/) MQTT client,
  [ESPHome](https://esphome.io) for the IR capture firmware,
  [Home Assistant](https://www.home-assistant.io) and [HACS](https://hacs.xyz).
- The heater manual is the manufacturer's document, retrieved from a public source
  and included unmodified for reference.

## License

[MIT](LICENSE). The manufacturer's manual and third-party references remain the
property of their respective owners.
