"""Main service: polls the inverter, listens to the ZMAi meter, drives N-PE bonding.

Ties together ZmaiMeter, DaxtromnInverter, NpeBonding, BatteryDischargeGuard,
and Home Assistant discovery over a single MQTT client, one cycle every
POLL_INTERVAL_SECONDS.
"""

import glob
import os
import socket
import time

import paho.mqtt.client as mqtt

import settings
from alarm import Alarm
from battery import estimate_soc_from_voltage
from discharge_guard import BatteryDischargeGuard, OUTPUT_PRIORITY_MODES
from home_assistant import HomeAssistantDiscovery
from inverter import DaxtromnInverter, COMMAND_MAX_RETRIES
from npe_bonding import NpeBonding
from pi30 import is_number
from zmai_meter import ZmaiMeter, ZMAI_TOPIC_PREFIX


def notify_systemd(message):
    socket_address = os.environ.get("NOTIFY_SOCKET")
    if not socket_address:
        return
    if socket_address.startswith("@"):
        socket_address = "\0" + socket_address[1:]
    notify_socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    notify_socket.connect(socket_address)
    notify_socket.sendall(message.encode())
    notify_socket.close()


class SolarMonitor:
    """Main application: ties together meter, inverter, N-PE bonding, and MQTT."""

    def __init__(self):
        self.zmai_meter = ZmaiMeter()
        self.npe_bonding = NpeBonding(
            settings.NPE_RELAY_PIN,
            settings.NPE_BOND_THRESHOLD_W,
            settings.NPE_BOND_STABLE_SECONDS,
            settings.NPE_BATTERY_STALE_SECONDS,
        )
        self.inverter = DaxtromnInverter(settings.INVERTER_PORT, settings.INVERTER_BAUD, settings.INVERTER_STALE_SECONDS)
        self.inverter_alarm = Alarm("inverter-silent", settings.ALARM_REPEAT_SECONDS)
        self.failsafe_alarm = Alarm("npe-failsafe-blind", settings.ALARM_REPEAT_SECONDS)
        self.battery_low_alarm = Alarm("battery-low-voltage", settings.ALARM_REPEAT_SECONDS)
        self.discharge_guard = BatteryDischargeGuard(
            settings.BATTERY_DISCHARGE_STOP_SOC_PCT,
            settings.BATTERY_RESUME_SOC_PCT,
            settings.PV_RESUME_THRESHOLD_W,
        )
        self.client = mqtt.Client()
        self.discovery = HomeAssistantDiscovery(self.client)
        self._initialize_state()

    def _initialize_state(self):
        self.last_applied_priority = None
        self.output_priority_fault = False
        self.last_applied_charger_source = None
        self.pending_charger_source = None
        self.pv_efficiency = settings.PV_EFFICIENCY_DEFAULT
        self.pv2_pv1_ratio = settings.PV2_PV1_RATIO_DEFAULT
        self.battery_charge_energy_kwh = 0.0
        self.battery_discharge_energy_kwh = 0.0
        self.last_battery_cycle_time = None
        self._command_handlers = {
            settings.NPE_MODE_TOPIC: self._handle_npe_mode,
            settings.OUTPUT_PRIORITY_MODE_TOPIC: self._handle_output_priority_mode,
            settings.CHARGER_SOURCE_TOPIC: self._handle_charger_source,
            settings.PV_EFFICIENCY_TOPIC: self._handle_pv_efficiency,
            settings.PV2_RATIO_TOPIC: self._handle_pv2_ratio,
            settings.DISCHARGE_STOP_SOC_TOPIC: self._handle_discharge_stop_soc,
        }
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

    def _on_connect(self, client, userdata, flags, result_code):
        client.publish(settings.AVAILABILITY_TOPIC, "online", retain=True)
        for command_topic in self._command_handlers:
            client.subscribe(command_topic)
        client.subscribe(f"{ZMAI_TOPIC_PREFIX}/+/get")
        self.discovery.publish_all()
        print("mqtt connected, subscriptions and discovery re-armed", flush=True)

    def _on_message(self, client, userdata, message):
        payload = message.payload.decode().strip()
        handler = self._command_handlers.get(message.topic)
        if handler is not None:
            handler(payload)
        else:
            self.zmai_meter.on_message(message.topic, payload, time.time())

    def _handle_npe_mode(self, payload):
        if payload in settings.NPE_MODES:
            self.npe_bonding.mode = payload

    def _handle_output_priority_mode(self, payload):
        if payload in OUTPUT_PRIORITY_MODES:
            self.discharge_guard.mode = payload
            self.discharge_guard.clear_auto_protection()
            self.client.publish(f"{settings.BASE_TOPIC}/output_priority/mode/state", payload)
            print(f"output priority mode set to {payload}", flush=True)

    def _handle_charger_source(self, payload):
        if payload in settings.CHARGER_SOURCE_OPTIONS:
            self.pending_charger_source = payload
            self.client.publish(f"{settings.BASE_TOPIC}/charger_source/state", payload)
            print(f"charger source requested: {payload}", flush=True)

    def _handle_pv_efficiency(self, payload):
        if not is_number(payload):
            return
        value = float(payload)
        if 0.5 <= value <= 1.0:
            self.pv_efficiency = value
            print(f"pv efficiency set to {value}", flush=True)

    def _handle_pv2_ratio(self, payload):
        if not is_number(payload):
            return
        value = float(payload)
        if 0.1 <= value <= 1.0:
            self.pv2_pv1_ratio = value
            print(f"pv2/pv1 ratio set to {value}", flush=True)

    def _handle_discharge_stop_soc(self, payload):
        if not is_number(payload):
            return
        value = int(float(payload))
        if 10 <= value <= 50:
            self.discharge_guard.stop_soc_pct = value
            print(f"discharge stop SOC set to {value}%", flush=True)

    def _connect_mqtt(self):
        self.client.username_pw_set(settings.MQTT_USER, settings.MQTT_PASSWORD)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.will_set(settings.AVAILABILITY_TOPIC, "offline", retain=True)
        self.client.connect(settings.MQTT_HOST, settings.MQTT_PORT)
        self.client.loop_start()

    def _load_initial_inverter_state(self):
        initial_priority = self.inverter.query_output_source_priority()
        if initial_priority is not None:
            self.last_applied_priority = initial_priority
            print(f"initial output priority: {initial_priority}", flush=True)

        initial_charger_source = self.inverter.query_charger_source_priority()
        if initial_charger_source is not None:
            self.last_applied_charger_source = initial_charger_source
            self.pending_charger_source = initial_charger_source
            print(f"initial charger source: {initial_charger_source}", flush=True)

    def run(self):
        self._connect_mqtt()
        self._load_initial_inverter_state()
        print("solar_monitor started", flush=True)
        notify_systemd("READY=1")
        while True:
            cycle_start = time.time()
            notify_systemd("WATCHDOG=1")
            self._run_cycle(cycle_start)
            if self._source_files_changed():
                print("source files changed, restarting", flush=True)
                return
            self._sleep_until_next_cycle(cycle_start)

    def _run_cycle(self, now):
        zmai_online, grid_power_for_npe, grid_power_for_pv2 = self._publish_grid_readings(now)
        inverter_data = self.inverter.poll(now)
        battery_power_w = None
        pv_total_power_w = 0
        if inverter_data is not None:
            self._publish_inverter_fields(inverter_data)
            battery_power_w = self._compute_battery_power(inverter_data, now)
            battery_contribution_w = battery_power_w if self.inverter.is_battery_present(inverter_data) else 0.0
            pv_total_power_w = self._estimate_pv_power(inverter_data, battery_contribution_w, grid_power_for_pv2)
        self._publish_link_status(zmai_online, now)
        battery_present, estimated_soc, battery_is_low = self._assess_battery(inverter_data, now)
        self._apply_output_priority(estimated_soc, battery_present, pv_total_power_w)
        self._apply_charger_source()
        ac_input_voltage_v = inverter_data.get("ac_input_voltage_v") if inverter_data is not None else None
        self._apply_npe_bonding(ac_input_voltage_v, grid_power_for_npe, zmai_online, battery_power_w, battery_is_low, now)

    def _publish_grid_readings(self, now):
        if self.zmai_meter.power_w is not None:
            self.client.publish(f"{settings.BASE_TOPIC}/zmai/power_w", self.zmai_meter.power_w)
        if self.zmai_meter.voltage_v is not None:
            self.client.publish(f"{settings.BASE_TOPIC}/zmai/voltage_v", self.zmai_meter.voltage_v)
        if self.zmai_meter.current_a is not None:
            self.client.publish(f"{settings.BASE_TOPIC}/zmai/current_a", self.zmai_meter.current_a)
        zmai_online = self.zmai_meter.has_recent_data(now, settings.ZMAI_STALE_SECONDS)
        self.client.publish(f"{settings.BASE_TOPIC}/zmai/data_status", "online" if zmai_online else "offline")
        zmai_has_reading = zmai_online and self.zmai_meter.power_w is not None
        grid_power_for_npe = self.zmai_meter.power_w if zmai_has_reading else None
        power_above_noise = zmai_has_reading and abs(self.zmai_meter.power_w) >= settings.ZMAI_NOISE_THRESHOLD_W
        grid_power_for_pv2 = self.zmai_meter.power_w if power_above_noise else None
        return zmai_online, grid_power_for_npe, grid_power_for_pv2

    def _publish_inverter_fields(self, inverter_data):
        for field_name, field_value in inverter_data.items():
            self.client.publish(f"{settings.BASE_TOPIC}/inverter/{field_name}", field_value)

    def _compute_battery_power(self, inverter_data, now):
        required_fields = ("battery_voltage_v", "battery_charging_current_a", "battery_discharge_current_a")
        for field_name in required_fields:
            if field_name not in inverter_data:
                return None
        net_current_a = inverter_data["battery_discharge_current_a"] - inverter_data["battery_charging_current_a"]
        battery_power_w = net_current_a * inverter_data["battery_voltage_v"]
        self.client.publish(f"{settings.BASE_TOPIC}/derived/battery_power_w", battery_power_w)
        self.client.publish(f"{settings.BASE_TOPIC}/derived/battery_charge_power_w", max(-battery_power_w, 0))
        self.client.publish(f"{settings.BASE_TOPIC}/derived/battery_discharge_power_w", -max(battery_power_w, 0))
        self._accumulate_battery_energy(battery_power_w, now)
        return battery_power_w

    def _accumulate_battery_energy(self, battery_power_w, now):
        if self.last_battery_cycle_time is not None:
            elapsed_hours = (now - self.last_battery_cycle_time) / 3600
            if battery_power_w < 0:
                self.battery_charge_energy_kwh += abs(battery_power_w) * elapsed_hours / 1000
            elif battery_power_w > 0:
                self.battery_discharge_energy_kwh += battery_power_w * elapsed_hours / 1000
            self.client.publish(f"{settings.BASE_TOPIC}/derived/battery_charge_energy_kwh", round(self.battery_charge_energy_kwh, 3))
            self.client.publish(f"{settings.BASE_TOPIC}/derived/battery_discharge_energy_kwh", round(self.battery_discharge_energy_kwh, 3))
        self.last_battery_cycle_time = now

    def _estimate_total_pv_watts(self, inverter_data, battery_contribution_w, grid_power_w):
        ac_output_w = inverter_data["ac_output_power_w"]
        pv1_power_w = inverter_data["pv1_power_w"]
        total_pv_w = None
        if grid_power_w is not None:
            device_status = inverter_data.get("device_status", "00000000")
            ac_charging_from_grid = len(device_status) > 7 and device_status[7] == "1"
            total_pv_as_import = (ac_output_w - grid_power_w) / self.pv_efficiency - battery_contribution_w
            if ac_charging_from_grid or total_pv_as_import >= pv1_power_w:
                total_pv_w = total_pv_as_import
        if total_pv_w is None:
            total_pv_w = ac_output_w / self.pv_efficiency - battery_contribution_w
        pv2_from_balance_w = total_pv_w - pv1_power_w
        if pv2_from_balance_w < pv1_power_w * 0.05 and pv1_power_w > settings.PV2_RATIO_MIN_PV1_W:
            total_pv_w = pv1_power_w * (1 + self.pv2_pv1_ratio)
        return total_pv_w

    def _estimate_pv_power(self, inverter_data, battery_contribution_w, grid_power_w):
        if "ac_output_power_w" not in inverter_data or "pv1_power_w" not in inverter_data:
            return 0
        if battery_contribution_w is None:
            return 0
        total_pv_w = self._estimate_total_pv_watts(inverter_data, battery_contribution_w, grid_power_w)
        pv1_power_w = inverter_data["pv1_power_w"]
        pv2_power_w = max(total_pv_w - pv1_power_w, 0)
        pv_total_power_w = pv1_power_w + pv2_power_w
        self.client.publish(f"{settings.BASE_TOPIC}/derived/pv2_power_w", pv2_power_w)
        self.client.publish(f"{settings.BASE_TOPIC}/derived/pv_total_power_w", pv_total_power_w)
        self.client.publish(f"{settings.BASE_TOPIC}/pv/efficiency/state", self.pv_efficiency)
        return pv_total_power_w

    def _publish_link_status(self, zmai_online, now):
        inverter_online = self.inverter.has_recent_data(now)
        self.client.publish(f"{settings.BASE_TOPIC}/inverter/data_status", "online" if inverter_online else "offline")
        self.inverter_alarm.update(not inverter_online, self.inverter.alarm_detail(), now)
        failsafe_blind = not inverter_online and not zmai_online
        self.client.publish(f"{settings.BASE_TOPIC}/npe_bonding/failsafe_status", "blind" if failsafe_blind else "ok")
        self.failsafe_alarm.update(failsafe_blind, "inverter and ZMAi-90 both down, N-PE cannot detect grid loss", now)

    def _assess_battery(self, inverter_data, now):
        battery_present = self.inverter.is_battery_present(inverter_data)
        self.client.publish(f"{settings.BASE_TOPIC}/derived/battery_present", "ON" if battery_present else "OFF")
        battery_voltage = inverter_data.get("battery_voltage_v", 0) if inverter_data is not None else 0
        estimated_soc = 0
        if battery_present and battery_voltage > 0:
            estimated_soc = estimate_soc_from_voltage(battery_voltage)
            self.client.publish(f"{settings.BASE_TOPIC}/derived/battery_soc_estimated_pct", estimated_soc)
        battery_is_low = battery_present and battery_voltage < settings.BATTERY_LOW_VOLTAGE_V
        self.battery_low_alarm.update(battery_is_low, f"battery voltage {battery_voltage}V (threshold {settings.BATTERY_LOW_VOLTAGE_V}V)", now)
        self.client.publish(f"{settings.BASE_TOPIC}/battery/low_voltage_status", "low" if battery_is_low else "ok")
        self.client.publish(f"{settings.BASE_TOPIC}/battery/discharge_stop_soc/state", self.discharge_guard.stop_soc_pct)
        return battery_present, estimated_soc, battery_is_low

    def _apply_output_priority(self, estimated_soc, battery_present, pv_total_power_w):
        auto_mode = self.discharge_guard.update_auto_protection(estimated_soc, battery_present)
        if auto_mode is not None:
            self.client.publish(f"{settings.BASE_TOPIC}/output_priority/mode/state", auto_mode)
            print(f"auto-protection: mode -> {auto_mode} (SOC {estimated_soc}%)", flush=True)
        desired_priority = self.discharge_guard.decide(estimated_soc, battery_present, pv_total_power_w)
        if desired_priority != self.last_applied_priority:
            command = "POP02" if desired_priority == "SBU" else "POP01"
            if self.inverter.set_output_priority(command):
                self.last_applied_priority = desired_priority
                self.output_priority_fault = False
                print(f"output priority: {desired_priority} (SOC {estimated_soc}%)", flush=True)
            else:
                self.output_priority_fault = True
                print(f"ALARM output priority command failed after {COMMAND_MAX_RETRIES} retries: "
                      f"wanted {desired_priority}", flush=True)
        self.client.publish(f"{settings.BASE_TOPIC}/output_priority/state", self.last_applied_priority or "unknown")
        self.client.publish(f"{settings.BASE_TOPIC}/output_priority/mode/state", self.discharge_guard.mode)
        self.client.publish(f"{settings.BASE_TOPIC}/output_priority/discharge_blocked", "ON" if self.discharge_guard.is_discharge_blocked else "OFF")
        self.client.publish(f"{settings.BASE_TOPIC}/output_priority/command_fault", "ON" if self.output_priority_fault else "OFF")

    def _apply_charger_source(self):
        if self.pending_charger_source is not None and self.pending_charger_source != self.last_applied_charger_source:
            pcp_command = settings.CHARGER_SOURCE_TO_PCP[self.pending_charger_source]
            if self.inverter.set_charger_source(pcp_command):
                self.last_applied_charger_source = self.pending_charger_source
                print(f"charger source: {self.last_applied_charger_source}", flush=True)
        self.client.publish(f"{settings.BASE_TOPIC}/charger_source/state", self.last_applied_charger_source or "unknown")

    def _apply_npe_bonding(self, ac_input_voltage_v, grid_power_w, zmai_online, battery_power_w, battery_is_low, now):
        desired_bond_state = self.npe_bonding.decide(ac_input_voltage_v, grid_power_w, zmai_online, battery_power_w, now)
        if battery_is_low:
            desired_bond_state = False
        self.npe_bonding.apply(desired_bond_state)
        self.client.publish(f"{settings.BASE_TOPIC}/npe_bonding/state", "ON" if self.npe_bonding.is_bonded else "OFF")
        for reason_key, reason_value in self.npe_bonding.last_reasons.items():
            self.client.publish(f"{settings.BASE_TOPIC}/npe_bonding/debug/{reason_key}", reason_value)
        self.client.publish(f"{settings.BASE_TOPIC}/npe_bonding/mode/state", self.npe_bonding.mode)

    @staticmethod
    def _sleep_until_next_cycle(cycle_start):
        elapsed = time.time() - cycle_start
        remaining = settings.POLL_INTERVAL_SECONDS - elapsed
        if remaining > 0:
            time.sleep(remaining)


def main():
    monitor = SolarMonitor()
    monitor.run()


if __name__ == "__main__":
    main()
