# Migrating from 1.x

Version 2 is opt-in for existing installations. Do not remove and re-add your
heaters: the config-entry migration preserves each MAC, unique ID, device identity
and the five original entity unique IDs. Your entity IDs, history, dashboards,
Generic Thermostat helpers and automation references remain intact.

## What happens immediately after upgrading

Existing heater entries receive **Compatibility** control mode and retain the
cloud connection. The old climate still offers heat/off and Level 1–6, the actuator
still sends level plus `T1` on turn-on, and timer zero still sends `T0` plus `B0`.
The old automatic safety timer on external off-to-on transitions is retained.
No external room sensor, upstream power switch or local service is added automatically.

Additional diagnostic/session entities do not change your automations. The five
original unique-ID suffixes remain `_climate`, `_timer`, `_timer_remaining`,
`_thermostat` and `_actuator`.

## Adopt the new Luxeva thermostat

1. Set your existing Generic Thermostat helper to off and disable any automations
   that would re-enable it. Do not leave two thermostats controlling one heater.
2. Open the heater's **Configure** flow and select **Luxeva climate**.
3. Select the same external room sensor previously used by Generic Thermostat.
4. Review tolerance, minimum cycle interval and optional sensor freshness limit.
5. Optionally choose an upstream power switch, then save.
6. The old session ends and heating remains off. Set a target and P level, then
   explicitly select Heat on the Luxeva climate.

The integration does not edit or delete your helper or automations. You may keep
them disabled if you want to return to the old arrangement later.

## Keep Generic Thermostat

You may remain in Compatibility mode, or opt into **Actuator** control. In Actuator
mode the switch retains a one-hour timer on every start and does not periodically
renew it. The climate may select the shared P level and stop heating, but a climate
start is rejected while the actuator owns control.

Generic Thermostat needs another control evaluation to resume heating after the
device timer expires; the actuator's off transition alone does not guarantee that
it restarts immediately. Sensor updates or a configured periodic evaluation can
provide this. A Generic Thermostat keepalive that calls turn-on while already
heating also resets the device timer. The helper remains user-managed HA configuration.

Managed user-session expiry rejects subsequent actuator starts until Timer is
explicitly cleared or given a new duration; this prevents the helper immediately
undoing a user deadline.

## Behavior changes when you opt in

| Action | Compatibility | Managed climate/actuator |
| --- | --- | --- |
| Timer = 0 | Cancel timer and turn heating off | Cancel user session limit; active heating retains safety protection |
| Timer = 1–9 while off | Start heater at last level, then set native timer | Set an HA session deadline; does not itself start heating |
| Long timer | Device receives `T2`–`T9` | HA persists the deadline; device receives one-hour intervals |
| Remaining timer entity | Device countdown | Same device countdown; separate User session remaining shows HA deadline |
| Target temperature | Not supported | Luxeva climate supports it when an external sensor is selected |
| Missing room temperature | Outside the integration's control | Luxeva thermostat requests shutdown and stops renewals |
| External starts | Automatically arm `T1` when no countdown | Configurable: one protective `T1` interval, without HA taking over or renewing it; managed climate starts always have protection |

Update automations using timer zero as an off command to call `climate.turn_off`
or `switch.turn_off` before opting in. Those actions stop heating explicitly.

## Cloudless and safety shutdown are separate choices

You do not need to adopt local MQTT to use the new thermostat, or adopt the new
thermostat to retain cloud access. Add a separate local service and select it per
heater when ready. The optional power-cut switch can also be added independently.

Reconfiguration intentionally ends the current session and leaves heating off.
A safety latch is retained regardless of control mode. Never remove a latch by
switching ownership: use Reset safety shutdown while the upstream switch reports off.

## Preview and rollback

This is a major-version beta. First verify one heater before moving others. Keep
an HA backup before upgrading. Returning to 1.x requires restoring its older
config-entry/storage state from backup; a v2 entry should not be downgraded merely
by replacing the Python files. Re-selecting Compatibility in v2 is the supported
way to return to old behavior without losing entity identities.
