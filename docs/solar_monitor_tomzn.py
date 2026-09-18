import json
import os
import socket
import time

import paho.mqtt.client as mqtt
import tinytuya
from gpiozero import DigitalOutputDevice  # , Button  (pulse meter, disabled, see TomznMeter below)
from mppsolar.helpers import get_device_class

# TOMZN_PULSE_PIN = 17  # GPIO pulse counting, disabled: EMI on GPIO17 made it unreliable
# IMP_PER_KWH = 1600

TOMZN_DEVICE_ID = os.environ["TOMZN_DEVICE_ID"]
TOMZN_LOCAL_KEY = os.environ["TOMZN_LOCAL_KEY"]
TOMZN_IP = os.environ["TOMZN_IP"]
TOMZN_VERSION = 3.3
TOMZN_POWER_DP = "103"
TOMZN_POWER_SCALE = 1

NPE_RELAY_PIN = 27
NPE_BOND_THRESHOLD_W = 30
NPE_BOND_STABLE_SECONDS = 3
NPE_BATTERY_STALE_SECONDS = 30
GRID_VOLTAGE_THRESHOLD_V = 50
TOMZN_STALE_SECONDS = 15

INVERTER_PORT = "/dev/ttyUSB0"
INVERTER_BAUD = 2400
INVERTER_PROTOCOL = "PI30"
INVERTER_RECONNECT_AFTER_FAILURES = 5
INVERTER_STALE_SECONDS = 30
ALARM_REPEAT_SECONDS = 300

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
AVAILABILITY_TOPIC = f"{BASE_TOPIC}/status"


# class TomznMeter:
#     """GPIO17 pulse-counting version, disabled due to EMI noise on the pulse line. Kept for reference."""
#     def __init__(self, pin, imp_per_kwh):
#         self._imp_per_kwh = imp_per_kwh
#         self._last_pulse_time = None
#         self.power_w = None
#         self._button = Button(pin, pull_up=True, bounce_time=0.05)
#         self._button.when_released = self._on_pulse
#
#     def _on_pulse(self):
#         now = time.time()
#         if self._last_pulse_time is not None:
#             interval = now - self._last_pulse_time
#             if interval > 0.1:
#                 self.power_w = (3600 * 1000) / (interval * self._imp_per_kwh)
#         self._last_pulse_time = now
#
#     def has_recent_data(self, now, stale_seconds):
#         if self._last_pulse_time is None:
#             return False
#         return (now - self._last_pulse_time) < stale_seconds


class TomznMeter:
    def __init__(self, device_id, local_key, ip, version):
        self._device = tinytuya.OutletDevice(device_id, ip, local_key)
        self._device.set_version(version)
        self._device.set_socketPersistent(False)
        self.power_w = None
        self._last_update_time = None

    def poll(self, now):
        status = self._device.status()
        if "Error" in status:
            return
        if "dps" not in status:
            return
        if TOMZN_POWER_DP not in status["dps"]:
            return
        self.power_w = status["dps"][TOMZN_POWER_DP] * TOMZN_POWER_SCALE
        self._last_update_time = now

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
        self.mode = "auto"

    def decide(self, ac_input_voltage_v, tomzn_power_w, tomzn_online, battery_power_w, now):
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
        grid_absent_by_tomzn = tomzn_power_w is not None and tomzn_power_w < self._threshold_w
        # Tomzn offline drops our main off-grid signal. Battery discharging while the
        # meter is unreachable is itself evidence of an unbonded off-grid fault.
        grid_absent_by_battery_failsafe = (
            not tomzn_online and held_battery_power_w is not None and held_battery_power_w > self._threshold_w
        )
        off_grid_signal = grid_absent_by_inverter or grid_absent_by_tomzn or grid_absent_by_battery_failsafe

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


def build_inverter_device():
    device_class = get_device_class("mppsolar")
    return device_class(name="inverter", port=INVERTER_PORT, protocol=INVERTER_PROTOCOL, baud=INVERTER_BAUD)


def read_inverter(device):
    result = device.run_command(command="QPIGS")
    if "ERROR" in result:
        return None

    data = {}
    if "AC Output Active Power" in result:
        data["ac_output_power_w"] = result["AC Output Active Power"][0]
    if "AC Input Voltage" in result:
        data["ac_input_voltage_v"] = result["AC Input Voltage"][0]
    if "PV Input Power" in result:
        data["pv1_power_w"] = result["PV Input Power"][0]
    if "PV Input Voltage" in result:
        data["pv1_input_voltage_v"] = result["PV Input Voltage"][0]
    if "Battery Capacity" in result:
        data["battery_capacity_pct"] = result["Battery Capacity"][0]
    if "Battery Voltage" in result:
        data["battery_voltage_v"] = result["Battery Voltage"][0]
    if "Battery Charging Current" in result:
        data["battery_charging_current_a"] = result["Battery Charging Current"][0]
    if "Battery Discharge Current" in result:
        data["battery_discharge_current_a"] = result["Battery Discharge Current"][0]
    return data


def on_mqtt_connect(client, userdata, flags, rc):
    """Subscriptions and retained discovery do not survive a broker restart.

    paho reconnects on its own, but silently comes back without them, which used to
    leave the HA mode select dead until the service was restarted. Re-arm both here.
    """
    client.publish(AVAILABILITY_TOPIC, "online", retain=True)
    client.subscribe(NPE_MODE_TOPIC)
    publish_discovery(client)
    print("mqtt connected, subscriptions and discovery re-armed", flush=True)


def on_mqtt_message(client, userdata, message):
    npe = userdata["npe"]
    payload = message.payload.decode().strip()
    if payload in NPE_MODES:
        npe.mode = payload


def publish_discovery(client):
    device_info = {"identifiers": [DEVICE_ID], "name": "tomzn-daxtromn", "manufacturer": "Daxtromn/Tomzn"}
    availability = [{"topic": AVAILABILITY_TOPIC, "payload_available": "online", "payload_not_available": "offline"}]

    sensors = [
        ("tomzn_power", "Tomzn Power (tinytuya)", f"{BASE_TOPIC}/tomzn/power_w", "W", "power"),
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

    tomzn_data_config = {
        "name": "Tomzn Data Status (tinytuya)",
        "unique_id": f"{DEVICE_ID}_tomzn_data",
        "state_topic": f"{BASE_TOPIC}/tomzn/data_status",
        "availability": availability,
        "device": device_info,
    }
    client.publish(f"{DISCOVERY_PREFIX}/sensor/{DEVICE_ID}/tomzn_data/config", json.dumps(tomzn_data_config), retain=True)

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
    tomzn = TomznMeter(TOMZN_DEVICE_ID, TOMZN_LOCAL_KEY, TOMZN_IP, TOMZN_VERSION)
    npe = NpeBonding(NPE_RELAY_PIN, NPE_BOND_THRESHOLD_W, NPE_BOND_STABLE_SECONDS, NPE_BATTERY_STALE_SECONDS)
    inverter = build_inverter_device()
    inverter_consecutive_failures = 0
    inverter_last_success_time = None
    inverter_alarm = Alarm("inverter-silent", ALARM_REPEAT_SECONDS)
    failsafe_alarm = Alarm("npe-failsafe-blind", ALARM_REPEAT_SECONDS)

    client = mqtt.Client(userdata={"npe": npe})
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

        tomzn.poll(cycle_start)
        if tomzn.power_w is not None:
            client.publish(f"{BASE_TOPIC}/tomzn/power_w", tomzn.power_w)
        tomzn_online = tomzn.has_recent_data(cycle_start, TOMZN_STALE_SECONDS)
        client.publish(f"{BASE_TOPIC}/tomzn/data_status", "online" if tomzn_online else "offline")
        tomzn_power_for_decision = tomzn.power_w if tomzn_online else None

        inverter_data = read_inverter(inverter)
        if not inverter_data:
            inverter_consecutive_failures += 1
        else:
            inverter_consecutive_failures = 0
            inverter_last_success_time = cycle_start
            for key, value in inverter_data.items():
                client.publish(f"{BASE_TOPIC}/inverter/{key}", value)

            if "battery_voltage_v" in inverter_data and "battery_charging_current_a" in inverter_data and "battery_discharge_current_a" in inverter_data:
                battery_power_w = (inverter_data["battery_discharge_current_a"] - inverter_data["battery_charging_current_a"]) * inverter_data["battery_voltage_v"]
                client.publish(f"{BASE_TOPIC}/derived/battery_power_w", battery_power_w)
                client.publish(f"{BASE_TOPIC}/derived/battery_charge_power_w", max(-battery_power_w, 0))
                client.publish(f"{BASE_TOPIC}/derived/battery_discharge_power_w", max(battery_power_w, 0))

            if "ac_output_power_w" in inverter_data and "pv1_power_w" in inverter_data and battery_power_w is not None and tomzn_power_for_decision is not None:
                total_pv_w = (inverter_data["ac_output_power_w"] - battery_power_w - tomzn_power_for_decision) / 0.85
                pv2_power_w = max(total_pv_w - inverter_data["pv1_power_w"], 0)
                client.publish(f"{BASE_TOPIC}/derived/pv2_power_w", pv2_power_w)
                client.publish(f"{BASE_TOPIC}/derived/pv_total_power_w", inverter_data["pv1_power_w"] + pv2_power_w)

        if inverter_consecutive_failures >= INVERTER_RECONNECT_AFTER_FAILURES:
            inverter = build_inverter_device()
            inverter_consecutive_failures = 0

        inverter_online = (
            inverter_last_success_time is not None
            and (cycle_start - inverter_last_success_time) < INVERTER_STALE_SECONDS
        )
        client.publish(f"{BASE_TOPIC}/inverter/data_status", "online" if inverter_online else "offline")
        if inverter_last_success_time is None:
            silent_detail = f"no valid read since start, port {INVERTER_PORT}"
        else:
            silent_detail = f"silent for {int(cycle_start - inverter_last_success_time)}s, port {INVERTER_PORT}"
        inverter_alarm.update(not inverter_online, silent_detail, cycle_start)

        ac_input_voltage_v = inverter_data.get("ac_input_voltage_v") if inverter_data else None

        # Off-grid detection has three independent signals; a dead inverter kills two of
        # them at once. With the Tomzn also gone nothing can bond N-PE on a grid loss,
        # so that combination is a hazard in its own right and must be visible.
        failsafe_blind = not inverter_online and not tomzn_online
        client.publish(f"{BASE_TOPIC}/npe_bonding/failsafe_status", "blind" if failsafe_blind else "ok")
        failsafe_alarm.update(failsafe_blind, "inverter and Tomzn both down, N-PE cannot detect grid loss", cycle_start)

        desired_bond_state = npe.decide(ac_input_voltage_v, tomzn_power_for_decision, tomzn_online, battery_power_w, cycle_start)
        npe.apply(desired_bond_state)
        client.publish(f"{BASE_TOPIC}/npe_bonding/state", "ON" if npe.is_bonded else "OFF")
        client.publish(f"{BASE_TOPIC}/npe_bonding/mode/state", npe.mode)

        elapsed = time.time() - cycle_start
        remaining = POLL_INTERVAL_SECONDS - elapsed
        if remaining > 0:
            time.sleep(remaining)


if __name__ == "__main__":
    main()
