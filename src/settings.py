"""Runtime configuration: hardware ports, safety thresholds, MQTT topics, credentials."""

import os


def read_required_environment(variable_name):
    if variable_name not in os.environ:
        raise SystemExit(f"missing required environment variable: {variable_name}")
    return os.environ[variable_name]


NPE_RELAY_PIN = 27
NPE_BOND_THRESHOLD_W = 50
NPE_BOND_STABLE_SECONDS = 3
ZMAI_STALE_SECONDS = 15
ZMAI_NOISE_THRESHOLD_W = 20
PV2_PV1_RATIO_DEFAULT = 0.60
PV2_RATIO_MIN_PV1_W = 50

INVERTER_PORT = "/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A5069RR4-if00-port0"
INVERTER_BAUD = 2400
INVERTER_STALE_SECONDS = 30
ALARM_REPEAT_SECONDS = 300

BATTERY_LOW_VOLTAGE_V = 44.0
LOW_BATTERY_PROTECTION_SOC_PCT = 10
LOW_BATTERY_PROTECTION_SOC_RANGE = (10, 50)
GRID_STOP_CHARGING_MINIMUM_GAP_PCT = 15
GRID_STOP_CHARGING_SOC_PCT = 30
GRID_STOP_CHARGING_SOC_RANGE = (LOW_BATTERY_PROTECTION_SOC_RANGE[0] + GRID_STOP_CHARGING_MINIMUM_GAP_PCT, 100)
GRID_QUICK_CHARGE_SOC_PCT = 90
SOC_SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "soc_settings.json")
GRID_QUICK_CHARGE_SOC_RANGE = (30, 100)
# LCD program 12: SBU moves the load to grid below this voltage; must stay above where the BMS cuts out (~46V).
BACK_TO_GRID_V = 49.0
BACK_TO_GRID_V_RANGE = (44.0, 51.0)
# LCD program 13: SBU moves the load back to battery above this voltage.
BACK_TO_BATTERY_V = 52.0
BACK_TO_BATTERY_V_RANGE = (48.0, 58.0)
BACK_TO_BATTERY_MINIMUM_GAP_V = 2.0

GRID_NOMINAL_VOLTAGE_V = 240
MAX_GRID_POWER_W = 5000
MAX_GRID_POWER_RANGE = (1000, 7200)
SOFT_LIMIT_HYSTERESIS_W = 500
MCB_RATING_A = 32
MCB_RATING_RANGE = (16, 63)
MCB_LOCKOUT_SECONDS = 1800

POLL_INTERVAL_SECONDS = 5

MQTT_HOST = read_required_environment("MQTT_HOST")
MQTT_PORT = int(read_required_environment("MQTT_PORT"))
MQTT_USER = read_required_environment("MQTT_USER")
MQTT_PASSWORD = read_required_environment("MQTT_PASSWORD")

BASE_TOPIC = "solar"
DISCOVERY_PREFIX = "homeassistant"
DEVICE_ID = "solar_pi"
UNIQUE_ID_PREFIX = "rasp"
AVAILABILITY_TOPIC = f"{BASE_TOPIC}/status"

NPE_MODE_TOPIC = f"{BASE_TOPIC}/npe_bonding/mode/set"
NPE_MODES = ("auto", "manual_on", "manual_off")
PV_EFFICIENCY_TOPIC = f"{BASE_TOPIC}/pv/efficiency/set"
PV2_RATIO_TOPIC = f"{BASE_TOPIC}/pv/pv2_ratio/set"
PV_EFFICIENCY_DEFAULT = 0.93
BATTERY_MODE_TOPIC = f"{BASE_TOPIC}/battery_mode/set"
LOW_BATTERY_PROTECTION_SOC_TOPIC = f"{BASE_TOPIC}/battery/discharge_stop_soc/set"
GRID_STOP_CHARGING_SOC_TOPIC = f"{BASE_TOPIC}/battery/discharge_resume_soc/set"
GRID_QUICK_CHARGE_SOC_TOPIC = f"{BASE_TOPIC}/battery/grid_quick_charge_soc/set"
BACK_TO_GRID_V_TOPIC = f"{BASE_TOPIC}/battery/back_to_grid_v/set"
BACK_TO_BATTERY_V_TOPIC = f"{BASE_TOPIC}/battery/back_to_battery_v/set"
MAX_GRID_POWER_TOPIC = f"{BASE_TOPIC}/grid_limiter/max_power_w/set"
MCB_RATING_TOPIC = f"{BASE_TOPIC}/grid_limiter/mcb_rating_a/set"

CAN_INTERFACE = "can0"
CAN_BATTERY_STALE_SECONDS = 30

CHARGER_SOURCE_TO_PCP = {
    "utility_first": "PCP00",
    "solar_first": "PCP01",
    "solar_and_utility": "PCP02",
    "solar_only": "PCP03",
}
