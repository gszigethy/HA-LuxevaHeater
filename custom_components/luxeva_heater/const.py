"""Constants for the Luxeva Heater integration."""

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

# Timer: T<N> command sets N hours (integer). Assumed max based on typical heaters;
# adjust if the app exposes a higher limit.
TIMER_MAX_HOURS = 9
