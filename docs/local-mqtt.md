# Local MQTT service

The local replacement is an ordinary MQTT broker. Mosquitto owns authentication,
sessions, subscriptions and ping responses. Each heater continues to publish its
own status and consume its native commands. The Luxeva integration supplies HA
entities and control policy; there is no additional Luxeva service app.

## Separate entries, multiple heaters

Add **Luxeva Heater → Local MQTT service** once. Add each heater separately with
its own MAC, then select the service in that heater's configuration. Heater
settings, sessions and emergency latches are independent. A service can be shared
by Terrace, Patio and other heaters, or multiple services can be configured.

| Entry | Example | Responsibility |
| --- | --- | --- |
| Local MQTT service | Luxeva Local MQTT | Broker address, setup and connection diagnostic |
| Heater | Terrace | Its own MAC, climate, sensors, actuator and safety policy |
| Heater | Patio | Separate MAC and independent control; may reuse the same service |

The service diagnostic authenticates to the broker without sending commands.
Connected means the **broker** accepts the heater login. A heater becomes
available only after its own fresh, non-retained status arrives.

## Automatic Mosquitto preparation

On a Supervisor installation, select **Install/configure Mosquitto and provision
the heater login**. The setup flow checks for `core_mosquitto`, installs it if
missing, adds the observed device login if absent, and starts it or restarts it
when the configuration changed. The flow shows progress and verifies MQTT CONNACK.

Existing options and logins are preserved. A matching existing login is reused
without restarting an already running broker. A conflicting password is rejected
rather than overwritten. Preparation is serialized across Luxeva setup flows.
A broker restart briefly disconnects all of its clients; the setup form says so
before you opt in.
This action is not repeated on every heater setup or HA restart.

The observed firmware logs in with a fixed username and password. Two captured
connections from one heater used the same pair; its universality across models is not established.
Mosquitto's local `logins` feature provisions it without creating a HA UI account.
Home Assistant connects with the same login, so there are no credentials to enter;
the broker must accept this login in any case for the heater to connect. On other
brokers, add this login yourself; the values are `DEVICE_USERNAME` and
`DEVICE_PASSWORD` in `const.py`. If you use per-user ACLs, the login also needs
to publish to `inTopic/<MAC>` and subscribe to `outTopic/<MAC>` for HA.

Without Supervisor, leave automatic preparation unchecked and supply an existing
broker. The integration does not replace HA's configured MQTT integration or
change its broker. Each broker address and port can belong to only one service
entry. Changing a shared service stops its heaters, refuses new starts until they
reconnect, and ends their sessions. Configure another service instead if only one
heater should move.

## Network steps the user must perform

1. Make the broker reachable from the heater's network on **TCP 1883**. If the
   heater and Home Assistant are on separate VLANs or subnets, add a firewall rule
   allowing the heater to reach the broker's LAN IP on TCP 1883. The heater also
   needs DNS (UDP/TCP 53) to the resolver that carries the override.
2. Redirect **iot.luxeva.com.tr** to the broker's **LAN IP** using network DNS.
   `core-mosquitto` is an HA-internal hostname, not the address to give the heater.
3. Ensure the heater actually uses that DNS resolver. Allow for cached answers and
   reconnect the heater if needed.
4. If using custom ACLs, allow device status publication to `outTopic/<MAC>` and
   subscriptions to `inTopic/<MAC>` and `OTA_Ready/<MAC>`. The HA client needs to
   publish and subscribe to `inTopic/<MAC>` and subscribe to `outTopic/<MAC>`.
5. Choose the service in each heater's **Configure** flow. A repair issue remains
   until the correct MAC publishes fresh status through the local connection.

Use uppercase, colon-separated MACs, such as `AA:BB:CC:DD:EE:01`. Topics remain:

```text
inTopic/AA:BB:CC:DD:EE:01
outTopic/AA:BB:CC:DD:EE:01
OTA_Ready/AA:BB:CC:DD:EE:01
```

No topic namespace, MAC rewriting, wildcard subscription, synthetic status or
cloud bridge is introduced. The OTA subscription is permitted, but no OTA command
is sent: its payload and behavior remain unknown.

A network-wide DNS override affects every heater using that resolver. To mix cloud
and local heaters using the same hostname, use per-device DNS/network policies.
To return to cloud operation, restore the appropriate DNS resolution as well as
changing the heater's connection option. Local mode has no automatic cloud fallback.

## Scope and acceptance checks

The PCAP establishes the device-facing MQTT contract, not the official app's
account, discovery or provisioning backend. Full offline operation of the official
app is not claimed. Wi-Fi provisioning remains through the official app.

Local operation has not yet been verified with a real heater. Before relying on
it, check for every heater: fresh status arrives, commands take effect, heating
starts from standby, `T1` renewals are confirmed, and the heater stops within an
hour when HA is stopped. The integration never changes your DNS, HA users or
power switches by itself; Mosquitto is installed only when you choose that option.
