import json
import os
import socket
import time

import paho.mqtt.client as mqtt
import serial
from gpiozero import DigitalOutputDevice

# Grid meter is a ZMAi-90 (BK7231N/CBU) running OpenBeken with the RN8209 driver.
# It pushes readings over MQTT roughly once a second; the previous Tomzn was polled
# over the local network with tinytuya. See solar_monitor_tomzn.py for that version.
ZMAI_TOPIC_PREFIX = "energy-smart-meter-zmai-90"
ZMAI_POWER_TOPIC = f"{ZMAI_TOPIC_PREFIX}/power/get"
ZMAI_VOLTAGE_TOPIC = f"{ZMAI_TOPIC_PREFIX}/voltage/get"
ZMAI_CURRENT_TOPIC = f"{ZMAI_TOPIC_PREFIX}/current/get"
ZMAI_RELAY_TOPIC = f"{ZMAI_TOPIC_PREFIX}/1/get"

NPE_RELAY_PIN = 27
NPE_BOND_THRESHOLD_W = 30
NPE_BOND_STABLE_SECONDS = 3
NPE_BATTERY_STALE_SECONDS = 30
GRID_VOLTAGE_THRESHOLD_V = 50
ZMAI_STALE_SECONDS = 15

# by-id, not /dev/ttyUSB0: the adapter renumbers on replug and the hardcoded path
# left the inverter silent. this symlink follows the FTDI chip's serial number.
INVERTER_PORT = "/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A5069RR4-if00-port0"
INVERTER_BAUD = 2400
INVERTER_STALE_SECONDS = 30
ALARM_REPEAT_SECONDS = 300

# No battery fitted yet. PV2 is derived from the inverter's own output, so it must
# still be computed without a battery term - the Daxtromn generates on PV2 but does
# not report that string over RS232.
BATTERY_INSTALLED = False

POLL_INTERVAL_SECONDS = 5

MQTT_HOST = os.environ["MQTT_HOST"]
MQTT_PORT = int(os.environ["MQTT_PORT"])
MQTT_USER = os.environ["MQTT_USER"]
MQTT_PASSWORD = os.environ["MQTT_PASSWORD"]
BASE_TOPIC = "solar"
DISCOVERY_PREFIX = "homeassistant"
DEVICE_ID = "solar_pi"

NPE_MODE_TOPIC = f"{BASE_TOPIC}/npe_bonding/mode/set"
NPE_MODES = ("auto", "manual_on", "manual_off")
# No battery fitted yet: the inverter runs grid + PV only, so it cannot island and
# N-PE bonding is never required. The detection logic below stays live and reports,
# it just cannot drive the relay. Set this back to "auto" when the battery is in.
NPE_DEFAULT_MODE = "manual_off"
AVAILABILITY_TOPIC = f"{BASE_TOPIC}/status"


class ZmaiMeter:
    """Grid meter fed by MQTT pushes, not polled.

    The meter publishes on its own schedule, so freshness is tracked from message
    arrival rather than from a poll returning. A meter that stops publishing goes
    stale on its own and drops out of the bonding decision, same as a Tomzn that
    stopped answering.
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


def is_number(text):
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.lstrip("-+").replace(".", "", 1).isdigit():
        return True
    return False


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

    def decide(self, ac_input_voltage_v, grid_power_w, grid_relay_is_on, grid_online, battery_power_w, now):
        if self.mode == "manual_on":
            self._low_power_since = None
            return True
        if self.mode == "manual_off":
            self._low_power_since = None
            return False

        # Inverter serial reads fail intermittently (EMI while inverting), which drops
        # battery_power_w to None for a cycle. Hold the last known reading for a grace
        # window instead of losing the failsafe signal on every transient read error.
        if battery_power_w is not None:
            self._last_battery_power_w = battery_power_w
            self._last_battery_update_time = now
        battery_reading_is_recent = (
            self._last_battery_update_time is not None
            and (now - self._last_battery_update_time) < self._battery_stale_seconds
        )
        held_battery_power_w = self._last_battery_power_w if battery_reading_is_recent else None

        grid_absent_by_inverter = ac_input_voltage_v is not None and ac_input_voltage_v < GRID_VOLTAGE_THRESHOLD_V
        # Under the threshold means the inverter has transferred to PV/battery and its
        # output is no longer bonded by the grid. Relay open means we islanded the house
        # deliberately. The meter's voltage is useless here: it reads the line side and
        # stays live even with the relay open.
        grid_relay_is_open = grid_relay_is_on is not None and not grid_relay_is_on
        grid_absent_by_meter = grid_relay_is_open or (grid_power_w is not None and grid_power_w < self._threshold_w)
        # Meter offline drops our main off-grid signal. Battery discharging while the
        # meter is unreachable is itself evidence of an unbonded off-grid fault.
        grid_absent_by_battery_failsafe = (
            not grid_online and held_battery_power_w is not None and held_battery_power_w > self._threshold_w
        )
        off_grid_signal = grid_absent_by_inverter or grid_absent_by_meter or grid_absent_by_battery_failsafe

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
    """Logs a fault once on transition, then repeats slowly while it persists.

    A fault printed every 5s poll buries itself: the dead-inverter fault logged 75977
    identical lines and nobody saw it. Transitions are the signal, not the repetition.
    """

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


class DaxtromnInverter:
    """Daxtromn hybrid inverter polled over RS232 (PI30 protocol).

    The inverter leaks its internal Pylon BMS traffic onto the RS232 line. On ~10%
    of queries this interleaves with the QPIGS response and corrupts the '(' start
    byte. The poll method retries once, which brings the effective success rate above
    99%.
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
    ]

    def __init__(self, port, baud, stale_seconds):
        self._port = port
        self._baud = baud
        self._stale_seconds = stale_seconds
        self._last_success_time = None
        self.last_data = None

    def _query_serial(self):
        """Send QPIGS and return all raw bytes received, or None if port missing."""
        if not os.path.exists(self._port):
            return None
        connection = serial.Serial(self._port, self._baud, timeout=2)
        connection.reset_input_buffer()
        connection.write(self.QPIGS_CMD)
        raw_response = b""
        read_deadline = time.time() + 2
        while time.time() < read_deadline:
            waiting = connection.in_waiting
            if waiting > 0:
                raw_response += connection.read(waiting)
            else:
                incoming_byte = connection.read(1)
                if not incoming_byte:
                    break
                raw_response += incoming_byte
        connection.reset_input_buffer()
        connection.close()
        return raw_response

    def _parse_qpigs(self, raw_response):
        """Extract the '('-prefixed PI30 frame and parse its fields."""
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
        """Query QPIGS and return parsed data dict, or None on failure.

        Retries once on a corrupted frame (Pylon BMS interference).
        """
        for _attempt in range(2):
            raw_response = self._query_serial()
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


def on_mqtt_connect(client, userdata, flags, rc):
    """Subscriptions and retained discovery do not survive a broker restart.

    paho reconnects on its own, but silently comes back without them, which used to
    leave the HA mode select dead until the service was restarted. Re-arm both here.
    """
    client.publish(AVAILABILITY_TOPIC, "online", retain=True)
    client.subscribe(NPE_MODE_TOPIC)
    client.subscribe(f"{ZMAI_TOPIC_PREFIX}/+/get")  # includes 1/get, the grid relay state
    publish_discovery(client)
    print("mqtt connected, subscriptions and discovery re-armed", flush=True)


def on_mqtt_message(client, userdata, message):
    payload = message.payload.decode().strip()
    if message.topic == NPE_MODE_TOPIC:
        if payload in NPE_MODES:
            userdata["npe"].mode = payload
        return
    userdata["zmai"].on_message(message.topic, payload, time.time())


def publish_discovery(client):
    device_info = {"identifiers": [DEVICE_ID], "name": "rasp", "manufacturer": "Daxtromn/ZMAi-90"}
    availability = [{"topic": AVAILABILITY_TOPIC, "payload_available": "online", "payload_not_available": "offline"}]

    sensors = [
        ("zmai_power", "Grid Power (ZMAi-90)", f"{BASE_TOPIC}/zmai/power_w", "W", "power"),
        ("zmai_voltage", "Grid Voltage (ZMAi-90)", f"{BASE_TOPIC}/zmai/voltage_v", "V", "voltage"),
        ("zmai_current", "Grid Current (ZMAi-90)", f"{BASE_TOPIC}/zmai/current_a", "A", "current"),
        ("inverter_ac_output_power", "Daxtromn Total Consumption", f"{BASE_TOPIC}/inverter/ac_output_power_w", "W", "power"),
        ("inverter_pv_input_power", "PV1 Power", f"{BASE_TOPIC}/inverter/pv1_power_w", "W", "power"),
        ("inverter_ac_input_voltage", "Daxtromn AC Input Voltage", f"{BASE_TOPIC}/inverter/ac_input_voltage_v", "V", "voltage"),
        ("inverter_pv_input_voltage", "PV1 Input Voltage", f"{BASE_TOPIC}/inverter/pv1_input_voltage_v", "V", "voltage"),
        ("inverter_battery_capacity", "Battery Capacity", f"{BASE_TOPIC}/inverter/battery_capacity_pct", "%", "battery"),
        ("battery_power", "Battery", f"{BASE_TOPIC}/derived/battery_power_w", "W", "power"),
        ("battery_charge_power", "Battery Charge Power", f"{BASE_TOPIC}/derived/battery_charge_power_w", "W", "power"),
        ("battery_discharge_power", "Battery Discharge Power", f"{BASE_TOPIC}/derived/battery_discharge_power_w", "W", "power"),
        ("pv2_power", "PV2 Power", f"{BASE_TOPIC}/derived/pv2_power_w", "W", "power"),
        ("pv_total_power", "PV Total Power", f"{BASE_TOPIC}/derived/pv_total_power_w", "W", "power"),
    ]
    for object_id, name, state_topic, unit, device_class in sensors:
        config = {
            "name": name,
            "unique_id": f"{DEVICE_ID}_{object_id}",
            "state_topic": state_topic,
            "unit_of_measurement": unit,
            "device_class": device_class,
            "state_class": "measurement",
            "availability": availability,
            "device": device_info,
        }
        client.publish(f"{DISCOVERY_PREFIX}/sensor/{DEVICE_ID}/{object_id}/config", json.dumps(config), retain=True)

    zmai_data_config = {
        "name": "ZMAi-90 Data Status",
        "unique_id": f"{DEVICE_ID}_zmai_data",
        "state_topic": f"{BASE_TOPIC}/zmai/data_status",
        "availability": availability,
        "device": device_info,
    }
    client.publish(f"{DISCOVERY_PREFIX}/sensor/{DEVICE_ID}/zmai_data/config", json.dumps(zmai_data_config), retain=True)

    inverter_data_config = {
        "name": "Daxtromn Data Status",
        "unique_id": f"{DEVICE_ID}_inverter_data",
        "state_topic": f"{BASE_TOPIC}/inverter/data_status",
        "availability": availability,
        "device": device_info,
    }
    client.publish(f"{DISCOVERY_PREFIX}/sensor/{DEVICE_ID}/inverter_data/config", json.dumps(inverter_data_config), retain=True)

    inverter_problem_config = {
        "name": "Daxtromn Link Fault",
        "unique_id": f"{DEVICE_ID}_inverter_fault",
        "state_topic": f"{BASE_TOPIC}/inverter/data_status",
        "payload_on": "offline",
        "payload_off": "online",
        "device_class": "problem",
        "availability": availability,
        "device": device_info,
    }
    client.publish(f"{DISCOVERY_PREFIX}/binary_sensor/{DEVICE_ID}/inverter_fault/config", json.dumps(inverter_problem_config), retain=True)

    failsafe_config = {
        "name": "N-PE Failsafe Blind",
        "unique_id": f"{DEVICE_ID}_npe_failsafe",
        "state_topic": f"{BASE_TOPIC}/npe_bonding/failsafe_status",
        "payload_on": "blind",
        "payload_off": "ok",
        "device_class": "safety",
        "availability": availability,
        "device": device_info,
    }
    client.publish(f"{DISCOVERY_PREFIX}/binary_sensor/{DEVICE_ID}/npe_failsafe/config", json.dumps(failsafe_config), retain=True)

    npe_binary_config = {
        "name": "N-PE Bonded",
        "unique_id": f"{DEVICE_ID}_npe_bonded",
        "state_topic": f"{BASE_TOPIC}/npe_bonding/state",
        "payload_on": "ON",
        "payload_off": "OFF",
        "availability": availability,
        "device": device_info,
    }
    client.publish(f"{DISCOVERY_PREFIX}/binary_sensor/{DEVICE_ID}/npe_bonded/config", json.dumps(npe_binary_config), retain=True)

    npe_select_config = {
        "name": "N-PE Bonding Mode",
        "unique_id": f"{DEVICE_ID}_npe_mode",
        "state_topic": f"{BASE_TOPIC}/npe_bonding/mode/state",
        "command_topic": NPE_MODE_TOPIC,
        "options": list(NPE_MODES),
        "availability": availability,
        "device": device_info,
    }
    client.publish(f"{DISCOVERY_PREFIX}/select/{DEVICE_ID}/npe_mode/config", json.dumps(npe_select_config), retain=True)


def main():
    zmai = ZmaiMeter()
    npe = NpeBonding(NPE_RELAY_PIN, NPE_BOND_THRESHOLD_W, NPE_BOND_STABLE_SECONDS, NPE_BATTERY_STALE_SECONDS)
    inverter = DaxtromnInverter(INVERTER_PORT, INVERTER_BAUD, INVERTER_STALE_SECONDS)
    inverter_alarm = Alarm("inverter-silent", ALARM_REPEAT_SECONDS)
    failsafe_alarm = Alarm("npe-failsafe-blind", ALARM_REPEAT_SECONDS)

    client = mqtt.Client(userdata={"npe": npe, "zmai": zmai})
    client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
    client.on_connect = on_mqtt_connect
    client.on_message = on_mqtt_message
    client.will_set(AVAILABILITY_TOPIC, "offline", retain=True)
    client.connect(MQTT_HOST, MQTT_PORT)
    client.loop_start()

    print("solar_monitor started", flush=True)
    sd_notify("READY=1")
    while True:
        cycle_start = time.time()
        sd_notify("WATCHDOG=1")
        battery_power_w = None

        # The meter pushes over MQTT, so there is nothing to poll here; paho's network
        # thread has already filled these in between cycles.
        if zmai.power_w is not None:
            client.publish(f"{BASE_TOPIC}/zmai/power_w", zmai.power_w)
        if zmai.voltage_v is not None:
            client.publish(f"{BASE_TOPIC}/zmai/voltage_v", zmai.voltage_v)
        if zmai.current_a is not None:
            client.publish(f"{BASE_TOPIC}/zmai/current_a", zmai.current_a)
        zmai_online = zmai.has_recent_data(cycle_start, ZMAI_STALE_SECONDS)
        client.publish(f"{BASE_TOPIC}/zmai/data_status", "online" if zmai_online else "offline")
        grid_power_for_decision = zmai.power_w if zmai_online else None

        inverter_data = inverter.poll(cycle_start)
        if inverter_data is not None:
            for key, value in inverter_data.items():
                client.publish(f"{BASE_TOPIC}/inverter/{key}", value)

            if "battery_voltage_v" in inverter_data and "battery_charging_current_a" in inverter_data and "battery_discharge_current_a" in inverter_data:
                battery_power_w = (inverter_data["battery_discharge_current_a"] - inverter_data["battery_charging_current_a"]) * inverter_data["battery_voltage_v"]
                client.publish(f"{BASE_TOPIC}/derived/battery_power_w", battery_power_w)
                client.publish(f"{BASE_TOPIC}/derived/battery_charge_power_w", max(-battery_power_w, 0))
                client.publish(f"{BASE_TOPIC}/derived/battery_discharge_power_w", max(battery_power_w, 0))

            if BATTERY_INSTALLED:
                battery_contribution_w = battery_power_w
            else:
                battery_contribution_w = 0.0

            if "ac_output_power_w" in inverter_data and "pv1_power_w" in inverter_data and battery_contribution_w is not None and grid_power_for_decision is not None:
                total_pv_w = (inverter_data["ac_output_power_w"] - battery_contribution_w - grid_power_for_decision) / 0.85
                pv2_power_w = max(total_pv_w - inverter_data["pv1_power_w"], 0)
                client.publish(f"{BASE_TOPIC}/derived/pv2_power_w", pv2_power_w)
                client.publish(f"{BASE_TOPIC}/derived/pv_total_power_w", inverter_data["pv1_power_w"] + pv2_power_w)

        inverter_online = inverter.has_recent_data(cycle_start)
        client.publish(f"{BASE_TOPIC}/inverter/data_status", "online" if inverter_online else "offline")
        inverter_alarm.update(not inverter_online, inverter.alarm_detail(), cycle_start)

        ac_input_voltage_v = inverter_data.get("ac_input_voltage_v") if inverter_data is not None else None

        # Off-grid detection has three independent signals; a dead inverter kills two of
        # them at once. With the meter also gone nothing can bond N-PE on a grid loss,
        # so that combination is a hazard in its own right and must be visible.
        failsafe_blind = not inverter_online and not zmai_online
        client.publish(f"{BASE_TOPIC}/npe_bonding/failsafe_status", "blind" if failsafe_blind else "ok")
        failsafe_alarm.update(failsafe_blind, "inverter and ZMAi-90 both down, N-PE cannot detect grid loss", cycle_start)

        desired_bond_state = npe.decide(ac_input_voltage_v, grid_power_for_decision, zmai.relay_is_on, zmai_online, battery_power_w, cycle_start)
        npe.apply(desired_bond_state)
        client.publish(f"{BASE_TOPIC}/npe_bonding/state", "ON" if npe.is_bonded else "OFF")
        client.publish(f"{BASE_TOPIC}/npe_bonding/mode/state", npe.mode)

        elapsed = time.time() - cycle_start
        remaining = POLL_INTERVAL_SECONDS - elapsed
        if remaining > 0:
            time.sleep(remaining)


if __name__ == "__main__":
    main()
