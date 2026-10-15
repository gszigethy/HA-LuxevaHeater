# Device network capture findings — 2026-10-15

Source: user-provided `~/luxeva.pcap`, 474,938 bytes, SHA-256
`1e34befe82a34fb08884d97f3e28347710353079f574b3b005081c29b4ba0873`.
4,764 packets spanning 09:55:18–10:55:13 UTC (11:55:18–12:55:13 Budapest).
Analysis uses packet contents, not the HA integration implementation.

## Observed network behavior

The local endpoint `192.168.15.28` publishes heater status and receives device
commands. DNS resolves `iot.luxeva.com.tr` to `68.183.74.11` in this capture.
All captured IPv4 TCP traffic is MQTT to that address on port 1883. The only
other captured IPv4 traffic is UDP DNS between the local endpoint and its
router. There is no observed HTTP, HTTPS, TLS, NTP, or firmware download.
This describes the capture's visibility, not all possible device behavior.

Three TCP connections are present. The first starts before the capture; two
later connections include complete MQTT CONNECT handshakes. Reassembled
payload sequences have no gaps; retransmissions at identical sequence numbers
were deduplicated. The capture includes 1,890 status publications, 16 incoming
command publications, and 228 PINGREQ/PINGRESP pairs.

## MQTT connection contract

The two complete handshakes establish:

- Protocol name `MQTT`, version 4 (MQTT 3.1.1).
- CONNECT flags `0xC2`: username/password present, clean session enabled,
  no Last Will.
- Keepalive: 15 seconds.
- Client IDs: `LuxevaClient-4e73` and `LuxevaClient-f067`. The suffix changes
  between these connections; its generation algorithm is unknown.
- Both connections use the same captured username and password. Values remain
  in the private analysis file rather than this repository document.
- Broker returns successful CONNACK with session-present false.
- Two exact subscriptions, both requested and granted at QoS 0:
  `inTopic/<MAC>` and **`OTA_Ready/<MAC>`**.
- Status publishes to `outTopic/<MAC>` and commands delivered on
  `inTopic/<MAC>` have QoS 0, RETAIN false, DUP false.
- MAC is uppercase, colon-separated hexadecimal.

The device sends credentials in plaintext MQTT. The passive listener's
successful anonymous connection does not mean the device itself connects
anonymously. A local broker replacement must account for the device's actual
CONNECT behavior.

## Commands and lifecycle

Incoming command payloads are exactly the ASCII strings previously captured:
`T1`, `B1`, `T0`, `B2`, `B3`, `B0`, `T2`, `H28`, `H0`, `H29`, `T3`, including
repeated commands. There is no JSON wrapper or additional command exchange
visible. Broker-to-device packets do not identify the original publisher.
Initial `T1` interference was identified by the user as HA-originated.

The connection beginning at 10:09:36 UTC uses a new client ID and its first
status is `Msg 1, Prg 0, Tmp 25, Hts 00, Tmr 00:00`. This ties the observed
message-number reset to a new connection, but does not prove whether a reboot,
a reconnect, or another event caused the reset. Later app power-off and remote
power-on occur without a further connection change, so standby transitions do
not inherently require reconnecting in the observed session.

No message is delivered on `OTA_Ready/<MAC>`. Its name suggests an update-related
channel, but its payload format, authorization, and effect remain unknown.
Do not infer an OTA procedure from the subscription alone.

## Implication for a cloudless implementation

Observed steady-state control needs a plain MQTT broker supporting the
captured device login, subscriptions, status topic, and command strings.
DNS-based redirection is a plausible next experiment because the device
performs hostname lookups. Neither DNS redirection nor a replacement broker
has been tested; cached addresses, reconnection behavior, and dependencies
outside this capture remain to be verified. No local network configuration
was changed during analysis.

Private decoded flow evidence: `.local/pcap/analysis.json` (contains credentials
and real device identifiers). Original capture remains unchanged.
