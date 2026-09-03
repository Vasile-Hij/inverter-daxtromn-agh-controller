"""DAH battery CAN protocol: frame decoders for SMA/Pylontech-compatible BMS.

Each decoder is registered by CAN ID and called with (payload_bytes, fields_dict).
Decoded values are written into the fields dict, keyed by MQTT-friendly names.

CAN ID map (verified against DAH LiFePO4 16S battery):

    0x351  Charge/discharge voltage and current limits
    0x355  SOC and SOH percentages
    0x356  Pack voltage, current, temperature
    0x359  Alarm and warning flags, module count
    0x35C  Charge/discharge enable, force-charge request
    0x35E  Manufacturer name (ASCII)
    0x373  Cell min/max voltage (mV) and temperature (0.1 C)
    0x379  Battery capacity (Ah)
"""

import struct


FRAME_DECODERS = {}


def _register(can_id):
    def decorator(func):
        FRAME_DECODERS[can_id] = func
        return func
    return decorator


@_register(0x351)
def _decode_charge_discharge_limits(data, fields):
    if len(data) < 8:
        return
    charge_voltage_raw, charge_current_raw, discharge_current_raw, discharge_voltage_raw = struct.unpack_from("<HhhH", data)
    fields["bms_charge_voltage_limit_v"] = round(charge_voltage_raw * 0.1, 1)
    fields["bms_charge_current_limit_a"] = round(charge_current_raw * 0.1, 1)
    fields["bms_discharge_current_limit_a"] = round(discharge_current_raw * 0.1, 1)
    fields["bms_discharge_voltage_limit_v"] = round(discharge_voltage_raw * 0.1, 1)


@_register(0x355)
def _decode_soc_soh(data, fields):
    if len(data) < 4:
        return
    soc_pct, soh_pct = struct.unpack_from("<HH", data)
    fields["bms_soc_pct"] = soc_pct
    fields["bms_soh_pct"] = soh_pct


@_register(0x356)
def _decode_voltage_current_temp(data, fields):
    if len(data) < 6:
        return
    voltage_raw, current_raw, temperature_raw = struct.unpack_from("<hhh", data)
    fields["bms_voltage_v"] = round(voltage_raw * 0.01, 2)
    fields["bms_current_a"] = round(current_raw * 0.1, 1)
    fields["bms_temperature_c"] = round(temperature_raw * 0.1, 1)


@_register(0x359)
def _decode_alarms(data, fields):
    if len(data) < 7:
        return
    alarm_byte_0 = data[0]
    alarm_byte_1 = data[1]
    warning_byte_0 = data[2]
    warning_byte_1 = data[3]
    module_count = data[4]

    alarm_flags = []
    if alarm_byte_0 & 0x02:
        alarm_flags.append("cell_high_voltage")
    if alarm_byte_0 & 0x04:
        alarm_flags.append("cell_low_voltage")
    if alarm_byte_0 & 0x08:
        alarm_flags.append("high_temperature")
    if alarm_byte_0 & 0x10:
        alarm_flags.append("low_temperature")
    if alarm_byte_1 & 0x01:
        alarm_flags.append("high_charge_current")
    if alarm_byte_1 & 0x02:
        alarm_flags.append("high_discharge_current")
    fields["bms_alarms"] = ",".join(alarm_flags) if alarm_flags else "none"

    warning_flags = []
    if warning_byte_0 & 0x02:
        warning_flags.append("cell_high_voltage")
    if warning_byte_0 & 0x04:
        warning_flags.append("cell_low_voltage")
    if warning_byte_0 & 0x08:
        warning_flags.append("high_temperature")
    if warning_byte_0 & 0x10:
        warning_flags.append("low_temperature")
    if warning_byte_1 & 0x01:
        warning_flags.append("high_charge_current")
    if warning_byte_1 & 0x02:
        warning_flags.append("high_discharge_current")
    fields["bms_warnings"] = ",".join(warning_flags) if warning_flags else "none"
    fields["bms_module_count"] = module_count


@_register(0x35C)
def _decode_charge_request(data, fields):
    if len(data) < 2:
        return
    flags = struct.unpack_from("<H", data)[0]
    fields["bms_charge_enable"] = bool(flags & 0x80)
    fields["bms_discharge_enable"] = bool(flags & 0x40)
    fields["bms_force_charge_request"] = bool(flags & 0x20)


@_register(0x373)
def _decode_cell_min_max(data, fields):
    if len(data) < 8:
        return
    cell_min_mv, cell_max_mv, temp_min_raw, temp_max_raw = struct.unpack_from("<HHHH", data)
    fields["bms_cell_min_mv"] = cell_min_mv
    fields["bms_cell_max_mv"] = cell_max_mv
    fields["bms_cell_diff_mv"] = cell_max_mv - cell_min_mv
    fields["bms_temp_min_c"] = round(temp_min_raw * 0.1, 1)
    fields["bms_temp_max_c"] = round(temp_max_raw * 0.1, 1)


@_register(0x379)
def _decode_capacity(data, fields):
    if len(data) < 2:
        return
    capacity_raw = struct.unpack_from("<H", data)[0]
    fields["bms_capacity_ah"] = capacity_raw


@_register(0x35E)
def _decode_manufacturer(data, fields):
    manufacturer_name = data.rstrip(b"\x00").decode("ascii", errors="replace").strip()
    if manufacturer_name:
        fields["bms_manufacturer"] = manufacturer_name
