"""Runtime configuration: hardware ports, safety thresholds, MQTT topics, credentials."""

import os


def read_required_environment(variable_name):
    if variable_name not in os.environ:
        raise SystemExit(f"missing required environment variable: {variable_name}")
    return os.environ[variable_name]


NPE_RELAY_PIN = 27
NPE_BOND_THRESHOLD_W = 50
NPE_BOND_STABLE_SECONDS = 3
NPE_BATTERY_STALE_SECONDS = 30
ZMAI_STALE_SECONDS = 15
ZMAI_NOISE_THRESHOLD_W = 20
PV2_PV1_RATIO_DEFAULT = 0.60
PV2_RATIO_MIN_PV1_W = 50

INVERTER_PORT = "/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A5069RR4-if00-port0"
INVERTER_BAUD = 2400
INVERTER_STALE_SECONDS = 30
ALARM_REPEAT_SECONDS = 300

BATTERY_LOW_VOLTAGE_V = 44.0
BATTERY_DISCHARGE_STOP_SOC_PCT = 10
BATTERY_RESUME_SOC_PCT = 50

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
OUTPUT_PRIORITY_MODE_TOPIC = f"{BASE_TOPIC}/output_priority/mode/set"
CHARGER_SOURCE_TOPIC = f"{BASE_TOPIC}/charger_source/set"
DISCHARGE_STOP_SOC_TOPIC = f"{BASE_TOPIC}/battery/discharge_stop_soc/set"
DISCHARGE_RESUME_SOC_TOPIC = f"{BASE_TOPIC}/battery/discharge_resume_soc/set"

CHARGER_SOURCE_OPTIONS = ("solar_first", "utility_first", "solar_and_utility", "solar_only")
CHARGER_SOURCE_TO_PCP = {
    "utility_first": "PCP00",
    "solar_first": "PCP01",
    "solar_and_utility": "PCP02",
    "solar_only": "PCP03",
}
