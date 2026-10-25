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
BACK_TO_GRID_V_RANGE = (46.0, 51.0)
# LCD program 13: SBU moves the load back to battery above this voltage and stops utility charging there.
BACK_TO_BATTERY_V = 52.0
BACK_TO_BATTERY_V_RANGE = (48.0, 58.0)
# a user value above this (near the BMS charge limit, 57.6V) would keep the load on grid for good
BACK_TO_BATTERY_NORMAL_MAXIMUM_V = 56.0
BACK_TO_BATTERY_MINIMUM_GAP_V = 2.0

MCB_RATING_A = 32
MCB_RATING_RANGE = (16, 160)
# Repeated MCB lockouts last longer each time; after the last step grid charging stays off until midnight.
MCB_LOCKOUT_STEPS_SECONDS = (1800, 3600, 7200)

# LCD program 11: max utility (grid) charging current, battery side DC amps; 150/160A exist on the 10.2kW model only.
# program 11 (battery-side DC amps, ~52V) per grid-charging mode; every other state runs the minimum option
NORMAL_GRID_CHARGING_CURRENT_A = 50  # ~2.6kW
QUICK_GRID_CHARGING_CURRENT_A = 90  # ~4.7kW
MAX_UTILITY_CHARGING_CURRENT_OPTIONS_A = (2, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150, 160)
# LCD program 02: max total (solar + grid) charging current, held at the DAH BMS charge current limit (~7.4kW)
MAX_TOTAL_CHARGING_CURRENT_A = 140

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
MCB_RATING_TOPIC = f"{BASE_TOPIC}/grid_limiter/mcb_rating_a/set"
# topic name kept from the former number entity: the mosquitto bridge already forwards it in
# the normal topic keeps the old program 11 path, already forwarded by the mosquitto bridge
NORMAL_GRID_CHARGING_CURRENT_TOPIC = f"{BASE_TOPIC}/inverter/max_ac_charge_current_a/set"
QUICK_GRID_CHARGING_CURRENT_TOPIC = f"{BASE_TOPIC}/inverter/quick_grid_charging_current_a/set"

CAN_INTERFACE = "can0"
CAN_BATTERY_STALE_SECONDS = 30

OUTPUT_PRIORITY_TO_POP = {"USB": "POP00", "SUB": "POP01", "SBU": "POP02"}
# a refused output priority command is retried at most this often
OUTPUT_PRIORITY_RETRY_SECONDS = 60

# Program 16 codes named by what they did in live tests on this firmware (2026-10-22), not by the manual:
# PCP01 grid-charges and follows program 11; PCP02 stops grid charging (PV still charges);
# PCP03 grid-charges ignoring program 11 (56A with program 11 at 2A), so it is never sent.
CHARGER_SOURCE_TO_PCP = {
    "grid_charging": "PCP01",
    "no_grid_charging": "PCP02",
}
GRID_CHARGING_SOURCES = ("grid_charging",)
