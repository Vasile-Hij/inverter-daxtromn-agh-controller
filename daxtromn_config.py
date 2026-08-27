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

    def __init__(self, port, baud):
        super().__init__(port, baud)

    def query_settings(self):
        for _attempt in range(3):
            raw_response = self.send_command("QPIRI")
            payload = self.extract_payload(raw_response)
            if payload is None:
                continue
            fields = payload.split()
            if len(fields) < len(self.QPIRI_FIELDS):
                continue
            all_valid = True
            for index in range(min(len(fields), len(self.QPIRI_FIELDS))):
                field_name = self.QPIRI_FIELDS[index]
                if field_name not in ("machine_type", "device_status"):
                    if not is_number(fields[index]):
                        all_valid = False
                        break
            if not all_valid:
                continue
            settings = {}
            for index, field_name in enumerate(self.QPIRI_FIELDS):
                if index >= len(fields):
                    break
                raw_value = fields[index]
                if is_number(raw_value):
                    settings[field_name] = float(raw_value)
                else:
                    settings[field_name] = raw_value
            return settings
        print("error: no valid QPIRI response after 3 attempts")
        return None

    @staticmethod
    def display_settings(settings):
        if settings is None:
            return

        battery_type_code = settings.get("battery_type")
        if battery_type_code is not None:
            type_int = int(float(battery_type_code))
            type_name = DaxtromnConfigurator.BATTERY_TYPE_NAMES.get(type_int, "unknown")
            print(f"  [05] Battery type:            {type_int} ({type_name})")

        print(f"  [26] Bulk/CV voltage (max):    {settings.get('battery_bulk_cv_voltage_v', '?')} V")
        print(f"  [27] Float voltage:            {settings.get('battery_float_voltage_v', '?')} V")
        print(f"  [29] Under voltage (min):      {settings.get('battery_under_voltage_v', '?')} V")
        print(f"  [--] Recharge voltage:         {settings.get('battery_recharge_voltage_v', '?')} V")
        print(f"  [--] Re-discharge voltage:     {settings.get('battery_redischarge_voltage_v', '?')} V")
        print(f"  [--] Nominal voltage:          {settings.get('battery_nominal_voltage_v', '?')} V")
        print(f"  [11] Max AC charge current:    {settings.get('max_ac_charging_current_a', '?')} A")
        print(f"  [02] Max total charge current: {settings.get('max_charging_current_a', '?')} A")

        output_source = settings.get("output_source_priority")
        if output_source is not None:
            output_int = int(float(output_source))
            output_name = DaxtromnConfigurator.OUTPUT_SOURCE_NAMES.get(output_int, "unknown")
            print(f"  [01] Output source priority:  {output_int} ({output_name})")

        charger_source = settings.get("charger_source_priority")
        if charger_source is not None:
            charger_int = int(float(charger_source))
            charger_name = DaxtromnConfigurator.CHARGER_SOURCE_NAMES.get(charger_int, "unknown")
            print(f"  [16] Charger source priority: {charger_int} ({charger_name})")

    def apply_setting(self, command_text, description):
        print(f"  {description}: {command_text} ... ", end="", flush=True)
        for _attempt in range(3):
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
        print("FAIL (no valid response after 3 attempts)")
        return False

    def run(self, args):
        if args.raw:
            print(f"sending: {args.raw}")
            raw_response = self.send_command(args.raw)
            if raw_response is not None:
                print(f"raw: {raw_response}")
                payload = self.extract_payload(raw_response)
                if payload is not None:
                    print(f"payload: {payload}")
            return

        print(f"port: {self._port}")
        print(f"\ncurrent settings (QPIRI):")
        settings = self.query_settings()
        self.display_settings(settings)

        has_changes = any([
            args.battery_type is not None,
            args.cv_voltage is not None,
            args.float_voltage is not None,
            args.cutoff_voltage is not None,
            args.utility_charge_current is not None,
            args.total_charge_current is not None,
            args.charger_source is not None,
        ])

        if not has_changes:
            print("\nno changes requested")
            print("example: python3 daxtromn_config.py --battery-type 3 --cv-voltage 57.6 --utility-charge-current 100")
            print("note: with LIb battery type, float voltage (27) and low DC cut-off (29) are locked by the inverter")
            return

        print("\napplying:")

        if args.battery_type is not None:
            self.apply_setting(f"PBT{args.battery_type:02d}", "battery type")

        if args.cv_voltage is not None:
            self.apply_setting(f"PCVV{args.cv_voltage:04.1f}", "bulk/CV voltage")

        if args.float_voltage is not None:
            self.apply_setting(f"PBFT{args.float_voltage:04.1f}", "float voltage")

        if args.cutoff_voltage is not None:
            self.apply_setting(f"PSDV{args.cutoff_voltage:04.1f}", "low DC cut-off")

        if args.utility_charge_current is not None:
            self.apply_setting(f"MUCHGC{args.utility_charge_current:03d}", "max utility charge current")

        if args.total_charge_current is not None:
            self.apply_setting(f"MCHGC{args.total_charge_current:03d}", "max total charge current")

        if args.charger_source is not None:
            self.apply_setting(f"PCP{args.charger_source:02d}", "charger source priority")

        print("\nverifying:")
        updated_settings = self.query_settings()
        self.display_settings(updated_settings)


def main():
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

    args = parser.parse_args()

    expected_qpigs_crc = 0xB7A9
    computed_qpigs_crc = PI30Connection.compute_crc(b"QPIGS")
    if computed_qpigs_crc != expected_qpigs_crc:
        print(f"CRC self-test failed: expected 0x{expected_qpigs_crc:04X}, got 0x{computed_qpigs_crc:04X}")
        sys.exit(1)

    configurator = DaxtromnConfigurator(args.port, args.baud)
    configurator.run(args)


if __name__ == "__main__":
    main()
