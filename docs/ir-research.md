# Luxeva SMART-FR IR research

Target: [SMART-FR BLACK](https://luxeva.com.tr/product/smart-fr-black/).
Compatibility with other Smart models remains unverified.

For implementation, use the [IR protocol specification](ir-protocol.md) and
[machine-readable button map](ir-codes.json). This page records setup history.

## Manual

[Original manual](manuals/luxeva-pro-smart-smarty-instruction.pdf), downloaded
2026-10-15 from
https://www.mirnagreva.ru/doc/obogrevateli/infrakrasnye/luxeva/infrakrasnye-karbonovye-obogrevateli-luxeva-pro-smart-smarty-instruction.pdf
without modification.

Printed page 14 (PDF page 13) shows the remote. Printed pages 15-16
(PDF pages 14-15) describe its functions:

- Power / standby
- Up and down: adjust the current screen's value
- OK: confirm timer or thermostat selection
- P: select program P1-P6
- Timer: select 0-9 hours and confirm with OK
- Thermostat: select 18-37 C; XX disables the thermostat
- MAX and MIN: select the current screen's highest or lowest value

## Capture hardware

The receiver is an ESP32-PICO-D4 (4 MB flash) running receive-only ESPHome
firmware, [esp32/receiver.example.yaml](../esp32/receiver.example.yaml): GPIO32
RX with inverted input, raw timing dumps over 115200-baud serial, 50 us filter,
30 ms idle and a 64 KB receive buffer. A GPIO26 transmitter is configured but
never used. The same capture setup was earlier used for the author's
[Webasto Cool Top Trail](https://github.com/gszigethy/HA-Webasto-Cool-Top-Trail)
integration.

[scripts/capture_ir_serial.py](../scripts/capture_ir_serial.py) collects the
serial dumps. It makes no assumptions about the protocol and preserves signed
microsecond timings and, optionally, the original serial bytes.
The initial setup had no established protocol. Subsequent captures match the
Xiaomi IRP four-level space encoding, MSB-first 20-bit fields, and nibble XOR
checksum. Carrier frequency remains unmeasured. See the corrected results in
[the capture notes](../captures/smart-fr/2026-10-15/README.md).

## Initial capture sequence

1. Capture three separate short presses of each of the nine buttons, with
   approximately two seconds between presses and a label for every button.
2. Capture held up/down buttons to establish repeat behavior.
3. Compare up/down, MIN/MAX, and OK in program, timer, and thermostat contexts
   to determine whether IR sends fixed button commands or selected state.
4. Correlate heater behavior and MQTT state only after identifying the frames.

Start with receive-only capture. General Smart-series compatibility requires
additional hardware evidence.

## Capture session, 2026-10-15

The ESP32 was attached over USB/IP and flashed with the capture firmware
(ESPHome 2026.9.1; firmware binary SHA-256
`d643cb2330daacd2ecfe9647b20dedfbd29e3f2e1790916de3a30a69fe51615e`). Before the
first button press the receiver logged only isolated pulses of about 3 ms, not
remote frames. Each button was then pressed several times with labels set before
each sequence. No IR was transmitted at any point.
