# Superseded analysis: incorrect binary assumption

The analysis below was corrected by the Xiaomi four-level symbol decoder.
The apparent button collisions, +3 pattern, bit counts, and parity inference
are invalid. Retained only as research provenance. See README.md for results.

# SMART-FR remote capture, 2026-10-15

Receive-only capture with the restored ESPHome firmware described in
../../../docs/ir-research.md. Each button was pressed three times by the user.
Signed timings are microseconds. The power records were labelled after the
user confirmed the requested sequence; subsequent labels were set before capture.

| Button | Repeated frames per press | Candidate 10-bit field, transmission order |
| --- | --- | --- |
| Power | 7, 8, 10 | 0110101011 |
| Up | 6, 8, 7 | 1001000011 |
| Down | 7, 7, 8 | 1001000110 |
| OK | 6, 7, 7 | 1001001001 |
| Program (requested button; needs confirmation) | 9, 9, 10 | 1001001001 |
| Timer | 8, 10, 9 | 1001000110 |
| Thermostat | 8, 9, 10 | 1001000011 |
| MAX | 10, 10, 10 | 1001001100 |
| MIN | 10, 10, 13 | 1001001100 |

Each repeat has 23 durations: a candidate header mark/space, ten mark/space
data pairs, and a final mark. Frame boundaries are approximately 10 ms spaces.
This framing remains a hypothesis: the first pair could have a different role.
Bit significance, address/command fields, and integrity checks are unconfirmed.

Across all 25 Power repeats, measured medians are: header mark 1019 us,
header space 575 us, data/footer mark 596 us, short data space 585 us,
long data space 1466 us, and inter-frame space 9947 us.
Carrier frequency cannot be measured with this demodulating receiver.

## Existing protocol comparison

IRremoteESP8266 revision `1e2f0f3ef0a93cbf2a8ddb2e95130f8f4c584b3f`
was compiled on the host with UNIT_TEST enabled. Recorded durations were
replayed in software through IRsendTest into IRrecv::decode, both as full
bursts and individual repeat frames. All six Power/Up bursts and their 46
individual frames fell back to UNKNOWN. No IR was transmitted by this check.
See irremoteesp8266-results.txt. UNKNOWN's value is a hash, and its reported
bit count is an estimate; neither is a decoded command or confirmed frame size.
The 38 kHz passed to the software sender is an arbitrary simulation setting,
not a measurement of this remote.

Source comparisons at the same revision:

- `src/ir_NEC.cpp`: incompatible 9 ms header and 32-bit framing.
- `src/ir_Sony.cpp`: pulse-width encoding differs from these constant data marks.
- `src/ir_Symphony.cpp`: varies mark and space together; incompatible encoding.
- `src/ir_Wowwee.cpp`: 6684 us header and 912/3259 us bit timings differ.
- `src/ir_Bose.cpp`: superficially similar 555/500/1435 us data timings, but
  1100/1350 us header and 16-bit framing disagree with the capture.

Up and Down share their first seven candidate bits and differ in their last
three. Further buttons and context comparisons should test whether these are
command fields, check bits, or another encoding. No named protocol match has
been established; the decoder result does not rule out protocols absent from
the library.

OK adds another distinct, stable pattern with the same 23-duration framing.
With the provisional transmission-order MSB notation, Up/Down/OK are
0x243/0x246/0x249: a common prefix and increments of three. This is a useful
field-structure hypothesis, not proof of bit order, command numbering, or a
checksum. All four observed patterns have an even number of set bits; further
buttons are needed to determine whether this is meaningful or coincidental.

The requested Program sequence produced the same pattern as the previous OK
sequence in all 28 repeats. Preserve both labels as reported; do not assume
distinct commands or a confirmed shared command until an alternating OK/P
capture checks button identity and repeatability.

The follow-up requested OK/P/OK/P sequence yielded four bursts of 7/9/10/9
frames, all with pattern 1001001001 and the same 23-duration structure.
Given the user-reported button order, both buttons send the same observed
waveform in this test. This does not establish whether the heater handles them
identically in every context. Preserve the alternating capture separately.

The requested Timer sequence yielded 27 frames with the same pattern as Down.
This is a second apparent button collision. Button mapping is provisional:
check the physical remote layout and compare complete waveforms/context before
claiming intentional shared commands across all functions.

The requested Thermostat sequence yielded 27 frames matching Up. The observed
pairs are now Up/Thermostat, Down/Timer, and OK/Program. These are waveform
observations associated with user-reported presses, not proof of intentional
manufacturer command sharing. Finish MAX/MIN, then investigate these pairs
using the actual remote layout and heater response.

MAX yielded 30 identical frames with a new candidate field, 1001001100
(provisional MSB notation 0x24C). This continues the +3 sequence observed for
Up (0x243), Down (0x246), and OK (0x249). Its physical meaning remains
unconfirmed until the repeated button pairs are resolved.

MIN yielded 33 matching frames, identical to MAX under the current framing.
The first pass therefore has only five distinct candidate fields for nine
reported buttons. Besides Power, the four distinct fields are 0x243, 0x246,
0x249, 0x24C. Their low nibbles are 0011, 0110, 1001, 1100: the lower two bits
are the complement of the preceding two. This may represent a two-bit command
and redundant inverted copy, but the available captures do not prove that
interpretation. Resolve the collisions using a confirmed remote layout and
observed heater responses before collecting more undifferentiated presses.
