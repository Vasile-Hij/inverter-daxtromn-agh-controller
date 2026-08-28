import time
from functools import wraps

from pi30 import PI30Connection, is_number
from npe_bonding import GRID_VOLTAGE_THRESHOLD_V

COMMAND_MAX_RETRIES = 3

BATTERY_VOLTAGE_PRESENT_V = 20
BATTERY_CURRENT_NOISE_A = 0.5
BATTERY_OUTPUT_FLOOR_W = 50

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


class InverterCommandError(Exception):
    pass


def retry(exceptions, retries=COMMAND_MAX_RETRIES, delay=1, fail_callback=None):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(1, retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as error:
                    last_exception = error
                    print(f"{func.__name__} failed (attempt {attempt}/{retries}): {error}", flush=True)
                    if attempt < retries:
                        time.sleep(delay)
            if fail_callback is not None:
                fail_callback(last_exception)
            return None
        return wrapper
    return decorator


class DaxtromnInverter(PI30Connection):
    """Daxtromn hybrid inverter polled over RS232 (PI30 protocol).

    Extends PI30Connection with QPIGS polling, data staleness tracking, and
    battery presence detection.
    """

    QPIRI_OUTPUT_SOURCE_INDEX = 16
    QPIRI_CHARGER_SOURCE_INDEX = 17
    OUTPUT_SOURCE_NAMES = {0: "USB", 1: "SUB", 2: "SBU"}
    CHARGER_SOURCE_NAMES = {0: "utility_first", 1: "solar_first", 2: "solar_and_utility", 3: "solar_only"}

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

    def query_output_source_priority(self):
        raw_response = self.send_command("QPIRI")
        payload = self.extract_payload(raw_response)
        if payload is None:
            return None
        fields = payload.split()
        if len(fields) <= self.QPIRI_OUTPUT_SOURCE_INDEX:
            return None
        raw_value = fields[self.QPIRI_OUTPUT_SOURCE_INDEX]
        if not is_number(raw_value):
            return None
        priority_code = int(float(raw_value))
        return self.OUTPUT_SOURCE_NAMES.get(priority_code)

    def query_charger_source_priority(self):
        raw_response = self.send_command("QPIRI")
        payload = self.extract_payload(raw_response)
        if payload is None:
            return None
        fields = payload.split()
        if len(fields) <= self.QPIRI_CHARGER_SOURCE_INDEX:
            return None
        raw_value = fields[self.QPIRI_CHARGER_SOURCE_INDEX]
        if not is_number(raw_value):
            return None
        charger_code = int(float(raw_value))
        return self.CHARGER_SOURCE_NAMES.get(charger_code)

    @retry(InverterCommandError)
    def set_output_priority(self, pop_command):
        expected_code = int(pop_command[3:])
        expected_name = self.OUTPUT_SOURCE_NAMES.get(expected_code)
        raw_response = self.send_command(pop_command)
        if raw_response is None:
            raise InverterCommandError(f"no response to {pop_command}")
        payload = self.extract_payload(raw_response)
        if payload is None:
            raise InverterCommandError(f"no payload in response to {pop_command}")
        if "ACK" not in payload:
            raise InverterCommandError(f"{pop_command} rejected (NAK)")
        time.sleep(1)
        actual_priority = self.query_output_source_priority()
        if actual_priority != expected_name:
            print(f"set_output_priority: {pop_command} ACKed but verify returned {actual_priority}", flush=True)
        return True

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
