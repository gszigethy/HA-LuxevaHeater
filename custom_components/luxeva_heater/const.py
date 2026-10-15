"""Constants for the Luxeva Heater integration."""

from typing import Any

DOMAIN = "luxeva_heater"

DEFAULT_BROKER = "iot.luxeva.com.tr"
DEFAULT_PORT = 1883

CONF_MAC = "mac"
CONF_DISCLAIMER = "disclaimer_accepted"

TOPIC_OUT = "outTopic/{mac}"
TOPIC_IN = "inTopic/{mac}"

# Heating level presets: Prg 1-6 → B1-B6 commands
PRESET_MODES = ["Level 1", "Level 2", "Level 3", "Level 4", "Level 5", "Level 6"]
PRESET_TO_LEVEL: dict[str, int] = {f"Level {i}": i for i in range(1, 7)}
LEVEL_TO_PRESET: dict[int, str] = {i: f"Level {i}" for i in range(1, 7)}

# The manufacturer manual documents countdown settings from 0 to 9 hours.
TIMER_MAX_HOURS = 9

# Existing entries migrate to compatibility; new installations opt into managed control.
CONF_CONTROL_MODE = "control_mode"
MODE_COMPATIBILITY = "compatibility"
MODE_CLIMATE = "climate"
MODE_ACTUATOR = "actuator"
CONF_CONNECTION = "connection"
CONNECTION_CLOUD = "cloud"
CONNECTION_LOCAL = "local"
CONF_BROKER = "broker"
CONF_PORT = "port"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SENSOR = "temperature_sensor"
CONF_POWER_SWITCH = "power_switch"
CONF_TOLERANCE = "tolerance"
CONF_MIN_CYCLE = "minimum_cycle_seconds"
CONF_SENSOR_TIMEOUT = "sensor_timeout_minutes"
CONF_PROTECT_EXTERNAL = "protect_external_starts"
CONF_PREPARE_BROKER = "prepare_mosquitto"
RENEW_SECONDS = 600
CONTROL_INTERVAL = 5
TIMER_ACK_SECONDS = 15
DEFAULT_OPTIONS: dict[str, Any] = {
    CONF_CONTROL_MODE: MODE_CLIMATE,
    CONF_CONNECTION: CONNECTION_CLOUD,
    CONF_BROKER: DEFAULT_BROKER,
    CONF_PORT: DEFAULT_PORT,
    CONF_TOLERANCE: 0.3,
    CONF_MIN_CYCLE: 300,
    CONF_SENSOR_TIMEOUT: 0,
    CONF_PROTECT_EXTERNAL: True,
}
CONF_ENTRY_TYPE = "entry_type"
ENTRY_HEATER = "heater"
ENTRY_LOCAL_SERVICE = "local_service"
CONF_LOCAL_SERVICE = "local_service"
# Observed device firmware login. Not claimed to be universal to every model.
# It is fixed in the firmware and provisioned on local brokers; not a secret.
DEVICE_USERNAME = "luxeva@us"
DEVICE_PASSWORD = "luxeva@pw"  # NOSONAR
