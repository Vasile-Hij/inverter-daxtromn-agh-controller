import glob
import json
import os
import socket
import time

import paho.mqtt.client as mqtt
from gpiozero import DigitalOutputDevice

from pi30 import PI30Connection, is_number

ZMAI_TOPIC_PREFIX = "energy-smart-meter-zmai-90"
ZMAI_POWER_TOPIC = f"{ZMAI_TOPIC_PREFIX}/power/get"
ZMAI_VOLTAGE_TOPIC = f"{ZMAI_TOPIC_PREFIX}/voltage/get"
ZMAI_CURRENT_TOPIC = f"{ZMAI_TOPIC_PREFIX}/current/get"
ZMAI_RELAY_TOPIC = f"{ZMAI_TOPIC_PREFIX}/1/get"

NPE_RELAY_PIN = 27
NPE_BOND_THRESHOLD_W = 50
NPE_BOND_STABLE_SECONDS = 3
NPE_BATTERY_STALE_SECONDS = 30
GRID_VOLTAGE_THRESHOLD_V = 50
ZMAI_STALE_SECONDS = 15
ZMAI_NOISE_THRESHOLD_W = 20
PV2_PV1_RATIO_DEFAULT = 0.37
PV2_RATIO_MIN_PV1_W = 50

INVERTER_PORT = "/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A5069RR4-if00-port0"
INVERTER_BAUD = 2400
INVERTER_STALE_SECONDS = 30
ALARM_REPEAT_SECONDS = 300

BATTERY_VOLTAGE_PRESENT_V = 20
BATTERY_LOW_VOLTAGE_V = 44.0
BATTERY_CURRENT_NOISE_A = 0.5
BATTERY_OUTPUT_FLOOR_W = 50
BATTERY_DISCHARGE_STOP_SOC_PCT = 7
BATTERY_RESUME_SOC_PCT = 50
PV_RESUME_THRESHOLD_W = 200

# 16S LiFePO4 OCV-to-SOC lookup (voltage_v, soc_pct)
LIFEPO4_16S_SOC_TABLE = [
    (44.0, 0),
    (49.6, 10),
    (51.2, 20),
    (52.0, 30),
    (52.4, 40),
    (52.6, 50),
    (52.8, 60),
    (53.0, 70),
    (53.3, 80),
    (53.6, 90),
    (54.4, 95),
    (58.4, 100),
]

POLL_INTERVAL_SECONDS = 5

MQTT_HOST = os.environ["MQTT_HOST"]
MQTT_PORT = int(os.environ["MQTT_PORT"])
MQTT_USER = os.environ["MQTT_USER"]
MQTT_PASSWORD = os.environ["MQTT_PASSWORD"]
BASE_TOPIC = "solar"
DISCOVERY_PREFIX = "homeassistant"
DEVICE_ID = "solar_pi"
UNIQUE_ID_PREFIX = "rasp"

NPE_MODE_TOPIC = f"{BASE_TOPIC}/npe_bonding/mode/set"
NPE_MODES = ("auto", "manual_on", "manual_off")
NPE_DEFAULT_MODE = "auto"
PV_EFFICIENCY_TOPIC = f"{BASE_TOPIC}/pv/efficiency/set"
PV2_RATIO_TOPIC = f"{BASE_TOPIC}/pv/pv2_ratio/set"
PV_EFFICIENCY_DEFAULT = 0.93
AVAILABILITY_TOPIC = f"{BASE_TOPIC}/status"
OUTPUT_PRIORITY_MODE_TOPIC = f"{BASE_TOPIC}/output_priority/mode/set"
OUTPUT_PRIORITY_MODES = ("auto", "force_sbu", "force_sub")
OUTPUT_PRIORITY_DEFAULT = "auto"
CHARGER_SOURCE_TOPIC = f"{BASE_TOPIC}/charger_source/set"
CHARGER_SOURCE_OPTIONS = ("solar_first", "utility_first", "solar_and_utility", "solar_only")
CHARGER_SOURCE_TO_PCP = {
    "utility_first": "PCP00",
    "solar_first": "PCP01",
    "solar_and_utility": "PCP02",
    "solar_only": "PCP03",
}


class ZmaiMeter:
    """Grid meter fed by MQTT pushes from a ZMAi-90 (OpenBeken + RN8209).

    The meter publishes on its own schedule, so freshness is tracked from message
    arrival rather than from a poll returning.
    """

    def __init__(self):
        self.power_w = None
        self.voltage_v = None
        self.current_a = None
        self.relay_is_on = None
        self._last_update_time = None

    def on_message(self, topic, payload, now):
        if not is_number(payload):
            return
        value = float(payload)
        if topic == ZMAI_POWER_TOPIC:
            self.power_w = value
            self._last_update_time = now
        elif topic == ZMAI_VOLTAGE_TOPIC:
            self.voltage_v = value
        elif topic == ZMAI_CURRENT_TOPIC:
            self.current_a = value
        elif topic == ZMAI_RELAY_TOPIC:
            self.relay_is_on = value != 0

    def has_recent_data(self, now, stale_seconds):
        if self._last_update_time is None:
            return False
        return (now - self._last_update_time) < stale_seconds


class NpeBonding:
    def __init__(self, pin, threshold_w, stable_seconds, battery_stale_seconds):
        self._threshold_w = threshold_w
        self._stable_seconds = stable_seconds
        self._battery_stale_seconds = battery_stale_seconds
        self._relay = DigitalOutputDevice(pin, active_high=True, initial_value=False)
        self._low_power_since = None
        self._last_battery_power_w = None
        self._last_battery_update_time = None
        self.mode = NPE_DEFAULT_MODE
        self.last_reasons = {}

    def decide(self, ac_input_voltage_v, grid_power_w, grid_online, battery_power_w, now):
        if self.mode == "manual_on":
            self._low_power_since = None
            return True
        if self.mode == "manual_off":
            self._low_power_since = None
            return False

        if battery_power_w is not None:
            self._last_battery_power_w = battery_power_w
            self._last_battery_update_time = now
        battery_reading_is_recent = (
            self._last_battery_update_time is not None
            and (now - self._last_battery_update_time) < self._battery_stale_seconds
        )
        held_battery_power_w = self._last_battery_power_w if battery_reading_is_recent else None

        grid_absent_by_inverter = ac_input_voltage_v is not None and ac_input_voltage_v < GRID_VOLTAGE_THRESHOLD_V
        grid_absent_by_meter = grid_power_w is not None and grid_power_w < self._threshold_w
        grid_absent_by_battery_failsafe = (
            not grid_online and held_battery_power_w is not None and held_battery_power_w > self._threshold_w
        )
        off_grid_signal = grid_absent_by_inverter or grid_absent_by_meter or grid_absent_by_battery_failsafe

        self.last_reasons = {
            "grid_absent_by_inverter": grid_absent_by_inverter,
            "grid_absent_by_meter": grid_absent_by_meter,
            "grid_absent_by_failsafe": grid_absent_by_battery_failsafe,
            "ac_input_v": ac_input_voltage_v,
            "grid_power_w": grid_power_w,
        }

        if not off_grid_signal:
            self._low_power_since = None
            return False

        if self._low_power_since is None:
            self._low_power_since = now
        return (now - self._low_power_since) >= self._stable_seconds

    def apply(self, desired_state):
        if desired_state and not self._relay.value:
            self._relay.on()
        elif not desired_state and self._relay.value:
            self._relay.off()

    @property
    def is_bonded(self):
        return bool(self._relay.value)


class Alarm:
    """Logs a fault once on transition, then repeats slowly while it persists."""

    def __init__(self, name, repeat_seconds):
        self._name = name
        self._repeat_seconds = repeat_seconds
        self._last_log_time = None
        self.active = False

    def update(self, is_faulted, detail, now):
        if not is_faulted:
            if self.active:
                print(f"ALARM CLEARED [{self._name}]", flush=True)
            self.active = False
            self._last_log_time = None
            return

        if not self.active:
            print(f"ALARM RAISED [{self._name}] {detail}", flush=True)
        elif (now - self._last_log_time) >= self._repeat_seconds:
            print(f"ALARM ACTIVE [{self._name}] {detail}", flush=True)
        else:
            return
        self.active = True
        self._last_log_time = now


class DaxtromnInverter(PI30Connection):
    """Daxtromn hybrid inverter polled over RS232 (PI30 protocol).

    Extends PI30Connection with QPIGS polling, data staleness tracking, and
    battery presence detection.
    """

    QPIGS_CMD = b"QPIGS\xb7\xa9\r"
    QPIGS_FIELD_NAMES = [
        "ac_input_voltage_v",
        "ac_input_frequency_hz",
        "ac_output_voltage_v",
        "ac_output_frequency_hz",
        "ac_output_apparent_power_va",
        "ac_output_power_w",
        "ac_output_load_pct",
        "bus_voltage_v",
        "battery_voltage_v",
        "battery_charging_current_a",
        "battery_capacity_pct",
        "heatsink_temperature_c",
        "pv1_input_current_a",
        "pv1_input_voltage_v",
        "battery_voltage_scc_v",
        "battery_discharge_current_a",
        "device_status",
        "rsv1",
        "rsv2",
        "pv1_power_w",
        "rsv3",
    ]

    def __init__(self, port, baud, stale_seconds):
        super().__init__(port, baud)
        self._stale_seconds = stale_seconds
        self._last_success_time = None
        self.last_data = None

    def _parse_qpigs(self, raw_response):
        frame_start = raw_response.find(b"(")
        if frame_start < 0:
            return None
        frame_end = raw_response.find(b"\r", frame_start)
        if frame_end < 0:
            return None
        qpigs_payload = raw_response[frame_start + 1 : frame_end]

        response_text = qpigs_payload.decode("ascii", errors="replace")
        response_fields = response_text.split()
        if len(response_fields) < len(self.QPIGS_FIELD_NAMES):
            return None

        parsed_data = {}
        for field_index, field_name in enumerate(self.QPIGS_FIELD_NAMES):
            raw_value = response_fields[field_index]
            if field_name == "device_status":
                parsed_data[field_name] = raw_value
            elif is_number(raw_value):
                parsed_data[field_name] = float(raw_value)
        return parsed_data

    def poll(self, now):
        for _attempt in range(2):
            raw_response = self.send_raw_command(self.QPIGS_CMD)
            if raw_response is None:
                return None
            parsed_data = self._parse_qpigs(raw_response)
            if parsed_data is not None:
                self.last_data = parsed_data
                self._last_success_time = now
                return parsed_data
        return None

    def has_recent_data(self, now):
        if self._last_success_time is None:
            return False
        return (now - self._last_success_time) < self._stale_seconds

    def alarm_detail(self):
        if self._last_success_time is None:
            return f"no valid read since start, port {self._port}"
        elapsed = int(time.time() - self._last_success_time)
        return f"silent for {elapsed}s, port {self._port}"

    def set_output_priority(self, pop_command):
        raw_response = self.send_command(pop_command)
        if raw_response is None:
            return False
        payload = self.extract_payload(raw_response)
        if payload is None:
            return False
        return "ACK" in payload

    def set_charger_source(self, pcp_command):
        raw_response = self.send_command(pcp_command)
        if raw_response is None:
            return False
        payload = self.extract_payload(raw_response)
        if payload is None:
            return False
        return "ACK" in payload

    def is_battery_present(self, inverter_data):
        if inverter_data is None:
            return False
        if inverter_data.get("battery_voltage_v", 0) > BATTERY_VOLTAGE_PRESENT_V:
            return True
        if inverter_data.get("battery_charging_current_a", 0) > BATTERY_CURRENT_NOISE_A:
            return True
        if inverter_data.get("battery_discharge_current_a", 0) > BATTERY_CURRENT_NOISE_A:
            return True
        if inverter_data.get("battery_capacity_pct", 0) > 0:
            return True
        ac_input_voltage = inverter_data.get("ac_input_voltage_v", 0)
        pv_power = inverter_data.get("pv1_power_w", 0)
        output_power = inverter_data.get("ac_output_power_w", 0)
        if ac_input_voltage < GRID_VOLTAGE_THRESHOLD_V and pv_power < 10 and output_power > BATTERY_OUTPUT_FLOOR_W:
            return True
        return False


def estimate_soc_from_voltage(voltage_v):
    table = LIFEPO4_16S_SOC_TABLE
    if voltage_v <= table[0][0]:
        return table[0][1]
    if voltage_v >= table[-1][0]:
        return table[-1][1]
    for index in range(1, len(table)):
        if voltage_v <= table[index][0]:
            low_voltage, low_soc = table[index - 1]
            high_voltage, high_soc = table[index]
            fraction = (voltage_v - low_voltage) / (high_voltage - low_voltage)
            return round(low_soc + fraction * (high_soc - low_soc))
    return table[-1][1]


class BatteryDischargeGuard:
    """Switches output priority to stop battery discharge when SOC is too low.

    In auto mode, sends POP01 (solar-first/SUB) when SOC drops to stop
    threshold. Resumes SBU only when solar is producing AND battery has
    charged to resume SOC (default 50%).
    """

    def __init__(self, stop_soc_pct, resume_soc_pct, pv_resume_threshold_w):
        self._stop_soc_pct = stop_soc_pct
        self._resume_soc_pct = resume_soc_pct
        self._pv_resume_threshold_w = pv_resume_threshold_w
        self.mode = OUTPUT_PRIORITY_DEFAULT
        self._discharge_blocked = False

    def decide(self, estimated_soc_pct, battery_present, pv_total_power_w):
        if self.mode == "force_sbu":
            self._discharge_blocked = False
            return "SBU"
        if self.mode == "force_sub":
            self._discharge_blocked = True
            return "SUB"

        if not battery_present:
            self._discharge_blocked = False
            return "SBU"

        if self._discharge_blocked:
            solar_is_producing = pv_total_power_w >= self._pv_resume_threshold_w
            battery_recovered = estimated_soc_pct >= self._resume_soc_pct
            if solar_is_producing and battery_recovered:
                self._discharge_blocked = False
                return "SBU"
            return "SUB"

        if estimated_soc_pct <= self._stop_soc_pct:
            self._discharge_blocked = True
            return "SUB"
        return "SBU"

    @property
    def is_discharge_blocked(self):
        return self._discharge_blocked


def sd_notify(message):
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    if addr.startswith("@"):
        addr = "\0" + addr[1:]
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        sock.connect(addr)
        sock.sendall(message.encode())
    finally:
        sock.close()


class SolarMonitor:
    """Main application: ties together meter, inverter, N-PE bonding, and MQTT."""

    def __init__(self):
        self.zmai = ZmaiMeter()
        self.npe = NpeBonding(NPE_RELAY_PIN, NPE_BOND_THRESHOLD_W, NPE_BOND_STABLE_SECONDS, NPE_BATTERY_STALE_SECONDS)
        self.inverter = DaxtromnInverter(INVERTER_PORT, INVERTER_BAUD, INVERTER_STALE_SECONDS)
        self.inverter_alarm = Alarm("inverter-silent", ALARM_REPEAT_SECONDS)
        self.failsafe_alarm = Alarm("npe-failsafe-blind", ALARM_REPEAT_SECONDS)
        self.battery_low_alarm = Alarm("battery-low-voltage", ALARM_REPEAT_SECONDS)
        self.discharge_guard = BatteryDischargeGuard(BATTERY_DISCHARGE_STOP_SOC_PCT, BATTERY_RESUME_SOC_PCT, PV_RESUME_THRESHOLD_W)
        self._last_applied_priority = None
        self._last_applied_charger_source = None
        self._pending_charger_source = None
        self.pv_efficiency = PV_EFFICIENCY_DEFAULT
        self.pv2_pv1_ratio = PV2_PV1_RATIO_DEFAULT
        self.battery_charge_energy_kwh = 0.0
        self.battery_discharge_energy_kwh = 0.0
        self.last_battery_cycle_time = None
        self.client = mqtt.Client()
        self._source_mtimes = self._snapshot_source_mtimes()

    def _snapshot_source_mtimes(self):
        source_directory = os.path.dirname(os.path.abspath(__file__))
        source_files = glob.glob(os.path.join(source_directory, "*.py"))
        return {path: os.path.getmtime(path) for path in source_files}

    def _source_files_changed(self):
        for path, original_mtime in self._source_mtimes.items():
            if not os.path.exists(path):
                continue
            if os.path.getmtime(path) != original_mtime:
                return True
        return False

    def _on_connect(self, client, userdata, flags, rc):
        client.publish(AVAILABILITY_TOPIC, "online", retain=True)
        client.subscribe(NPE_MODE_TOPIC)
        client.subscribe(OUTPUT_PRIORITY_MODE_TOPIC)
        client.subscribe(CHARGER_SOURCE_TOPIC)
        client.subscribe(PV_EFFICIENCY_TOPIC)
        client.subscribe(PV2_RATIO_TOPIC)
        client.subscribe(f"{ZMAI_TOPIC_PREFIX}/+/get")
        self._publish_discovery()
        print("mqtt connected, subscriptions and discovery re-armed", flush=True)

    def _on_message(self, client, userdata, message):
        payload = message.payload.decode().strip()
        if message.topic == NPE_MODE_TOPIC:
            if payload in NPE_MODES:
                self.npe.mode = payload
            return
        if message.topic == OUTPUT_PRIORITY_MODE_TOPIC:
            if payload in OUTPUT_PRIORITY_MODES:
                self.discharge_guard.mode = payload
                print(f"output priority mode set to {payload}", flush=True)
            return
        if message.topic == CHARGER_SOURCE_TOPIC:
            if payload in CHARGER_SOURCE_OPTIONS:
                self._pending_charger_source = payload
                print(f"charger source requested: {payload}", flush=True)
            return
        if message.topic == PV_EFFICIENCY_TOPIC:
            if is_number(payload):
                value = float(payload)
                if 0.5 <= value <= 1.0:
                    self.pv_efficiency = value
                    print(f"pv efficiency set to {value}", flush=True)
            return
        if message.topic == PV2_RATIO_TOPIC:
            if is_number(payload):
                value = float(payload)
                if 0.1 <= value <= 1.0:
                    self.pv2_pv1_ratio = value
                    print(f"pv2/pv1 ratio set to {value}", flush=True)
            return
        self.zmai.on_message(message.topic, payload, time.time())

    def _publish_discovery(self):
        device_info = {"identifiers": [DEVICE_ID], "name": "rasp", "manufacturer": "Daxtromn/ZMAi-90"}
        availability = [{"topic": AVAILABILITY_TOPIC, "payload_available": "online", "payload_not_available": "offline"}]

        sensors = [
            ("zmai_power", "Grid Power (ZMAi-90)", f"{BASE_TOPIC}/zmai/power_w", "W", "power"),
            ("zmai_voltage", "Grid Voltage (ZMAi-90)", f"{BASE_TOPIC}/zmai/voltage_v", "V", "voltage"),
            ("zmai_current", "Grid Current (ZMAi-90)", f"{BASE_TOPIC}/zmai/current_a", "A", "current"),
            ("inverter_ac_output_power", "Total House Consumption", f"{BASE_TOPIC}/inverter/ac_output_power_w", "W", "power"),
            ("inverter_pv_input_power", "PV1 Power", f"{BASE_TOPIC}/inverter/pv1_power_w", "W", "power"),
            ("inverter_ac_input_voltage", "Daxtromn AC Input Voltage", f"{BASE_TOPIC}/inverter/ac_input_voltage_v", "V", "voltage"),
            ("inverter_pv_input_voltage", "PV1 Input Voltage", f"{BASE_TOPIC}/inverter/pv1_input_voltage_v", "V", "voltage"),
            ("inverter_battery_capacity", "Battery Capacity", f"{BASE_TOPIC}/inverter/battery_capacity_pct", "%", "battery"),
            ("battery_power", "Battery", f"{BASE_TOPIC}/derived/battery_power_w", "W", "power"),
            ("battery_charge_power", "Battery Charge 14.8kW", f"{BASE_TOPIC}/derived/battery_charge_power_w", "W", "power"),
            ("battery_discharge_power", "Battery Discharge 14.8kW", f"{BASE_TOPIC}/derived/battery_discharge_power_w", "W", "power"),
            ("battery_soc_estimated", "Battery SOC (Estimated)", f"{BASE_TOPIC}/derived/battery_soc_estimated_pct", "%", "battery"),
            ("pv2_power", "PV2 Power", f"{BASE_TOPIC}/derived/pv2_power_w", "W", "power"),
            ("pv_total_power", "PV Total Power", f"{BASE_TOPIC}/derived/pv_total_power_w", "W", "power"),
        ]
        for object_id, name, state_topic, unit, device_class in sensors:
            config = {
                "name": name,
                "unique_id": f"{UNIQUE_ID_PREFIX}_{object_id}",
                "state_topic": state_topic,
                "unit_of_measurement": unit,
                "device_class": device_class,
                "state_class": "measurement",
                "availability": availability,
                "device": device_info,
            }
            self.client.publish(f"{DISCOVERY_PREFIX}/sensor/{DEVICE_ID}/{object_id}/config", json.dumps(config), retain=True)

        energy_sensors = [
            ("battery_charge_energy", "Battery Charge Energy 14.8kW", f"{BASE_TOPIC}/derived/battery_charge_energy_kwh", "kWh", "energy"),
            ("battery_discharge_energy", "Battery Discharge Energy 14.8kW", f"{BASE_TOPIC}/derived/battery_discharge_energy_kwh", "kWh", "energy"),
        ]
        for object_id, name, state_topic, unit, device_class in energy_sensors:
            config = {
                "name": name,
                "unique_id": f"{UNIQUE_ID_PREFIX}_{object_id}",
                "state_topic": state_topic,
                "unit_of_measurement": unit,
                "device_class": device_class,
                "state_class": "total_increasing",
                "availability": availability,
                "device": device_info,
            }
            self.client.publish(f"{DISCOVERY_PREFIX}/sensor/{DEVICE_ID}/{object_id}/config", json.dumps(config), retain=True)

        zmai_data_config = {
            "name": "ZMAi-90 Data Status",
            "unique_id": f"{UNIQUE_ID_PREFIX}_zmai_data",
            "state_topic": f"{BASE_TOPIC}/zmai/data_status",
            "availability": availability,
            "device": device_info,
        }
        self.client.publish(f"{DISCOVERY_PREFIX}/sensor/{DEVICE_ID}/zmai_data/config", json.dumps(zmai_data_config), retain=True)

        inverter_data_config = {
            "name": "Daxtromn Data Status",
            "unique_id": f"{UNIQUE_ID_PREFIX}_inverter_data",
            "state_topic": f"{BASE_TOPIC}/inverter/data_status",
            "availability": availability,
            "device": device_info,
        }
        self.client.publish(f"{DISCOVERY_PREFIX}/sensor/{DEVICE_ID}/inverter_data/config", json.dumps(inverter_data_config), retain=True)

        inverter_problem_config = {
            "name": "Daxtromn Link Fault",
            "unique_id": f"{UNIQUE_ID_PREFIX}_inverter_fault",
            "state_topic": f"{BASE_TOPIC}/inverter/data_status",
            "payload_on": "offline",
            "payload_off": "online",
            "device_class": "problem",
            "availability": availability,
            "device": device_info,
        }
        self.client.publish(f"{DISCOVERY_PREFIX}/binary_sensor/{DEVICE_ID}/inverter_fault/config", json.dumps(inverter_problem_config), retain=True)

        failsafe_config = {
            "name": "N-PE Failsafe Blind",
            "unique_id": f"{UNIQUE_ID_PREFIX}_npe_failsafe",
            "state_topic": f"{BASE_TOPIC}/npe_bonding/failsafe_status",
            "payload_on": "blind",
            "payload_off": "ok",
            "device_class": "safety",
            "availability": availability,
            "device": device_info,
        }
        self.client.publish(f"{DISCOVERY_PREFIX}/binary_sensor/{DEVICE_ID}/npe_failsafe/config", json.dumps(failsafe_config), retain=True)

        npe_binary_config = {
            "name": "N-PE Bonded",
            "unique_id": f"{UNIQUE_ID_PREFIX}_npe_bonded",
            "state_topic": f"{BASE_TOPIC}/npe_bonding/state",
            "payload_on": "ON",
            "payload_off": "OFF",
            "availability": availability,
            "device": device_info,
        }
        self.client.publish(f"{DISCOVERY_PREFIX}/binary_sensor/{DEVICE_ID}/npe_bonded/config", json.dumps(npe_binary_config), retain=True)

        battery_low_config = {
            "name": "Battery Low Voltage",
            "unique_id": f"{UNIQUE_ID_PREFIX}_battery_low",
            "state_topic": f"{BASE_TOPIC}/battery/low_voltage_status",
            "payload_on": "low",
            "payload_off": "ok",
            "device_class": "problem",
            "availability": availability,
            "device": device_info,
        }
        self.client.publish(f"{DISCOVERY_PREFIX}/binary_sensor/{DEVICE_ID}/battery_low/config", json.dumps(battery_low_config), retain=True)

        npe_select_config = {
            "name": "N-PE Bonding Mode",
            "unique_id": f"{UNIQUE_ID_PREFIX}_npe_mode",
            "state_topic": f"{BASE_TOPIC}/npe_bonding/mode/state",
            "command_topic": NPE_MODE_TOPIC,
            "options": list(NPE_MODES),
            "availability": availability,
            "device": device_info,
        }
        self.client.publish(f"{DISCOVERY_PREFIX}/select/{DEVICE_ID}/npe_mode/config", json.dumps(npe_select_config), retain=True)

        output_priority_config = {
            "name": "Output Priority",
            "unique_id": f"{UNIQUE_ID_PREFIX}_output_priority",
            "state_topic": f"{BASE_TOPIC}/output_priority/state",
            "availability": availability,
            "device": device_info,
        }
        self.client.publish(f"{DISCOVERY_PREFIX}/sensor/{DEVICE_ID}/output_priority/config", json.dumps(output_priority_config), retain=True)

        discharge_blocked_config = {
            "name": "Battery Discharge Blocked",
            "unique_id": f"{UNIQUE_ID_PREFIX}_discharge_blocked",
            "state_topic": f"{BASE_TOPIC}/output_priority/discharge_blocked",
            "payload_on": "ON",
            "payload_off": "OFF",
            "availability": availability,
            "device": device_info,
        }
        self.client.publish(f"{DISCOVERY_PREFIX}/binary_sensor/{DEVICE_ID}/discharge_blocked/config", json.dumps(discharge_blocked_config), retain=True)

        output_priority_mode_config = {
            "name": "Output Priority Mode",
            "unique_id": f"{UNIQUE_ID_PREFIX}_output_priority_mode",
            "state_topic": f"{BASE_TOPIC}/output_priority/mode/state",
            "command_topic": OUTPUT_PRIORITY_MODE_TOPIC,
            "options": list(OUTPUT_PRIORITY_MODES),
            "availability": availability,
            "device": device_info,
        }
        self.client.publish(f"{DISCOVERY_PREFIX}/select/{DEVICE_ID}/output_priority_mode/config", json.dumps(output_priority_mode_config), retain=True)

        charger_source_config = {
            "name": "Charger Source",
            "unique_id": f"{UNIQUE_ID_PREFIX}_charger_source",
            "state_topic": f"{BASE_TOPIC}/charger_source/state",
            "command_topic": CHARGER_SOURCE_TOPIC,
            "options": list(CHARGER_SOURCE_OPTIONS),
            "availability": availability,
            "device": device_info,
        }
        self.client.publish(f"{DISCOVERY_PREFIX}/select/{DEVICE_ID}/charger_source/config", json.dumps(charger_source_config), retain=True)

    def run(self):
        self.client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.will_set(AVAILABILITY_TOPIC, "offline", retain=True)
        self.client.connect(MQTT_HOST, MQTT_PORT)
        self.client.loop_start()

        print("solar_monitor started", flush=True)
        sd_notify("READY=1")
        while True:
            cycle_start = time.time()
            sd_notify("WATCHDOG=1")
            battery_power_w = None
            pv_total_power_w = 0

            if self.zmai.power_w is not None:
                self.client.publish(f"{BASE_TOPIC}/zmai/power_w", self.zmai.power_w)
            if self.zmai.voltage_v is not None:
                self.client.publish(f"{BASE_TOPIC}/zmai/voltage_v", self.zmai.voltage_v)
            if self.zmai.current_a is not None:
                self.client.publish(f"{BASE_TOPIC}/zmai/current_a", self.zmai.current_a)
            zmai_online = self.zmai.has_recent_data(cycle_start, ZMAI_STALE_SECONDS)
            self.client.publish(f"{BASE_TOPIC}/zmai/data_status", "online" if zmai_online else "offline")
            zmai_has_reading = zmai_online and self.zmai.power_w is not None
            grid_power_for_npe = self.zmai.power_w if zmai_has_reading else None
            zmai_power_above_noise = zmai_has_reading and abs(self.zmai.power_w) >= ZMAI_NOISE_THRESHOLD_W
            grid_power_for_pv2 = self.zmai.power_w if zmai_power_above_noise else None

            inverter_data = self.inverter.poll(cycle_start)
            if inverter_data is not None:
                for key, value in inverter_data.items():
                    self.client.publish(f"{BASE_TOPIC}/inverter/{key}", value)

                if "battery_voltage_v" in inverter_data and "battery_charging_current_a" in inverter_data and "battery_discharge_current_a" in inverter_data:
                    battery_power_w = (inverter_data["battery_discharge_current_a"] - inverter_data["battery_charging_current_a"]) * inverter_data["battery_voltage_v"]
                    self.client.publish(f"{BASE_TOPIC}/derived/battery_power_w", battery_power_w)
                    self.client.publish(f"{BASE_TOPIC}/derived/battery_charge_power_w", max(-battery_power_w, 0))
                    self.client.publish(f"{BASE_TOPIC}/derived/battery_discharge_power_w", -max(battery_power_w, 0))

                    if self.last_battery_cycle_time is not None:
                        elapsed_hours = (cycle_start - self.last_battery_cycle_time) / 3600
                        if battery_power_w < 0:
                            self.battery_charge_energy_kwh += abs(battery_power_w) * elapsed_hours / 1000
                        elif battery_power_w > 0:
                            self.battery_discharge_energy_kwh += battery_power_w * elapsed_hours / 1000
                        self.client.publish(f"{BASE_TOPIC}/derived/battery_charge_energy_kwh", round(self.battery_charge_energy_kwh, 3))
                        self.client.publish(f"{BASE_TOPIC}/derived/battery_discharge_energy_kwh", round(self.battery_discharge_energy_kwh, 3))
                    self.last_battery_cycle_time = cycle_start

                battery_contribution_w = battery_power_w if self.inverter.is_battery_present(inverter_data) else 0.0

                if "ac_output_power_w" in inverter_data and "pv1_power_w" in inverter_data and battery_contribution_w is not None:
                    pv_efficiency = self.pv_efficiency
                    pv1_power_w = inverter_data["pv1_power_w"]
                    ac_output_w = inverter_data["ac_output_power_w"]
                    total_pv_w = None

                    if grid_power_for_pv2 is not None:
                        device_status = inverter_data.get("device_status", "00000000")
                        ac_charging_from_grid = len(device_status) > 7 and device_status[7] == "1"
                        total_pv_as_import = (ac_output_w - grid_power_for_pv2) / pv_efficiency - battery_contribution_w
                        if ac_charging_from_grid or total_pv_as_import >= pv1_power_w:
                            total_pv_w = total_pv_as_import

                    if total_pv_w is None:
                        total_pv_w = ac_output_w / pv_efficiency - battery_contribution_w

                    if total_pv_w < pv1_power_w and pv1_power_w > PV2_RATIO_MIN_PV1_W:
                        total_pv_w = pv1_power_w * (1 + self.pv2_pv1_ratio)

                    pv2_power_w = max(total_pv_w - pv1_power_w, 0)
                    pv_total_power_w = pv1_power_w + pv2_power_w
                    self.client.publish(f"{BASE_TOPIC}/derived/pv2_power_w", pv2_power_w)
                    self.client.publish(f"{BASE_TOPIC}/derived/pv_total_power_w", pv_total_power_w)
                    self.client.publish(f"{BASE_TOPIC}/pv/efficiency/state", pv_efficiency)

            inverter_online = self.inverter.has_recent_data(cycle_start)
            self.client.publish(f"{BASE_TOPIC}/inverter/data_status", "online" if inverter_online else "offline")
            self.inverter_alarm.update(not inverter_online, self.inverter.alarm_detail(), cycle_start)

            ac_input_voltage_v = inverter_data.get("ac_input_voltage_v") if inverter_data is not None else None

            failsafe_blind = not inverter_online and not zmai_online
            self.client.publish(f"{BASE_TOPIC}/npe_bonding/failsafe_status", "blind" if failsafe_blind else "ok")
            self.failsafe_alarm.update(failsafe_blind, "inverter and ZMAi-90 both down, N-PE cannot detect grid loss", cycle_start)

            battery_present = self.inverter.is_battery_present(inverter_data)
            self.client.publish(f"{BASE_TOPIC}/derived/battery_present", "ON" if battery_present else "OFF")

            battery_voltage = inverter_data.get("battery_voltage_v", 0) if inverter_data is not None else 0
            estimated_soc = 0
            if battery_present and battery_voltage > 0:
                estimated_soc = estimate_soc_from_voltage(battery_voltage)
                self.client.publish(f"{BASE_TOPIC}/derived/battery_soc_estimated_pct", estimated_soc)
            battery_is_low = battery_present and battery_voltage < BATTERY_LOW_VOLTAGE_V
            self.battery_low_alarm.update(battery_is_low, f"battery voltage {battery_voltage}V (threshold {BATTERY_LOW_VOLTAGE_V}V)", cycle_start)
            self.client.publish(f"{BASE_TOPIC}/battery/low_voltage_status", "low" if battery_is_low else "ok")

            desired_priority = self.discharge_guard.decide(estimated_soc, battery_present, pv_total_power_w)
            if desired_priority != self._last_applied_priority:
                command = "POP02" if desired_priority == "SBU" else "POP01"
                if self.inverter.set_output_priority(command):
                    self._last_applied_priority = desired_priority
                    print(f"output priority: {desired_priority} (SOC {estimated_soc}%)", flush=True)
            self.client.publish(f"{BASE_TOPIC}/output_priority/state", self._last_applied_priority or "unknown")
            self.client.publish(f"{BASE_TOPIC}/output_priority/mode/state", self.discharge_guard.mode)
            self.client.publish(f"{BASE_TOPIC}/output_priority/discharge_blocked", "ON" if self.discharge_guard.is_discharge_blocked else "OFF")

            if self._pending_charger_source is not None and self._pending_charger_source != self._last_applied_charger_source:
                pcp_command = CHARGER_SOURCE_TO_PCP[self._pending_charger_source]
                if self.inverter.set_charger_source(pcp_command):
                    self._last_applied_charger_source = self._pending_charger_source
                    print(f"charger source: {self._last_applied_charger_source}", flush=True)
            self.client.publish(f"{BASE_TOPIC}/charger_source/state", self._last_applied_charger_source or "unknown")

            desired_bond_state = self.npe.decide(ac_input_voltage_v, grid_power_for_npe, zmai_online, battery_power_w, cycle_start)
            if battery_is_low:
                desired_bond_state = False
            self.npe.apply(desired_bond_state)
            self.client.publish(f"{BASE_TOPIC}/npe_bonding/state", "ON" if self.npe.is_bonded else "OFF")
            for reason_key, reason_value in self.npe.last_reasons.items():
                self.client.publish(f"{BASE_TOPIC}/npe_bonding/debug/{reason_key}", reason_value)
            self.client.publish(f"{BASE_TOPIC}/npe_bonding/mode/state", self.npe.mode)

            if self._source_files_changed():
                print("source files changed, restarting", flush=True)
                return

            elapsed = time.time() - cycle_start
            remaining = POLL_INTERVAL_SECONDS - elapsed
            if remaining > 0:
                time.sleep(remaining)


def main():
    monitor = SolarMonitor()
    monitor.run()


if __name__ == "__main__":
    main()
