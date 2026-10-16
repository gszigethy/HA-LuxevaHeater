# SMART-FR remote capture, 2026-10-15

The captured signals match the **Xiaomi IRP encoding and XOR checksum**.
This identifies the signal format, not the remote manufacturer.
Carrier frequency and heater response have not been verified.

For reimplementation, use the [standalone protocol specification](../../../docs/ir-protocol.md)
and [machine-readable code map](../../../docs/ir-codes.json).

| Button | Device D | Command F | Checksum C | Full 20-bit code | Valid frames |
| --- | --- | --- | --- | --- | --- |
| Power (initial + confirmation) | 0x3C | 0xCC | 0xF | 0x3CCCF | 55 |
| Up | 0x86 | 0x05 | 0xB | 0x8605B | 21 |
| Down | 0x86 | 0x06 | 0x8 | 0x86068 | 22 |
| OK | 0x86 | 0x0D | 0x3 | 0x860D3 | 20 |
| P / Program | 0x86 | 0x08 | 0x6 | 0x86086 | 28 |
| Timer | 0x86 | 0x07 | 0x9 | 0x86079 | 27 |
| Thermostat | 0x86 | 0x04 | 0xA | 0x8604A | 27 |
| MAX | 0x86 | 0x0E | 0x0 | 0x860E0 | 30 |
| MIN | 0x86 | 0x0F | 0x1 | 0x860F1 | 33 |

The separate OK/P/OK/P capture decoded to commands 0x0D/0x08/0x0D/0x08,
with 7/9/10/9 valid repeat frames. In total, all 298 stored repeat frames
passed symbol timing checks and the XOR checksum. All nine buttons have
separate observed full codes. Three additional Power presses produced
9/10/11 identical frames of 0x3CCCF with valid checksums. Power consistently
uses device byte 0x3C, whereas the other buttons use 0x86. Preserve the complete
Power code rather than substituting device byte 0x86. The reason for the
different device field is unknown; button transmission identity is confirmed
by repeated captures, while heater response is untested.

## Encoding

Reference: [IrpTransmogrifier Xiaomi definition](https://github.com/bengtmartensson/IrpTransmogrifier/blob/master/src/main/resources/IrpProtocols.xml).
The exact reference file hash is recorded in protocol-reference.json.

- Header: nominal 1000 us mark, 580 us space.
- Data: ten MSB-first two-bit symbols, giving 20 bits total.
- Every data mark: nominal 580 us.
- Spaces 580 / 870 / 1160 / 1450 us represent 00 / 01 / 10 / 11.
- Fields: eight device bits, eight command bits, four checksum bits.
- Checksum: XOR the four nibbles of the device and command bytes.
- Footer: nominal 580 us mark; captured inter-frame spaces 9.943-12.366 ms,
  varying by command to maintain a nearly constant frame period.
- Captured frame periods approximately 29.2 ms; reference specifies 30 ms.
- Reference carrier is 36 kHz. This demodulating receiver cannot measure it.

Receive-only ESPHome capture used GPIO32, 115200 baud, 30 ms idle, and the
restored firmware described in ../../../docs/ir-research.md. Signed durations
are in microseconds. The initial power label was assigned after the user
confirmed the sequence; subsequent labels were set before capture. The user
confirmed the remote matches the manual but the heater is unavailable.

## Reproduce

From the repository root:

```bash
python3 scripts/decode_ir.py captures/smart-fr/2026-10-15/*.jsonl
```

The decoder checks timing, polarity, symbol count, and checksum. It operates
on stored data and sends no IR. Raw JSONL captures remain unchanged.

## Correction to earlier interpretation

The initial analysis incorrectly assumed binary space encoding and merged
four distinct space levels into two. That caused false duplicate buttons and
incorrect 10-bit/+3/parity hypotheses. They are superseded. The corrected
decoder also distinguishes the complete alternating OK/P sequence.

IRremoteESP8266 revision 1e2f0f3ef0a93cbf2a8ddb2e95130f8f4c584b3f returned
UNKNOWN for the first six bursts and 46 individual Power/Up frames. Those
results are preserved in irremoteesp8266-results.txt; UNKNOWN values are
hashes, not commands, and estimated bit counts are not decoded field sizes.
The reference Xiaomi definition supplies the successful encoding model.
