"""Configure Daxtromn inverter battery settings via PI30 protocol over RS232.

Queries current settings (QPIRI) and applies battery configuration for the
DAH LiFePO4 battery. Run with no arguments to view current settings.

LCD program → PI30 command mapping:
  05  Battery type           → PBT
  11  Max utility current    → MUCHGC
  26  Bulk/CV voltage (max)  → PCVV
  27  Float voltage          → PBFT
  29  Low DC cut-off (min)   → PSDV
"""

import argparse
import os
import sys
import time

import serial

INVERTER_PORT = "/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A5069RR4-if00-port0"
INVERTER_BAUD = 2400

BATTERY_TYPE_NAMES = {
    0: "AGM",
    1: "Flooded",
    2: "User-Defined",
    3: "LIb (Lithium)",
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


def pi30_crc(data):
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc


def build_command(command_text):
    command_bytes = command_text.encode("ascii")
    crc = pi30_crc(command_bytes)
    crc_high = (crc >> 8) & 0xFF
    crc_low = crc & 0xFF
    return command_bytes + bytes([crc_high, crc_low]) + b"\r"


def is_number(text):
    stripped = text.strip()
    if not stripped:
        return False
    return stripped.lstrip("-+").replace(".", "", 1).isdigit()


def send_command(port, baud, command_text):
    if not os.path.exists(port):
        print(f"error: port not found: {port}")
        return None
    connection = serial.Serial(port, baud, timeout=2)
    connection.reset_input_buffer()
    command = build_command(command_text)
    connection.write(command)
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


def extract_payload(raw_response):
    if raw_response is None:
        return None
    frame_start = raw_response.find(b"(")
    if frame_start < 0:
        return None
    frame_end = raw_response.find(b"\r", frame_start)
    if frame_end < 0:
        frame_end = len(raw_response)
    payload_with_crc = raw_response[frame_start + 1 : frame_end]
    if len(payload_with_crc) >= 2:
        return payload_with_crc[:-2].decode("ascii", errors="replace")
    return payload_with_crc.decode("ascii", errors="replace")


def query_settings(port, baud):
    for _attempt in range(3):
        raw_response = send_command(port, baud, "QPIRI")
        payload = extract_payload(raw_response)
        if payload is None:
            continue
        fields = payload.split()
        if len(fields) < len(QPIRI_FIELDS):
            continue
        all_valid = True
        for index in range(min(len(fields), len(QPIRI_FIELDS))):
            field_name = QPIRI_FIELDS[index]
            if field_name not in ("machine_type", "device_status"):
                if not is_number(fields[index]):
                    all_valid = False
                    break
        if not all_valid:
            continue
        settings = {}
        for index, field_name in enumerate(QPIRI_FIELDS):
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


def display_settings(settings):
    if settings is None:
        return

    battery_type_code = settings.get("battery_type")
    if battery_type_code is not None:
        type_int = int(float(battery_type_code))
        type_name = BATTERY_TYPE_NAMES.get(type_int, "unknown")
        print(f"  [05] Battery type:            {type_int} ({type_name})")

    print(f"  [26] Bulk/CV voltage (max):    {settings.get('battery_bulk_cv_voltage_v', '?')} V")
    print(f"  [27] Float voltage:            {settings.get('battery_float_voltage_v', '?')} V")
    print(f"  [29] Under voltage (min):      {settings.get('battery_under_voltage_v', '?')} V")
    print(f"  [--] Recharge voltage:         {settings.get('battery_recharge_voltage_v', '?')} V")
    print(f"  [--] Re-discharge voltage:     {settings.get('battery_redischarge_voltage_v', '?')} V")
    print(f"  [--] Nominal voltage:          {settings.get('battery_nominal_voltage_v', '?')} V")
    print(f"  [11] Max AC charge current:    {settings.get('max_ac_charging_current_a', '?')} A")
    print(f"  [02] Max total charge current: {settings.get('max_charging_current_a', '?')} A")


def apply_setting(port, baud, command_text, description):
    print(f"  {description}: {command_text} ... ", end="", flush=True)
    for _attempt in range(3):
        raw_response = send_command(port, baud, command_text)
        if raw_response is None:
            continue
        payload = extract_payload(raw_response)
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
    parser.add_argument("--raw", help="send a raw PI30 command (e.g. QPIRI, QPIGS)")

    args = parser.parse_args()

    expected_qpigs_crc = 0xB7A9
    computed_qpigs_crc = pi30_crc(b"QPIGS")
    if computed_qpigs_crc != expected_qpigs_crc:
        print(f"CRC self-test failed: expected 0x{expected_qpigs_crc:04X}, got 0x{computed_qpigs_crc:04X}")
        sys.exit(1)

    if args.raw:
        print(f"sending: {args.raw}")
        raw_response = send_command(args.port, args.baud, args.raw)
        if raw_response is not None:
            print(f"raw: {raw_response}")
            payload = extract_payload(raw_response)
            if payload is not None:
                print(f"payload: {payload}")
        return

    print(f"port: {args.port}")
    print(f"\ncurrent settings (QPIRI):")
    settings = query_settings(args.port, args.baud)
    display_settings(settings)

    has_changes = any([
        args.battery_type is not None,
        args.cv_voltage is not None,
        args.float_voltage is not None,
        args.cutoff_voltage is not None,
        args.utility_charge_current is not None,
        args.total_charge_current is not None,
    ])

    if not has_changes:
        print("\nno changes requested")
        print("example: python3 daxtromn_config.py --battery-type 3 --cv-voltage 57.6 --utility-charge-current 100")
        print("note: with LIb battery type, float voltage (27) and low DC cut-off (29) are locked by the inverter")
        return

    print("\napplying:")

    if args.battery_type is not None:
        apply_setting(args.port, args.baud, f"PBT{args.battery_type:02d}", "battery type")

    if args.cv_voltage is not None:
        apply_setting(args.port, args.baud, f"PCVV{args.cv_voltage:04.1f}", "bulk/CV voltage")

    if args.float_voltage is not None:
        apply_setting(args.port, args.baud, f"PBFT{args.float_voltage:04.1f}", "float voltage")

    if args.cutoff_voltage is not None:
        apply_setting(args.port, args.baud, f"PSDV{args.cutoff_voltage:04.1f}", "low DC cut-off")

    if args.utility_charge_current is not None:
        apply_setting(args.port, args.baud, f"MUCHGC{args.utility_charge_current:03d}", "max utility charge current")

    if args.total_charge_current is not None:
        apply_setting(args.port, args.baud, f"MCHGC{args.total_charge_current:03d}", "max total charge current")

    print("\nverifying:")
    updated_settings = query_settings(args.port, args.baud)
    display_settings(updated_settings)


if __name__ == "__main__":
    main()
