# MQTT correlation capture

`scripts/capture_mqtt.py` is a passive subscriber for one Luxeva heater. It
records both `inTopic/<MAC>` commands and `outTopic/<MAC>` status from
`iot.luxeva.com.tr:1883`, verified by a successful live subscription and device status capture.
It sends no application commands, sets no will, and uses no wildcard topics.
The client ID is randomly generated and does not reuse the device/app/HA ID.
Subscriptions use QoS 0 with a clean MQTT 3.1.1 session. Disconnects and
reconnections are logged; messages during an outage may be missed.

## Run

Install `paho-mqtt` into a Python environment (1.6 or 2.x supported), then:

```bash
mkdir -p .local/mqtt/session
printf '%s\n' 'baseline' > .local/mqtt/session/label.txt
python3 scripts/capture_mqtt.py --mac AA:BB:CC:DD:EE:FF \
  --output .local/mqtt/session/traffic.jsonl \
  --label-file .local/mqtt/session/label.txt
```

Replace the example MAC with the device identifier verified in Home Assistant.
The collector successfully connected without a username or password.
Confirm a successful CONNACK, SUBACK for both topics, and fresh non-retained
status before beginning. Accepted subscriptions alone do not prove that an
app publishes its commands to the expected topic; the first controlled app
action must establish that.

The ignored `.local/` directory holds private captures. The script creates
new output files with owner-only permissions. Raw topics contain the real
device MAC; anonymize selected evidence before placing it under `captures/`.

## Evidence format

JSONL records include UTC receive time, host monotonic time, event type,
session label, actual topic, command/status direction, exact payload in
base64, decoded text, QoS, retained/duplicate flags, parsed status, and changes
relative to the previous status. All messages are retained in the file even
when the console prints only changed states and commands. Status fields are
`Msg`, `Prg`, `Tmp`, `Hts`, and `Tmr`; unrecognized payloads remain in the raw
record. Connection, subscription, disconnection, and shutdown events are also
preserved. Host receive time is not an application send timestamp.

## Controlled correlation

1. Record the baseline, the app screen, and the visible value before an action.
2. Set the label file before changing one setting in the Android app.
3. Record the exact user action and selected value, then allow several status
   updates. Compare command payloads with subsequent state changes.
4. Repeat values and boundaries to distinguish absolute commands from
   relative actions, normalization, cancellation, and unrelated periodic data.
5. For physical-remote tests, label the IR and MQTT captures consistently and
   keep the remote pointed at the heater as well as the capture receiver.
   A remote used only near the ESP32 cannot establish the heater's MQTT response.
6. Preserve unmatched actions, absent commands, and delayed updates as results
   rather than filling in an expected mapping.

MQTT 3.1.1 delivery to a subscriber does not identify the publishing client.
An `inTopic` message may come from the app, Home Assistant, or another source.
Controlled actions support correlation, not publisher identity proof. The
user identified the initial `T1` and resulting one-hour timer as interference
from HA, then disabled the integration before controlled app testing. Exclude
that action from the app and remote mappings. Other unmatched commands remain
unattributed. The capture tool does not change HA configuration.

These observations can inform a later local replacement. This collector
does not redirect the heater, replace a broker, emulate an app backend,
publish control commands, or establish cloudless operation by itself.


## Official app observations — 2026-10-15

Evidence comes from controlled user actions in the official Luxeva app and
passive MQTT capture, with the HA integration disabled. No integration control
logic is used to infer the command mapping. The user confirms the app exposes
only heating level, thermostat, and timer. The official app cannot power on
the heater; the user must first turn it on using the physical remote. This is
an observed app restriction, not proof that the device rejects all MQTT
requests to start from standby.

Commands are ASCII payloads without a JSON envelope, sent on
`inTopic/<MAC>`. Device status arrives on `outTopic/<MAC>`. MAC formatting is
uppercase colon-separated hexadecimal. For example:

```text
Msg 1353, Prg 1, Tmp 33, Hts 29, Tmr 02:59
```

| App action | Command | Observed response | Evidence |
| --- | --- | --- | --- |
| Select P1 while already on | `B1` | `Prg 1` remains unchanged | Captured; redundant level selection |
| Select P2 | `B2` | `Prg 1` → `Prg 2` | Captured |
| Select P3 | `B3` | `Prg 2` → `Prg 3` | Captured |
| Select P4/P5/P6 | `B4`/`B5`/`B6` | Corresponding heating level | Confirmed |
| Power off | `B0` | `Prg 1` → `Prg 0`; active timer cleared | Captured |
| Timer off | `T0` | `Tmr 00:56` → `00:00` | Captured |
| Timer 2 hours | `T2` | `Tmr 00:00` → `01:59` | Captured while on |
| Timer 3 hours | `T3` | `Tmr 00:00` → `02:59` | Captured while on |
| Thermostat 28°C | `H28` | `Hts 00` → `28` | Captured |
| Thermostat 29°C | `H29` | `Hts 00` → `29` | Captured |
| Thermostat off | `H0` | `Hts 28` → `00` | Captured |

The observed families support absolute settings `B<level>`, `T<hours>`, and
`H<temperature>`. Heating levels P1–P6 are confirmed. The manual documents
P1–P6, timer 0–9 hours, and thermostat 18–37°C plus disabled; these are manual
ranges, not exhaustively tested MQTT acceptance ranges. See the saved
[manual](manuals/luxeva-pro-smart-smarty-instruction.pdf), printed pages 14–16.

`Prg` correlates with selected power level/standby, `Tmp` with reported
current temperature, `Hts` with thermostat setpoint (zero disabled), and `Tmr`
with remaining hours/minutes (zero inactive). `Prg` remained 1 with `Tmp 33`
and `Hts 29`; therefore it must not be treated as proof of instantaneous
heating output. `Msg` is an observed sequence-like number; a reset to 1 was
captured, but its cause and persistence semantics are unproven.

Non-retained status usually arrived approximately every 1.9 seconds. Measured
command-to-first-confirming-status delays for the controlled examples were
0.34–1.68 seconds; these are subscriber receive intervals, not guaranteed
latency. Setting 2 or 3 hours immediately reported 01:59 or 02:59 respectively;
exact countdown rounding is unproven. A `T2` captured while `Prg 0` did not
produce an active timer in the observed status. This single observation does
not establish every standby command rule.

Turning off with `B0` cleared an active timer from 01:58 to 00:00. Thermostat
was already disabled, so persistence of an enabled thermostat across off/on
remains untested. Physical remote Power produced `Prg 0` → `1` without an
accompanying MQTT command in the capture. Remote buttons send IR actions;
they are not demonstrated to publish the app's command payloads. Further IR
to status correlation is separate from the captured IR protocol specification.

Private raw evidence and user annotations are stored under
`.local/mqtt/2026-10-15/`. No cloudless broker replacement, outbound replay,
or device network redirection has been tested in this session.
