# Luxeva SMART-FR infrared remote protocol

Specification version 1.0, based on receive-only captures made on 2026-10-15.

This document describes all nine buttons of the handheld remote supplied with
a Luxeva SMART-FR BLACK heater. It provides the information needed to decode
the remote or implement its transmitted waveform on another platform.
The signal format matches the protocol named **Xiaomi** in the
[IrpTransmogrifier protocol database](https://github.com/bengtmartensson/IrpTransmogrifier/blob/master/src/main/resources/IrpProtocols.xml).
That name identifies an encoding; it does not identify the remote manufacturer.

## Scope and evidence

| Item | Evidence/status |
| --- | --- |
| Target appliance | [Luxeva SMART-FR BLACK](https://luxeva.com.tr/product/smart-fr-black/), as identified by its owner |
| Remote | Owner confirmed the layout matches the manual; no remote model/PCB identifier recorded |
| Buttons | All nine captured at least three times; Power captured six times |
| Validation | 298 individual repeat frames pass timing and XOR checksum checks |
| Distinct commands | Nine; an alternating OK/P sequence confirms they differ |
| Receiver | ESP32-PICO-D4, ESPHome 2026.9.1, demodulated input on GPIO32 |
| Carrier | Not measured; 36 kHz is the Xiaomi reference value |
| Transmitter/heater validation | No generated IR was transmitted; heater was not present |
| Other Smart-series models | Compatibility has not been tested |
| Long holds, battery reset, receiver feedback | Not tested |

The manual is saved as
[luxeva-pro-smart-smarty-instruction.pdf](manuals/luxeva-pro-smart-smarty-instruction.pdf).
The remote diagram is on **printed page 14 / PDF page 13**. Function descriptions
are on printed pages 15-16 / PDF pages 14-15. Semantics below come from that
manual; this capture session verified button transmissions, not heater actions.

## Complete button map

`D` is the eight-bit device field, `F` the eight-bit function/command field,
and `C` the four-bit checksum. Hexadecimal values describe numeric fields in
MSB-first transmission order. Full codes include the checksum and are 20 bits.

| Button | D | F | C | Full code | Captured frames |
| --- | --- | --- | --- | --- | --- |
| Power / standby | `0x3C` | `0xCC` | `0xF` | `0x3CCCF` | 55 |
| Up | `0x86` | `0x05` | `0xB` | `0x8605B` | 21 |
| Down | `0x86` | `0x06` | `0x8` | `0x86068` | 22 |
| OK / confirm | `0x86` | `0x0D` | `0x3` | `0x860D3` | 20 |
| P / program | `0x86` | `0x08` | `0x6` | `0x86086` | 28 |
| Timer / clock | `0x86` | `0x07` | `0x9` | `0x86079` | 27 |
| Thermostat / thermometer | `0x86` | `0x04` | `0xA` | `0x8604A` | 27 |
| MAX | `0x86` | `0x0E` | `0x0` | `0x860E0` | 30 |
| MIN | `0x86` | `0x0F` | `0x1` | `0x860F1` | 33 |

The separate OK/P/OK/P confirmation adds 35 frames to the table's 263 frames,
giving 298 total. **Power uses a different device field.** Its full code was
confirmed in two independent sequences; do not force it onto device `0x86`.
The physical meaning of this different device field is unknown.

For machine-readable values, symbol sequences, nominal frames, and measured
representative frames, use [ir-codes.json](ir-codes.json). That file contains
decimal integers alongside explicitly named hexadecimal strings.

## Envelope and timing conventions

A **mark** is a burst of modulated infrared light. A **space** is no light.
The timings below describe this envelope, not individual carrier cycles.
In the raw JSONL captures, positive microseconds are marks and negative
microseconds are spaces. Electrical receiver polarity depends on hardware;
the capture input was configured as inverted. Do not invert the logical symbol
values when using another receiver.

This is a four-level pulse-distance encoding: each data mark has the same
duration, and the following space encodes **two bits**.

| Element | Reference duration, us | Measured min / median / max, us |
| --- | --- | --- |
| Header mark | 1000 | 995 / 1020.5 / 1025 |
| Header space | 580 | 571 / 574 / 599 |
| Data and footer mark | 580 | 572 / 597 / 600 |
| Symbol 0 (`00`) space | 580 | 582 / 585 / 609 |
| Symbol 1 (`01`) space | 870 | 872 / 875 / 900 |
| Symbol 2 (`10`) space | 1160 | 1162 / 1165 / 1190 |
| Symbol 3 (`11`) space | 1450 | 1462 / 1466 / 1491 |
| Complete frame start-to-start | 30000 | 29226 / 29250 / 29284 |
| Inter-frame space | Remaining frame time | 9943 / 11760 / 12366 |

These are observed ranges from this receiver and session, not universal
tolerance limits. Receiver demodulation and clock error affect measured times.
The 264 stored inter-frame gaps provide start-to-start measurements; the last
gap of each press is not reported by the raw logger.

### Carrier

The reference Xiaomi definition specifies **36 kHz**. A demodulating receiver
cannot establish the actual carrier frequency or optical duty cycle. Use
36 kHz as a reference-based starting point for a transmitter, then verify it
with the heater or a carrier measurement. The ESPHome capture firmware's
configured transmitter duty of 50% was unused and supplies no measurement of
the original remote. No transmitter duty cycle is established by this work.

## Frame layout and bit order

```text
header           10 symbols, each carrying 2 bits          footer   idle
+1000, -580       [ +580, -(580 + 290 * symbol) ] x 10      +580     -gap

20-bit value:    DDDDDDDD FFFFFFFF CCCC
bit positions:  19....12 11.....4 3..0
```

Transmit the device byte first, then the command byte, then the checksum nibble.
Within each field, take the most significant two bits first. There are ten
symbols per frame: four device symbols, four command symbols, two checksum
symbols. A frame has **23 durations before idle**, or 24 including its trailing
space. It is not a ten-bit binary frame.

The full integer is:

```text
code = (D << 12) | (F << 4) | C
```

If using a byte buffer for the 20-bit integer, define packing explicitly.
For example, `0x8605B` can be stored as bytes `08 60 5B` in a 24-bit container;
the top four container bits are padding and must not be transmitted. Sending
the string "8605B" or these three bytes as 24 data bits is incorrect.

### Checksum

The checksum is the XOR of the four data nibbles:

```text
C = ((D >> 4) ^ (D & 0x0F) ^ (F >> 4) ^ (F & 0x0F)) & 0x0F
```

For Up: `8 XOR 6 XOR 0 XOR 5 = B`, giving `0x8605B`.
For Power: `3 XOR C XOR C XOR C = F`, giving `0x3CCCF`.
Equivalently, XORing all five transmitted nibbles must produce zero.
The checksum detects some errors; it is not authentication or a CRC.

### Worked Up frame

```text
D = 0x86 = 10 00 01 10
F = 0x05 = 00 00 01 01
C = 0xB  = 10 11
symbols  =  2  0  1  2  0  0  1  1  2  3

Nominal signed durations in microseconds, excluding final idle:
[1000, -580,
 580, -1160, 580, -580, 580, -870, 580, -1160,
 580, -580, 580, -580, 580, -870, 580, -870,
 580, -1160, 580, -1450,
 580]
```

The active nominal frame above takes 17240 us. Add 12010 us idle for a
29250 us start-to-start period, or 12760 us idle for the reference 30000 us
period. The idle depends on the code's symbol durations; it is not a fixed
10 ms delay to append to every command.

## Repeats and one logical button press

Every recorded press consists of multiple complete, identical frames. No
special shortened repeat frame, toggle bit, or changing counter was observed.
The short presses produced 6-13 complete frames per press, with the same
approximately 29.25 ms frame period. The number of repeats varied even when
the button was unchanged. This does not establish long-hold behavior or a
minimum number of frames accepted by the heater.

A transmitter can construct a burst by repeating the complete frame at a
chosen fixed start-to-start period. A starting burst of about 8 frames resembles
these captures, but is not a heater-tested recommendation. Keep frame count
and period configurable. Do not automatically retry Power until its behavior
on the heater has been checked: the manual describes one power/standby button,
not separate, idempotent on and off codes.

A receiver should expose both individual decoded frames and, if useful, a
separate logical press event. Repeated frames about 29.25 ms apart belong to
the same observed burst. The session's presses were intentionally separated
by about two seconds; no general debounce or key-release threshold was
established. Choose and document a grouping policy instead of interpreting
every repeat as another human press.

## Portable waveform generator

The following Python uses only the standard language. It creates an envelope;
it does not access hardware. A hardware adapter must generate the carrier
during positive durations and turn the LED off during negative durations.
The final space makes consecutive frames start at the requested period.

```python
def checksum(device, command):
    if not (0 <= device <= 255 and 0 <= command <= 255):
        raise ValueError("Device and command must be bytes")
    return ((device >> 4) ^ (device & 15)
            ^ (command >> 4) ^ (command & 15)) & 15


def encode_frame(device, command, period_us=29250):
    code = (device << 12) | (command << 4) | checksum(device, command)
    pulses = [1000, -580]
    for shift in range(18, -1, -2):
        symbol = (code >> shift) & 3
        pulses.extend([580, -(580 + 290 * symbol)])
    pulses.append(580)
    gap = period_us - sum(abs(t) for t in pulses)
    if gap <= 0:
        raise ValueError("Period must exceed active frame duration")
    return pulses + [-gap]


up_frame = encode_frame(0x86, 0x05)
power_frame = encode_frame(0x3C, 0xCC)
up_burst = up_frame * 8  # Total eight frames, including the first.
```

If an API takes unsigned alternating durations, pass `abs(t)` for each item
and specify that the first item is a mark. If it handles the repeat gap
separately, omit the final space from the frame and schedule the next start
using the remaining period. Confirm whether its repeat count includes the
first frame. Do not select a generic binary pulse-distance encoder: this
format needs four symbol spaces, including 870 and 1160 us.

## Decoder implementation

The reference decoder is [scripts/decode_ir.py](../scripts/decode_ir.py), with
no third-party Python dependencies. Its steps are:

1. Separate repeated frames at spaces longer than 5000 us. This threshold
   works for these captures because the longest data space is 1491 us and
   the shortest recorded inter-frame space is 9943 us.
2. Require 23 alternating signed durations and a header near 1000/580 us.
3. Require data/footer marks near 580 us.
4. Match each data space to the nearest of 580, 870, 1160, and 1450 us.
5. Shift the resulting two-bit symbols into a 20-bit MSB-first value.
6. Extract D/F/C and require the XOR checksum to match.

The script permits an absolute error of 100 us per expected mark or space.
For data spaces, this leaves rejection bands between adjacent symbol classes.
This is a tested decoder policy for the captured data, not a measured heater
receiver tolerance. Preserve undecodable frames so new variants or noise can
be investigated. Ignore isolated short noise pulses as invalid frames rather
than assigning them button names.

From the repository root:

```bash
python3 scripts/decode_ir.py captures/smart-fr/2026-10-15/*.jsonl
python3 -m unittest discover -s tests -p test_ir_decoder.py
```

The tests check captured commands, the alternating OK/P sequence, rejection
of a valid-duration symbol that corrupts the checksum, and rejection of an
out-of-range symbol duration. These are offline checks, not transmitter tests.

## Button semantics and application state

The manual describes these operations:

| Button | Manual-described operation |
| --- | --- |
| Power | Switch between standby/off and on |
| Up / Down | Adjust the selected screen's value one step |
| OK | Confirm a timer or thermostat selection |
| P | Select the program screen; Up/Down choose heating level P1-P6 |
| Timer | Select timer screen; choose 0-9 hours and confirm with OK; 0 cancels |
| Thermostat | Select thermostat screen; choose 18-37 C and confirm with OK; XX disables |
| MAX / MIN | Select the highest/lowest value on the current screen |

Captures identify button commands, with no selected temperature, timer value,
or heating level encoded in these particular frames. No heater-state readback
was captured. Do not invent direct IR codes for "set 22 C", "level 4", or
"off" from this table. Any multi-button sequence to achieve an absolute state
depends on the heater's screen and current value and needs live verification.

The integration in this repository uses cloud MQTT, a separate transport.
Its `B0`-`B6` and `T0`-`T9` messages are not IR field values. Matching the
remote's button codes does not establish a direct numerical mapping to MQTT
commands or guarantee that IR control reconstructs the heater's full state.

## Capture provenance and reproducing a measurement

[Session notes and raw pulse captures](../captures/smart-fr/2026-10-15/README.md)
contain the evidence. JSONL records retain timestamps, labels, source kind,
and complete signed pulse arrays. Host receive timestamps describe serial
collection time, not precise optical onset times. Intra-frame and repeat
timings come from the ESP32 receiver.

[esp32/receiver.example.yaml](../esp32/receiver.example.yaml) contains the
capture configuration: ESP32, GPIO32 inverted RX, 115200-baud raw serial logs,
50 us filter, 30 ms idle, and a 64 KB receive buffer. Its node name is retained
from the reused Webasto capture infrastructure. The receiver part number,
supply voltage, optical distance, and remote hardware revision were not
recorded; pin numbers alone are not a complete wiring specification.

[scripts/capture_ir_serial.py](../scripts/capture_ir_serial.py) uses pyserial:

```bash
python3 -m venv .venv-ir
.venv-ir/bin/python -m pip install pyserial
printf '%s\n' 'up-short-press' > /tmp/luxeva-label.txt
.venv-ir/bin/python scripts/capture_ir_serial.py \
  --port /dev/ttyUSB0 \
  --output /tmp/luxeva-session.jsonl \
  --raw-log /tmp/luxeva-session.serial.log \
  --label-file /tmp/luxeva-label.txt
```

Use your actual serial port and receiver wiring. Update the label file before
each button sequence; wait for a completed press to be flushed before changing
the label. Keep initial boot logs and unrelated serial output out of public
captures. With 30 ms receiver idle, all repeats in one press appear as one raw
array, and the offline decoder splits it into individual frames. The collector
does not reset, flash, or send IR to the board. Full original serial logs were
kept as temporary working files; the repository's durable raw evidence is the
selected signed pulse arrays.

## References, limitations, and historical correction

- [Original manual source](https://www.mirnagreva.ru/doc/obogrevateli/infrakrasnye/luxeva/infrakrasnye-karbonovye-obogrevateli-luxeva-pro-smart-smarty-instruction.pdf),
  downloaded unchanged; SHA256
  `1a21c14aba149e427bb420dcc27463946dbd50f11e71c5b4d392d0ee079fd780`.
- Xiaomi reference IRP, retained here for interoperability:

  ```text
  {36k,290,msb}<2,-2|2,-3|2,-4|2,-5>(1000u,-2,D:8,F:8,C:4,2,^30m)*
  {C=(D:4:4^D:4^F:4:4^F:4)} [D:0..255,F:0..255]
  ```

  Here `^30m` means a frame duration/start-to-start period of 30 ms, not a
  fixed 30 ms trailing gap. The measured remote period is about 29.25 ms.
  [protocol-reference.json](../captures/smart-fr/2026-10-15/protocol-reference.json)
  records the exact downloaded database hash and reference definition.
- IRremoteESP8266 at revision
  `1e2f0f3ef0a93cbf2a8ddb2e95130f8f4c584b3f` returned UNKNOWN for the first
  Power/Up software replays. Its fallback hashes are not command values.
  See the [retained results](../captures/smart-fr/2026-10-15/irremoteesp8266-results.txt).

The initial working analysis incorrectly reduced four space classes to two,
creating false duplicate buttons. Its 10-bit, parity, and +3 hypotheses are
superseded. The corrected interpretation accounts for all nine distinct
buttons and all captured checksums. Older provisional notes are retained
only as research history; use this specification and the corrected decoder.

This remains a receive-verified specification. Carrier frequency/duty,
generated transmissions, long holds, screen-specific behavior, and other
heater models need independent verification. New implementations can use
the captured vectors to validate their encoder and decoder before testing
with a physical heater. Original code and documentation use this repository's
[MIT license](../LICENSE); the appliance manual and external references retain
their respective owners' rights and licenses.
