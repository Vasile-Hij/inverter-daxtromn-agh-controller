"""Configure Daxtromn inverter battery settings via PI30 protocol over RS232.

Queries current settings (QPIRI) and applies battery configuration for the
DAH LiFePO4 battery. Run with no arguments to view current settings.

LCD program - PI30 command mapping:
  05  Battery type           - PBT
  11  Max utility current    - MUCHGC
  26  Bulk/CV voltage (max)  - PCVV
  27  Float voltage          - PBFT
  29  Low DC cut-off (min)   - PSDV
"""

import argparse
import sys

from pi30 import PI30Connection, is_number

INVERTER_PORT = "/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A5069RR4-if00-port0"
INVERTER_BAUD = 2400
QUERY_MAX_ATTEMPTS = 3


class DaxtromnConfigurator(PI30Connection):
    """Daxtromn inverter configuration tool.

    Extends PI30Connection with QPIRI settings query, display, and apply
    methods for battery parameter tuning.
    """

    BATTERY_TYPE_NAMES = {
        0: "AGM",
        1: "Flooded",
        2: "User-Defined",
        3: "LIb (Lithium)",
    }

    CHARGER_SOURCE_NAMES = {
        0: "Utility first",
        1: "Solar first",
        2: "Solar and Utility",
        3: "Solar only",
    }

    OUTPUT_SOURCE_NAMES = {
        0: "Utility first (USB)",
        1: "Solar first (SUB)",
        2: "SBU",
    }

    NON_NUMERIC_FIELDS = ("machine_type", "device_status")

    QPIRI_FIELDS = [
        "ac_input_voltage_v",
        "ac_input_current_a",
        "ac_output_voltage_v",
        "ac_output_frequency_hz",
        "ac_output_current_a",
        "ac_output_apparent_power_va",
        "ac_output_active_power_w",
        "battery_nominal_voltage_v",
        "battery_recharge_voltage_v",
        "battery_under_voltage_v",
        "battery_bulk_cv_voltage_v",
        "battery_float_voltage_v",
        "battery_type",
        "max_ac_charging_current_a",
        "max_charging_current_a",
        "input_voltage_range",
        "output_source_priority",
        "charger_source_priority",
        "max_parallel_units",
        "machine_type",
        "topology",
        "output_mode",
        "battery_redischarge_voltage_v",
        "pv_ok_parallel",
        "pv_power_balance",
    ]

    def _all_numeric_fields_valid(self, fields):
        for index in range(min(len(fields), len(self.QPIRI_FIELDS))):
            field_name = self.QPIRI_FIELDS[index]
            if field_name not in self.NON_NUMERIC_FIELDS and not is_number(fields[index]):
                return False
        return True

    def _parse_qpiri_fields(self, fields):
        settings_by_name = {}
        for index, field_name in enumerate(self.QPIRI_FIELDS):
            if index >= len(fields):
                break
            raw_value = fields[index]
            if is_number(raw_value):
                settings_by_name[field_name] = float(raw_value)
            else:
                settings_by_name[field_name] = raw_value
        return settings_by_name

    def query_settings(self):
        for _attempt in range(QUERY_MAX_ATTEMPTS):
            raw_response = self.send_command("QPIRI")
            payload = self.extract_payload(raw_response)
            if payload is None:
                continue
            fields = payload.split()
            if len(fields) < len(self.QPIRI_FIELDS):
                continue
            if not self._all_numeric_fields_valid(fields):
                continue
            return self._parse_qpiri_fields(fields)
        print(f"error: no valid QPIRI response after {QUERY_MAX_ATTEMPTS} attempts")
        return None

    @classmethod
    def _display_coded_setting(cls, settings, field_name, label, code_names):
        raw_code = settings.get(field_name)
        if raw_code is None:
            return
        code = int(float(raw_code))
        code_name = code_names.get(code, "unknown")
        print(f"  {label} {code} ({code_name})")

    @classmethod
    def display_settings(cls, settings):
        if settings is None:
            return
        cls._display_coded_setting(settings, "battery_type", "[05] Battery type:           ", cls.BATTERY_TYPE_NAMES)
        print(f"  [26] Bulk/CV voltage (max):    {settings.get('battery_bulk_cv_voltage_v', '?')} V")
        print(f"  [27] Float voltage:            {settings.get('battery_float_voltage_v', '?')} V")
        print(f"  [29] Under voltage (min):      {settings.get('battery_under_voltage_v', '?')} V")
        print(f"  [--] Recharge voltage:         {settings.get('battery_recharge_voltage_v', '?')} V")
        print(f"  [--] Re-discharge voltage:     {settings.get('battery_redischarge_voltage_v', '?')} V")
        print(f"  [--] Nominal voltage:          {settings.get('battery_nominal_voltage_v', '?')} V")
        print(f"  [11] Max AC charge current:    {settings.get('max_ac_charging_current_a', '?')} A")
        print(f"  [02] Max total charge current: {settings.get('max_charging_current_a', '?')} A")
        cls._display_coded_setting(settings, "output_source_priority", "[01] Output source priority: ", cls.OUTPUT_SOURCE_NAMES)
        cls._display_coded_setting(settings, "charger_source_priority", "[16] Charger source priority:", cls.CHARGER_SOURCE_NAMES)

    def apply_setting(self, command_text, description):
        print(f"  {description}: {command_text} ... ", end="", flush=True)
        for _attempt in range(QUERY_MAX_ATTEMPTS):
            raw_response = self.send_command(command_text)
            if raw_response is None:
                continue
            payload = self.extract_payload(raw_response)
            if payload is None:
                continue
            if "ACK" in payload:
                print("OK")
                return True
            if "NAK" in payload:
                print("REJECTED")
                return False
        print(f"FAIL (no valid response after {QUERY_MAX_ATTEMPTS} attempts)")
        return False

    def send_raw_and_print(self, raw_command_text):
        print(f"sending: {raw_command_text}")
        raw_response = self.send_command(raw_command_text)
        if raw_response is None:
            return
        print(f"raw: {raw_response}")
        payload = self.extract_payload(raw_response)
        if payload is not None:
            print(f"payload: {payload}")

    @staticmethod
    def collect_requested_changes(args):
        possible_changes = [
            (args.battery_type, "PBT{:02d}", "battery type"),
            (args.cv_voltage, "PCVV{:04.1f}", "bulk/CV voltage"),
            (args.float_voltage, "PBFT{:04.1f}", "float voltage"),
            (args.cutoff_voltage, "PSDV{:04.1f}", "low DC cut-off"),
            (args.utility_charge_current, "MUCHGC{:03d}", "max utility charge current"),
            (args.total_charge_current, "MCHGC{:03d}", "max total charge current"),
            (args.charger_source, "PCP{:02d}", "charger source priority"),
        ]
        requested_changes = []
        for value, command_template, description in possible_changes:
            if value is not None:
                requested_changes.append((command_template.format(value), description))
        return requested_changes

    def run(self, args):
        if args.raw:
            self.send_raw_and_print(args.raw)
            return

        print(f"port: {self._port}")
        print("\ncurrent settings (QPIRI):")
        self.display_settings(self.query_settings())

        requested_changes = self.collect_requested_changes(args)
        if not requested_changes:
            print("\nno changes requested")
            print("example: python3 daxtromn_config.py --battery-type 3 --cv-voltage 57.6 --utility-charge-current 100")
            print("note: with LIb battery type, float voltage (27) and low DC cut-off (29) are locked by the inverter")
            return

        print("\napplying:")
        for command_text, description in requested_changes:
            self.apply_setting(command_text, description)

        print("\nverifying:")
        self.display_settings(self.query_settings())


def build_argument_parser():
    parser = argparse.ArgumentParser(
        description="Configure Daxtromn inverter battery settings (PI30 protocol)"
    )
    parser.add_argument("--port", default=INVERTER_PORT)
    parser.add_argument("--baud", type=int, default=INVERTER_BAUD)
    parser.add_argument("--battery-type", type=int, help="battery type (0=AGM 1=Flooded 2=User 3=LIb)")
    parser.add_argument("--cv-voltage", type=float, help="bulk/CV charging voltage in V (program 26)")
    parser.add_argument("--float-voltage", type=float, help="float charging voltage in V (program 27)")
    parser.add_argument("--cutoff-voltage", type=float, help="low DC cut-off voltage in V (program 29)")
    parser.add_argument("--utility-charge-current", type=int, help="max utility charging current in A (program 11)")
    parser.add_argument("--total-charge-current", type=int, help="max total charging current in A (program 02)")
    parser.add_argument("--charger-source", type=int, help="charger source priority (0=Utility 1=Solar-first 2=Solar+Utility 3=Solar-only, program 16)")
    parser.add_argument("--raw", help="send a raw PI30 command (e.g. QPIRI, QPIGS)")
    return parser


def verify_crc_self_test():
    expected_qpigs_crc = 0xB7A9
    computed_qpigs_crc = PI30Connection.compute_crc(b"QPIGS")
    if computed_qpigs_crc != expected_qpigs_crc:
        print(f"CRC self-test failed: expected 0x{expected_qpigs_crc:04X}, got 0x{computed_qpigs_crc:04X}")
        sys.exit(1)


def main():
    args = build_argument_parser().parse_args()
    verify_crc_self_test()
    configurator = DaxtromnConfigurator(args.port, args.baud)
    configurator.run(args)


if __name__ == "__main__":
    main()
