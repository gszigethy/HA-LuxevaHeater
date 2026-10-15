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

## Reuse the existing receiver

The adjacent `../HA-Webasto-Cool-Top-Trail` checkout contains the previous
USB-only ESPHome capture firmware in `esp32/receiver.example.yaml`:
GPIO32 RX, inverted input, raw timing dumps, 115200 baud, 50 us filter,
30 ms idle, 64 KB receive buffer. GPIO26 TX is configured but never invoked.
The documented capture board is an ESP32-PICO-D4 with 4 MB flash.
The existing `.venv-esphome` includes pyserial.

The original Webasto collector contained a Webasto-specific decoder and a
267-duration assembly threshold. The local `scripts/capture_ir_serial.py`
removes both assumptions and preserves signed microsecond timings and optional
original serial bytes. It does not depend on the adjacent Webasto checkout.
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

## Readiness check, 2026-10-15

The manual and previous firmware/scripts were found. The Python serial-port
enumeration returned no ports, and all USB/IP virtual-controller status tables
showed no attached devices from this execution environment. The running ESP32
firmware and receiver operation could therefore not be verified. No device was
flashed and no IR commands were transmitted during that initial check.

The device was subsequently attached from the user's Windows USB/IP export,
and identified as the expected ESP32-PICO-D4 with 4 MB flash. With the user's
authorization, the existing capture factory binary was restored using esptool
at 115200 baud with `--no-stub`; written data passed the flash hash check.
The binary SHA256 is
`d643cb2330daacd2ecfe9647b20dedfbd29e3f2e1790916de3a30a69fe51615e`.
Boot logs confirmed ESPHome 2026.9.1 and GPIO32 RX. Initial receiver logs
contained isolated approximately 3 ms pulses, not verified remote frames.
Attempts to back up the previous firmware failed over USB/IP; no usable backup
was obtained. No IR commands were transmitted.

The capture YAML is retained in `esp32/receiver.example.yaml` with its original
node name. `scripts/capture_ir_serial.py` reuses the previous serial collector
but removes the Webasto decoder and fixed pulse-count assembly threshold.
It stores undecoded timings, labels, timestamps, and optional original bytes.
