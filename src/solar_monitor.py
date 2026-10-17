"""Main service: polls the inverter, listens to the ZMAi meter, drives N-PE bonding.

Ties together ZmaiMeter, DaxtromnInverter, NpeBonding, BatteryMode,
and Home Assistant discovery over a single MQTT client, one cycle every
POLL_INTERVAL_SECONDS.
"""

import glob
import json
import os
import socket
import sys
import time

import paho.mqtt.client as mqtt

import settings
from alarm import Alarm
from batteries.battery import estimate_soc_from_voltage
from batteries.can_battery import CanBattery
from grid_limiter import GridPowerLimiter
from inverter.battery_mode import BatteryMode
from inverter.inverter import DaxtromnInverter, BATTERY_CURRENT_NOISE_A, COMMAND_MAX_RETRIES
from inverter.pi30 import is_number
from mqtt.home_assistant import HomeAssistantDiscovery
from mqtt.npe_bonding import NpeBonding
from mqtt.zmai_meter import ZmaiMeter, ZMAI_TOPIC_PREFIX
from pi_throttle import read_throttled_hex, decode_active_flags

BMS_OFFLINE_NO_SOLAR_TIMEOUT_SECONDS = 3 * 3600
MODE_VERIFY_INTERVAL_SECONDS = 600


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


SOC_SETTING_KEYS = ("low_battery_protection_soc_pct", "grid_stop_charging_soc_pct", "grid_quick_charge_soc_pct")
VOLTAGE_SETTING_KEYS = ("back_to_grid_v", "back_to_battery_v")
LIMITER_SETTING_KEYS = ("max_grid_power_w", "mcb_rating_a")


class SolarMonitor:
    """Main application: ties together meter, inverter, N-PE bonding, and MQTT."""

    def __init__(self):
        self.zmai_meter = ZmaiMeter()
        self.npe_bonding = NpeBonding(
            settings.NPE_RELAY_PIN,
            settings.NPE_BOND_THRESHOLD_W,
            settings.NPE_BOND_STABLE_SECONDS,
        )

        self.inverter = DaxtromnInverter(settings.INVERTER_PORT, settings.INVERTER_BAUD, settings.INVERTER_STALE_SECONDS)
        self.can_battery = CanBattery(settings.CAN_INTERFACE, settings.CAN_BATTERY_STALE_SECONDS)
        self.grid_limiter = GridPowerLimiter(
            settings.MAX_GRID_POWER_W, settings.SOFT_LIMIT_HYSTERESIS_W,
            settings.MCB_RATING_A, settings.GRID_NOMINAL_VOLTAGE_V,
            settings.MCB_LOCKOUT_SECONDS,
        )
        self.inverter_alarm = Alarm("inverter-silent", settings.ALARM_REPEAT_SECONDS)
        self.failsafe_alarm = Alarm("npe-failsafe-blind", settings.ALARM_REPEAT_SECONDS)

        self.battery_low_alarm = Alarm("battery-low-voltage", settings.ALARM_REPEAT_SECONDS)
        self.battery_mode = BatteryMode(
            settings.LOW_BATTERY_PROTECTION_SOC_PCT,
            settings.GRID_STOP_CHARGING_SOC_PCT,
            settings.GRID_QUICK_CHARGE_SOC_PCT,
        )
        self.back_to_grid_v = settings.BACK_TO_GRID_V
        self.back_to_battery_v = settings.BACK_TO_BATTERY_V
        self._load_soc_settings()
        self.undervoltage_alarm = Alarm("pi-undervoltage", settings.ALARM_REPEAT_SECONDS)

        self.client = mqtt.Client()
        self.discovery = HomeAssistantDiscovery(self.client)
        self._initialize_state()

        self._applied_ac_charge_current_a = None

    def _initialize_state(self):
        self._bms_was_online = None
        self._bms_offline_no_solar_since = None
        self._bms_offline_fallback_active = False
        self._last_mode_verify_time = None
        self.last_applied_priority = None
        self.output_priority_fault = False
        self.last_applied_charger_source = None
        self.actual_voltage_thresholds = None

        self.pv_efficiency = settings.PV_EFFICIENCY_DEFAULT
        self.pv2_pv1_ratio = settings.PV2_PV1_RATIO_DEFAULT
        self.battery_charge_energy_kwh = 0.0
        self.battery_discharge_energy_kwh = 0.0
        self.solar_production_energy_kwh = 0.0
        self.grid_import_energy_kwh = 0.0
        self.last_battery_cycle_time = None
        self.last_energy_cycle_time = None

        self._command_handlers = {
            settings.NPE_MODE_TOPIC: self._handle_npe_mode,
            settings.BATTERY_MODE_TOPIC: self._handle_battery_mode,
            settings.PV_EFFICIENCY_TOPIC: self._handle_pv_efficiency,
            settings.PV2_RATIO_TOPIC: self._handle_pv2_ratio,
            settings.LOW_BATTERY_PROTECTION_SOC_TOPIC: self._handle_low_battery_protection_soc,
            settings.GRID_STOP_CHARGING_SOC_TOPIC: self._handle_grid_stop_charging_soc,
            settings.GRID_QUICK_CHARGE_SOC_TOPIC: self._handle_grid_quick_charge_soc,
            settings.BACK_TO_GRID_V_TOPIC: self._handle_back_to_grid_v,
            settings.BACK_TO_BATTERY_V_TOPIC: self._handle_back_to_battery_v,
            settings.MAX_GRID_POWER_TOPIC: self._handle_max_grid_power,
            settings.MCB_RATING_TOPIC: self._handle_mcb_rating,
        }
        self._source_mtimes = self._snapshot_source_mtimes()

    def _snapshot_source_mtimes(self):
        source_directory = os.path.dirname(os.path.abspath(__file__))
        source_files = glob.glob(os.path.join(source_directory, "**", "*.py"), recursive=True)
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

    def _handle_battery_mode(self, payload):
        if not self.battery_mode.select(payload):
            return
        self.client.publish(f"{settings.BASE_TOPIC}/battery_mode/state", self.battery_mode.selected_mode)
        self.client.publish(f"{settings.BASE_TOPIC}/battery_mode/display", self.battery_mode.status_description)
        print(f"battery mode set to {self.battery_mode.status_description}", flush=True)

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

    @staticmethod
    def _parse_soc_in_range(payload, soc_range):
        if not is_number(payload):
            return None
        value = int(float(payload))
        minimum, maximum = soc_range

        if minimum <= value <= maximum:
            return value
        return None

    def _handle_low_battery_protection_soc(self, payload):
        value = self._parse_soc_in_range(payload, settings.LOW_BATTERY_PROTECTION_SOC_RANGE)
        highest_allowed = min(
            self.battery_mode.grid_stop_charging_soc_pct - settings.GRID_STOP_CHARGING_MINIMUM_GAP_PCT,
            self.battery_mode.grid_quick_charge_soc_pct - 1,
        )

        if value is None:
            return
        if value > highest_allowed:
            print(f"rejected low battery protection {value}%: maximum is {highest_allowed}%", flush=True)
            return
        self.battery_mode.low_battery_protection_soc_pct = value
        print(f"low battery protection set to {value}%", flush=True)
        self._save_soc_settings()

    def _load_soc_settings(self):
        try:
            with open(settings.SOC_SETTINGS_FILE) as f:
                saved = json.load(f)
        except (OSError, ValueError):
            return
        for key in SOC_SETTING_KEYS:
            if isinstance(saved.get(key), int):
                setattr(self.battery_mode, key, saved[key])
        for key in VOLTAGE_SETTING_KEYS:
            if isinstance(saved.get(key), (int, float)):
                setattr(self, key, float(saved[key]))
        for key in LIMITER_SETTING_KEYS:
            if isinstance(saved.get(key), (int, float)):
                setattr(self.grid_limiter, key, int(saved[key]))
        print(f"loaded SOC settings: {saved}", flush=True)

    def _save_soc_settings(self):
        values = {key: getattr(self.battery_mode, key) for key in SOC_SETTING_KEYS}
        values.update({key: getattr(self, key) for key in VOLTAGE_SETTING_KEYS})
        values.update({key: getattr(self.grid_limiter, key) for key in LIMITER_SETTING_KEYS})
        try:
            with open(settings.SOC_SETTINGS_FILE, "w") as f:
                json.dump(values, f)
        except OSError as error:
            print(f"failed to save SOC settings: {error}", flush=True)

    def _handle_grid_stop_charging_soc(self, payload):
        value = self._parse_soc_in_range(payload, settings.GRID_STOP_CHARGING_SOC_RANGE)
        lowest_allowed = self.battery_mode.low_battery_protection_soc_pct + settings.GRID_STOP_CHARGING_MINIMUM_GAP_PCT

        if value is None:
            return
        if value < lowest_allowed:
            print(f"rejected grid stop charging {value}%: minimum is {lowest_allowed}% "
                  f"(low battery protection + {settings.GRID_STOP_CHARGING_MINIMUM_GAP_PCT}%)", flush=True)
            return
        self.battery_mode.grid_stop_charging_soc_pct = value
        print(f"grid stop charging set to {value}%", flush=True)
        self._save_soc_settings()

    def _handle_grid_quick_charge_soc(self, payload):
        value = self._parse_soc_in_range(payload, settings.GRID_QUICK_CHARGE_SOC_RANGE)

        if value is None:
            return
        if value <= self.battery_mode.low_battery_protection_soc_pct:
            print(f"rejected grid quick charge {value}%: must be above low battery protection "
                  f"{self.battery_mode.low_battery_protection_soc_pct}%", flush=True)
            return
        self.battery_mode.grid_quick_charge_soc_pct = value
        print(f"grid quick charge set to {value}%", flush=True)
        self._save_soc_settings()

    @staticmethod
    def _parse_volts_in_range(payload, volts_range):
        if not is_number(payload):
            return None
        value = round(float(payload) * 2) / 2
        minimum, maximum = volts_range
        if minimum <= value <= maximum:
            return value
        return None

    def _handle_back_to_grid_v(self, payload):
        value = self._parse_volts_in_range(payload, settings.BACK_TO_GRID_V_RANGE)
        if value is None:
            return
        highest_allowed = self.back_to_battery_v - settings.BACK_TO_BATTERY_MINIMUM_GAP_V
        if value > highest_allowed:
            print(f"rejected back to grid {value}V: maximum is {highest_allowed}V", flush=True)
            return
        self.back_to_grid_v = value
        print(f"back to grid voltage set to {value}V", flush=True)
        self._save_soc_settings()

    def _handle_back_to_battery_v(self, payload):
        value = self._parse_volts_in_range(payload, settings.BACK_TO_BATTERY_V_RANGE)
        if value is None:
            return
        lowest_allowed = self.back_to_grid_v + settings.BACK_TO_BATTERY_MINIMUM_GAP_V
        if value < lowest_allowed:
            print(f"rejected back to battery {value}V: minimum is {lowest_allowed}V", flush=True)
            return
        self.back_to_battery_v = value
        print(f"back to battery voltage set to {value}V", flush=True)
        self._save_soc_settings()

    def _handle_max_grid_power(self, payload):
        if not is_number(payload):
            return
        value = int(float(payload))
        minimum, maximum = settings.MAX_GRID_POWER_RANGE
        if minimum <= value <= maximum:
            self.grid_limiter.max_grid_power_w = value
            print(f"max grid power set to {value}W", flush=True)
            self._save_soc_settings()

    def _handle_mcb_rating(self, payload):
        if not is_number(payload):
            return
        value = int(float(payload))
        minimum, maximum = settings.MCB_RATING_RANGE
        if minimum <= value <= maximum:
            self.grid_limiter.mcb_rating_a = value
            self._applied_ac_charge_current_a = None
            print(f"MCB rating set to {value}A", flush=True)
            self._save_soc_settings()

    def _desired_voltage_thresholds(self):
        # SBU only leaves the battery below program 12, so low battery protection raises 12 to its maximum
        # and 13 above the BMS charge limit: the load stays on grid until protection ends.
        if self.battery_mode.holds_load_on_grid:
            return settings.BACK_TO_GRID_V_RANGE[1], settings.BACK_TO_BATTERY_V_RANGE[1]
        return self.back_to_grid_v, self.back_to_battery_v

    def _apply_voltage_thresholds(self):
        desired = self._desired_voltage_thresholds()
        if self.actual_voltage_thresholds == desired:
            return
        actual = self.actual_voltage_thresholds or (None, None)
        for threshold_index, command_prefix, program in ((0, "PBCV", 12), (1, "PBDV", 13)):
            if actual[threshold_index] == desired[threshold_index]:
                continue
            if not self.inverter.set_battery_voltage_threshold(command_prefix, threshold_index, desired[threshold_index]):
                return
            print(f"program {program}: {desired[threshold_index]}V", flush=True)
        self.actual_voltage_thresholds = desired

    def _apply_max_ac_charge_current(self):
        desired_amps = self.grid_limiter.mcb_rating_a
        if self._applied_ac_charge_current_a == desired_amps:
            return
        if self.inverter.set_max_ac_charge_current(desired_amps):
            self._applied_ac_charge_current_a = desired_amps
            print(f"max AC charge current: {desired_amps}A", flush=True)

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

        self.actual_voltage_thresholds = self.inverter.query_battery_voltage_thresholds()
        print(f"initial program 12/13: {self.actual_voltage_thresholds}", flush=True)

        initial_charger_source = self.inverter.query_charger_source_priority()

        if initial_charger_source is not None:
            self.last_applied_charger_source = initial_charger_source
            print(f"initial charger source: {initial_charger_source}", flush=True)

        initial_ac_charge_current = self.inverter.query_max_ac_charge_current()
        if initial_ac_charge_current is not None:
            self._applied_ac_charge_current_a = initial_ac_charge_current
            print(f"initial max AC charge current: {initial_ac_charge_current}A", flush=True)

    def run(self):
        self._connect_mqtt()
        self._load_initial_inverter_state()
        self.can_battery.start()
        print("solar_monitor started", flush=True)
        notify_systemd("READY=1")

        while True:
            cycle_start = time.time()
            notify_systemd("WATCHDOG=1")
            self._run_cycle(cycle_start)

            if self._source_files_changed():
                print("source files changed, restarting", flush=True)
                os.execv(sys.executable, [sys.executable] + sys.argv)
            self._sleep_until_next_cycle(cycle_start)

    def _run_cycle(self, now):
        zmai_online, grid_power_for_npe, grid_power_for_pv2 = self._publish_grid_readings(now)
        grid_power_for_limiter = self.zmai_meter.power_w if zmai_online and self.zmai_meter.power_w is not None else None
        grid_voltage_for_limiter = self.zmai_meter.voltage_v if zmai_online else None
        self.grid_limiter.update(grid_power_for_limiter, grid_voltage_for_limiter, now)
        inverter_data = self.inverter.poll(now)
        battery_power_w = None
        pv_total_power_w = 0

        if inverter_data is not None:
            self._publish_inverter_fields(inverter_data)
            battery_power_w = self._compute_battery_power(inverter_data, now)
            battery_contribution_w = battery_power_w if self.inverter.is_battery_present(inverter_data) else 0.0
            pv_total_power_w = self._estimate_pv_power(inverter_data, battery_contribution_w, grid_power_for_pv2)

        grid_power_for_energy = self.zmai_meter.power_w if zmai_online and self.zmai_meter.power_w is not None else None
        self._accumulate_solar_grid_energy(pv_total_power_w, grid_power_for_energy, now)
        self._publish_link_status(zmai_online, now)
        self._publish_can_battery(now)
        can_data = self.can_battery.get_data() if self.can_battery.has_recent_data(now) else None
        battery_present, estimated_soc, battery_is_low, bms_available = self._assess_battery(inverter_data, can_data, now)
        self._check_bms_offline_fallback(inverter_data, bms_available, battery_present, now)

        if inverter_data is not None or bms_available:
            self._apply_battery_mode(estimated_soc, battery_present, bms_available)
        if inverter_data is not None:
            self._apply_voltage_thresholds()
            self._apply_max_ac_charge_current()
        self._verify_inverter_mode(estimated_soc, battery_present, now)
        ac_input_voltage_v = inverter_data.get("ac_input_voltage_v") if inverter_data is not None else None
        inverter_online = self.inverter.has_recent_data(now)
        self._apply_npe_bonding(ac_input_voltage_v, grid_power_for_npe, zmai_online, inverter_online, now)
        self._check_pi_throttle(now)

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
        self.client.publish(f"{settings.BASE_TOPIC}/derived/battery_discharge_power_w", max(battery_power_w, 0))
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

    def _accumulate_solar_grid_energy(self, pv_total_power_w, grid_power_w, now):
        if self.last_energy_cycle_time is not None:
            elapsed_hours = (now - self.last_energy_cycle_time) / 3600

            if pv_total_power_w > 0:
                self.solar_production_energy_kwh += pv_total_power_w * elapsed_hours / 1000
            if grid_power_w is not None and grid_power_w > 0:
                self.grid_import_energy_kwh += grid_power_w * elapsed_hours / 1000

            self.client.publish(f"{settings.BASE_TOPIC}/derived/solar_production_energy_kwh",
                                round(self.solar_production_energy_kwh, 3))
            self.client.publish(f"{settings.BASE_TOPIC}/derived/grid_import_energy_kwh",
                                round(self.grid_import_energy_kwh, 3))
        self.last_energy_cycle_time = now

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

    def _publish_can_battery(self, now):
        can_online = self.can_battery.has_recent_data(now)
        self.client.publish(f"{settings.BASE_TOPIC}/can_battery/data_status", "online" if can_online else "offline")
        can_data = self.can_battery.get_data()

        if can_data is None:
            return
        for field_name, field_value in can_data.items():
            self.client.publish(f"{settings.BASE_TOPIC}/can_battery/{field_name}", field_value)

    def _assess_battery(self, inverter_data, can_data, now):
        battery_present = self.inverter.is_battery_present(inverter_data)
        self.client.publish(f"{settings.BASE_TOPIC}/derived/battery_present", "ON" if battery_present else "OFF")
        bms_available = can_data is not None and "bms_soc_pct" in can_data
        self._publish_bms_status_change(bms_available)
        inverter_voltage = inverter_data.get("battery_voltage_v", 0) if inverter_data is not None else 0
        inverter_soc = 0

        if battery_present and inverter_voltage > 0:
            inverter_soc = estimate_soc_from_voltage(inverter_voltage)
        if bms_available:
            estimated_soc = can_data["bms_soc_pct"]
        else:
            estimated_soc = inverter_soc
        if battery_present:
            self.client.publish(f"{settings.BASE_TOPIC}/derived/battery_soc_estimated_pct", estimated_soc)
        if can_data is not None and "bms_voltage_v" in can_data:
            voltage_for_low_check = can_data["bms_voltage_v"]
        else:
            voltage_for_low_check = inverter_voltage

        battery_is_low = battery_present and voltage_for_low_check < settings.BATTERY_LOW_VOLTAGE_V
        self.battery_low_alarm.update(battery_is_low, f"battery voltage {voltage_for_low_check}V (threshold {settings.BATTERY_LOW_VOLTAGE_V}V)", now)
        self.client.publish(f"{settings.BASE_TOPIC}/battery/low_voltage_status", "low" if battery_is_low else "ok")

        return battery_present, estimated_soc, battery_is_low, bms_available

    def _publish_bms_status_change(self, bms_available):
        bms_status = "online" if bms_available else "offline"
        self.client.publish(f"{settings.BASE_TOPIC}/can_battery/bms_soc_status", bms_status)

        if self._bms_was_online is not None and bms_available != self._bms_was_online:
            if bms_available:
                print("BMS SOC data restored, trusting BMS for discharge protection", flush=True)
            else:
                print("WARNING: BMS SOC data lost, falling back to inverter capacity with safety margin", flush=True)
        self._bms_was_online = bms_available

    def _check_bms_offline_fallback(self, inverter_data, bms_available, battery_present, now):
        """After 3h with BMS offline and no solar charging, force SUB and grid charging."""
        if bms_available or not battery_present or inverter_data is None:
            if self._bms_offline_fallback_active:
                self._bms_offline_fallback_active = False
                print("BMS offline fallback cleared", flush=True)
            self._bms_offline_no_solar_since = None
            return

        charging_current = inverter_data.get("battery_charging_current_a", 0)
        if charging_current > BATTERY_CURRENT_NOISE_A:
            self._bms_offline_no_solar_since = None
            return

        if self._bms_offline_no_solar_since is None:
            self._bms_offline_no_solar_since = now

        elapsed = now - self._bms_offline_no_solar_since
        if elapsed >= BMS_OFFLINE_NO_SOLAR_TIMEOUT_SECONDS and not self._bms_offline_fallback_active:
            self._bms_offline_fallback_active = True
            self.battery_mode.accept_inverter_protection()
            print(f"WARNING: BMS offline and no solar charging for {int(elapsed / 3600)}h, "
                  "forcing solar_and_utility charging", flush=True)

    def _verify_inverter_mode(self, estimated_soc, battery_present, now):
        if self._last_mode_verify_time is not None:
            if (now - self._last_mode_verify_time) < MODE_VERIFY_INTERVAL_SECONDS:
                return
        self._last_mode_verify_time = now

        actual_priority = self.inverter.query_output_source_priority()
        if actual_priority is not None:
            self.client.publish(f"{settings.BASE_TOPIC}/inverter/actual_output_priority", actual_priority, retain=True)
            if actual_priority != self.last_applied_priority:
                print(f"mode verify: inverter output priority is {actual_priority}", flush=True)
            self.last_applied_priority = actual_priority

        actual_thresholds = self.inverter.query_battery_voltage_thresholds()
        if actual_thresholds is not None:
            if actual_thresholds != self.actual_voltage_thresholds:
                print(f"mode verify: inverter program 12/13 is {actual_thresholds}", flush=True)
            self.actual_voltage_thresholds = actual_thresholds

        actual_charger = self.inverter.query_charger_source_priority()
        if actual_charger is not None:
            self.client.publish(f"{settings.BASE_TOPIC}/inverter/actual_charger_source", actual_charger, retain=True)
            if actual_charger != self.last_applied_charger_source:
                # Changed on the LCD or a command did not stick: next cycle re-sends the desired source.
                print(f"mode verify: inverter charger source is {actual_charger}, "
                      f"expected {self.last_applied_charger_source}", flush=True)
            self.last_applied_charger_source = actual_charger

    def _apply_battery_mode(self, estimated_soc, battery_present, bms_available):
        inverter_capacity_pct = None

        if self.inverter.last_data is not None:
            inverter_capacity_pct = self.inverter.last_data.get("battery_capacity_pct")

        mode_change = self.battery_mode.update(
            estimated_soc, battery_present, inverter_capacity_pct, bms_available,
        )

        if mode_change is not None:
            print(f"battery mode: {mode_change}", flush=True)

        self._apply_charger_source()
        self._publish_battery_mode_state()

    def _apply_charger_source(self):
        effective_charger = self.battery_mode.desired_charger_source

        if self._bms_offline_fallback_active:
            effective_charger = "solar_and_utility"
        grid_limited = self.grid_limiter.is_throttled or self.grid_limiter.is_locked_out
        if grid_limited and effective_charger in ("utility_first", "solar_and_utility"):
            effective_charger = "solar_only"
        if effective_charger == self.last_applied_charger_source:
            return
        pcp_command = settings.CHARGER_SOURCE_TO_PCP[effective_charger]

        if self.inverter.set_charger_source(pcp_command):
            self.last_applied_charger_source = effective_charger
            print(f"charger source: {effective_charger}", flush=True)
            return
        print(f"charger source command failed: wanted {effective_charger}", flush=True)

    def _publish_battery_mode_state(self):
        self.client.publish(f"{settings.BASE_TOPIC}/battery_mode/state", self.battery_mode.selected_mode)
        self.client.publish(f"{settings.BASE_TOPIC}/battery_mode/display", self.battery_mode.status_description)
        self.client.publish(f"{settings.BASE_TOPIC}/battery_mode/low_battery_active",
                            "ON" if self.battery_mode.is_low_battery_active else "OFF")

        self.client.publish(f"{settings.BASE_TOPIC}/output_priority/command_fault",
                            "ON" if self.output_priority_fault else "OFF")
        self.client.publish(f"{settings.BASE_TOPIC}/charger_source/bms_offline_fallback",
                            "ON" if self._bms_offline_fallback_active else "OFF")
        self.client.publish(f"{settings.BASE_TOPIC}/grid_limiter/throttled",
                            "ON" if self.grid_limiter.is_throttled or self.grid_limiter.is_locked_out else "OFF")
        self.client.publish(f"{settings.BASE_TOPIC}/grid_limiter/mcb_lockout",
                            "ON" if self.grid_limiter.is_locked_out else "OFF")
        self.client.publish(f"{settings.BASE_TOPIC}/grid_limiter/max_power_w/state",
                            self.grid_limiter.max_grid_power_w)
        self.client.publish(f"{settings.BASE_TOPIC}/grid_limiter/mcb_rating_a/state",
                            self.grid_limiter.mcb_rating_a)
        grid_voltage = self.zmai_meter.voltage_v if self.zmai_meter.voltage_v is not None else settings.GRID_NOMINAL_VOLTAGE_V
        self.client.publish(f"{settings.BASE_TOPIC}/grid_limiter/mcb_threshold_w",
                            round(self.grid_limiter.mcb_power_w(grid_voltage)))

        self.client.publish(f"{settings.BASE_TOPIC}/battery/discharge_stop_soc/state",
                            self.battery_mode.low_battery_protection_soc_pct)
        self.client.publish(f"{settings.BASE_TOPIC}/battery/discharge_resume_soc/state",
                            self.battery_mode.grid_stop_charging_soc_pct)
        self.client.publish(f"{settings.BASE_TOPIC}/battery/grid_quick_charge_soc/state",
                            self.battery_mode.grid_quick_charge_soc_pct)
        self.client.publish(f"{settings.BASE_TOPIC}/battery/back_to_grid_v/state", self.back_to_grid_v)
        self.client.publish(f"{settings.BASE_TOPIC}/battery/back_to_battery_v/state", self.back_to_battery_v)

    def _apply_npe_bonding(self, ac_input_voltage_v, grid_power_w, zmai_online, inverter_online, now):
        desired_bond_state = self.npe_bonding.decide(ac_input_voltage_v, grid_power_w, zmai_online, inverter_online, now)
        self.npe_bonding.apply(desired_bond_state)
        self.client.publish(f"{settings.BASE_TOPIC}/npe_bonding/state", "ON" if self.npe_bonding.is_bonded else "OFF")

        for reason_key, reason_value in self.npe_bonding.last_reasons.items():
            self.client.publish(f"{settings.BASE_TOPIC}/npe_bonding/debug/{reason_key}", reason_value)
        self.client.publish(f"{settings.BASE_TOPIC}/npe_bonding/mode/state", self.npe_bonding.mode)

    def _check_pi_throttle(self, now):
        throttled_hex = read_throttled_hex()

        if throttled_hex is None:
            return

        undervoltage_active = bool(throttled_hex & 0x1)
        active_flags = decode_active_flags(throttled_hex)
        self.undervoltage_alarm.update(undervoltage_active, f"flags: {', '.join(active_flags) or 'none'}", now)
        self.client.publish(f"{settings.BASE_TOPIC}/pi/undervoltage", "ON" if undervoltage_active else "OFF")
        self.client.publish(f"{settings.BASE_TOPIC}/pi/throttled_raw", hex(throttled_hex))

        if active_flags:
            self.client.publish(f"{settings.BASE_TOPIC}/pi/throttle_flags", ", ".join(active_flags))
        else:
            self.client.publish(f"{settings.BASE_TOPIC}/pi/throttle_flags", "none")

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
