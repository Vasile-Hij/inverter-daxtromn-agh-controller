"""Home Assistant MQTT discovery: declares every sensor, select, and number entity."""

import json

import settings
from inverter.battery_mode import BATTERY_MODES

DEVICE_INFO = {"identifiers": [settings.DEVICE_ID], "name": "rasp", "manufacturer": "Daxtromn/ZMAi-90"}
AVAILABILITY = [
    {
        "topic": settings.AVAILABILITY_TOPIC,
        "payload_available": "online",
        "payload_not_available": "offline",
    }
]

# (object_id, name, state_topic, unit, device_class)
MEASUREMENT_SENSORS = [
    ("zmai_power", "Grid Power (ZMAi-90)", f"{settings.BASE_TOPIC}/zmai/power_w", "W", "power"),
    ("zmai_voltage", "Grid Voltage (ZMAi-90)", f"{settings.BASE_TOPIC}/zmai/voltage_v", "V", "voltage"),
    ("zmai_current", "Grid Current (ZMAi-90)", f"{settings.BASE_TOPIC}/zmai/current_a", "A", "current"),
    ("inverter_ac_output_power", "Total House Consumption", f"{settings.BASE_TOPIC}/inverter/ac_output_power_w", "W", "power"),
    ("inverter_pv_input_power", "PV1 Power", f"{settings.BASE_TOPIC}/inverter/pv1_power_w", "W", "power"),
    ("inverter_ac_input_voltage", "Daxtromn AC Input Voltage", f"{settings.BASE_TOPIC}/inverter/ac_input_voltage_v", "V", "voltage"),
    ("inverter_pv_input_voltage", "PV1 Input Voltage", f"{settings.BASE_TOPIC}/inverter/pv1_input_voltage_v", "V", "voltage"),
    ("inverter_battery_capacity", "Battery Capacity", f"{settings.BASE_TOPIC}/inverter/battery_capacity_pct", "%", "battery"),
    ("battery_power", "Battery", f"{settings.BASE_TOPIC}/derived/battery_power_w", "W", "power"),
    ("battery_charge_power", "Battery Charge 14.8kW", f"{settings.BASE_TOPIC}/derived/battery_charge_power_w", "W", "power"),
    ("battery_discharge_power", "Battery Discharge 14.8kW", f"{settings.BASE_TOPIC}/derived/battery_discharge_power_w", "W", "power"),
    ("battery_soc_estimated", "Battery SOC (Estimated)", f"{settings.BASE_TOPIC}/derived/battery_soc_estimated_pct", "%", "battery"),
    ("pv2_power", "PV2 Power", f"{settings.BASE_TOPIC}/derived/pv2_power_w", "W", "power"),
    ("pv_total_power", "PV Total Power", f"{settings.BASE_TOPIC}/derived/pv_total_power_w", "W", "power"),
    ("bms_voltage", "BMS Voltage", f"{settings.BASE_TOPIC}/can_battery/bms_voltage_v", "V", "voltage"),
    ("bms_current", "BMS Current", f"{settings.BASE_TOPIC}/can_battery/bms_current_a", "A", "current"),
    ("bms_temperature", "BMS Temperature", f"{settings.BASE_TOPIC}/can_battery/bms_temperature_c", "°C", "temperature"),
    ("bms_soc", "BMS SOC", f"{settings.BASE_TOPIC}/can_battery/bms_soc_pct", "%", "battery"),
    ("bms_soh", "BMS SOH", f"{settings.BASE_TOPIC}/can_battery/bms_soh_pct", "%", None),
    ("bms_charge_voltage_limit", "BMS Charge Voltage Limit", f"{settings.BASE_TOPIC}/can_battery/bms_charge_voltage_limit_v", "V", "voltage"),
    ("bms_charge_current_limit", "BMS Charge Current Limit", f"{settings.BASE_TOPIC}/can_battery/bms_charge_current_limit_a", "A", "current"),
    ("bms_discharge_current_limit", "BMS Discharge Current Limit", f"{settings.BASE_TOPIC}/can_battery/bms_discharge_current_limit_a", "A", "current"),
    ("bms_cell_min_voltage", "BMS Cell Min Voltage", f"{settings.BASE_TOPIC}/can_battery/bms_cell_min_mv", "mV", "voltage"),
    ("bms_cell_max_voltage", "BMS Cell Max Voltage", f"{settings.BASE_TOPIC}/can_battery/bms_cell_max_mv", "mV", "voltage"),
    ("bms_cell_diff", "BMS Cell Voltage Diff", f"{settings.BASE_TOPIC}/can_battery/bms_cell_diff_mv", "mV", None),
    ("bms_temp_min", "BMS Temp Min", f"{settings.BASE_TOPIC}/can_battery/bms_temp_min_c", "°C", "temperature"),
    ("bms_temp_max", "BMS Temp Max", f"{settings.BASE_TOPIC}/can_battery/bms_temp_max_c", "°C", "temperature"),
]

# (object_id, name, state_topic, unit, device_class)
ENERGY_SENSORS = [
    ("battery_charge_energy", "Battery Charge Energy 14.8kW", f"{settings.BASE_TOPIC}/derived/battery_charge_energy_kwh", "kWh", "energy"),
    ("battery_discharge_energy", "Battery Discharge Energy 14.8kW", f"{settings.BASE_TOPIC}/derived/battery_discharge_energy_kwh", "kWh", "energy"),
    ("solar_production_energy", "Solar Production Energy", f"{settings.BASE_TOPIC}/derived/solar_production_energy_kwh", "kWh", "energy"),
    ("grid_import_energy", "Grid Import Energy", f"{settings.BASE_TOPIC}/derived/grid_import_energy_kwh", "kWh", "energy"),
]

# (object_id, name, state_topic)
TEXT_SENSORS = [
    ("inverter_actual_output_priority", "Inverter Output Priority (actual)", f"{settings.BASE_TOPIC}/inverter/actual_output_priority"),
    ("inverter_actual_charger_source", "Inverter Charger Source (actual)", f"{settings.BASE_TOPIC}/inverter/actual_charger_source"),
    ("zmai_data", "ZMAi-90 Data Status", f"{settings.BASE_TOPIC}/zmai/data_status"),
    ("inverter_data", "Daxtromn Data Status", f"{settings.BASE_TOPIC}/inverter/data_status"),
    ("can_battery_data", "CAN Battery Data Status", f"{settings.BASE_TOPIC}/can_battery/data_status"),
    ("bms_alarms", "BMS Alarms", f"{settings.BASE_TOPIC}/can_battery/bms_alarms"),
    ("bms_warnings", "BMS Warnings", f"{settings.BASE_TOPIC}/can_battery/bms_warnings"),
    ("battery_mode_display", "Battery Mode Status", f"{settings.BASE_TOPIC}/battery_mode/display"),
    ("pi_throttle_flags", "RPi Throttle Flags", f"{settings.BASE_TOPIC}/pi/throttle_flags"),
]

# (object_id, name, state_topic, payload_on, payload_off, device_class or None)
BINARY_SENSORS = [
    ("inverter_fault", "Daxtromn Link Fault", f"{settings.BASE_TOPIC}/inverter/data_status", "offline", "online", "problem"),
    ("npe_failsafe", "N-PE Failsafe Blind", f"{settings.BASE_TOPIC}/npe_bonding/failsafe_status", "blind", "ok", "safety"),
    ("npe_bonded", "N-PE Bonded", f"{settings.BASE_TOPIC}/npe_bonding/state", "ON", "OFF", None),
    ("battery_low", "Battery Low Voltage", f"{settings.BASE_TOPIC}/battery/low_voltage_status", "low", "ok", "problem"),
    ("output_priority_fault", "Output Priority Command Fault", f"{settings.BASE_TOPIC}/output_priority/command_fault", "ON", "OFF", "problem"),
    ("battery_low_battery_active", "Battery Low Protection Active", f"{settings.BASE_TOPIC}/battery_mode/low_battery_active", "ON", "OFF", None),
    ("pi_undervoltage", "RPi Undervoltage", f"{settings.BASE_TOPIC}/pi/undervoltage", "ON", "OFF", "problem"),
    ("grid_charging_active", "Grid Charging Active", f"{settings.BASE_TOPIC}/grid_charging/active", "ON", "OFF", None),
    ("grid_mcb_lockout", "Grid MCB Lockout", f"{settings.BASE_TOPIC}/grid_limiter/mcb_lockout", "ON", "OFF", "problem"),
]

# (object_id, name, state_topic, command_topic, options)
SELECTS = [
    ("npe_mode", "N-PE Bonding Mode", f"{settings.BASE_TOPIC}/npe_bonding/mode/state", settings.NPE_MODE_TOPIC, settings.NPE_MODES),
    ("battery_mode", "Battery Mode", f"{settings.BASE_TOPIC}/battery_mode/state", settings.BATTERY_MODE_TOPIC, BATTERY_MODES),
]

# (object_id, name, state_topic, command_topic, minimum, maximum, step, unit)
NUMBERS = [
    ("discharge_stop_soc", "Low Battery Protection", f"{settings.BASE_TOPIC}/battery/discharge_stop_soc/state",
     settings.LOW_BATTERY_PROTECTION_SOC_TOPIC, *settings.LOW_BATTERY_PROTECTION_SOC_RANGE, 1, "%"),
    ("discharge_resume_soc", "Grid Stop Charging", f"{settings.BASE_TOPIC}/battery/discharge_resume_soc/state",
     settings.GRID_STOP_CHARGING_SOC_TOPIC, *settings.GRID_STOP_CHARGING_SOC_RANGE, 1, "%"),
    ("grid_quick_charge_soc", "Grid Quick Charge", f"{settings.BASE_TOPIC}/battery/grid_quick_charge_soc/state",
     settings.GRID_QUICK_CHARGE_SOC_TOPIC, *settings.GRID_QUICK_CHARGE_SOC_RANGE, 1, "%"),
    ("back_to_grid_v", "Back To Grid Voltage (prog 12)", f"{settings.BASE_TOPIC}/battery/back_to_grid_v/state",
     settings.BACK_TO_GRID_V_TOPIC, *settings.BACK_TO_GRID_V_RANGE, 0.5, "V"),
    ("back_to_battery_v", "Back To Battery Voltage (prog 13)", f"{settings.BASE_TOPIC}/battery/back_to_battery_v/state",
     settings.BACK_TO_BATTERY_V_TOPIC, *settings.BACK_TO_BATTERY_V_RANGE, 0.5, "V"),
    ("mcb_rating", "MCB Rating", f"{settings.BASE_TOPIC}/grid_limiter/mcb_rating_a/state",
     settings.MCB_RATING_TOPIC, *settings.MCB_RATING_RANGE, 1, "A"),
]


class HomeAssistantDiscovery:
    """Publishes retained MQTT discovery configs so Home Assistant creates entities."""

    def __init__(self, mqtt_client):
        self._mqtt_client = mqtt_client

    REMOVED_ENTITIES = [
        ("sensor", "grid_limiter_mcb_threshold"),
        ("number", "max_grid_power"),
        ("number", "max_grid_power_kw"),
        ("binary_sensor", "grid_limiter_throttled"),
    ]

    def publish_all(self):
        self._remove_stale_entities()
        self._publish_measurement_sensors()
        self._publish_energy_sensors()
        self._publish_text_sensors()
        self._publish_binary_sensors()
        self._publish_selects()
        self._publish_numbers()

    def _remove_stale_entities(self):
        for component, object_id in self.REMOVED_ENTITIES:
            config_topic = f"{settings.DISCOVERY_PREFIX}/{component}/{settings.DEVICE_ID}/{object_id}/config"
            self._mqtt_client.publish(config_topic, "", retain=True)

    def _publish_config(self, component, object_id, entity_config):
        entity_config["unique_id"] = f"{settings.UNIQUE_ID_PREFIX}_{object_id}"
        entity_config["availability"] = AVAILABILITY
        entity_config["device"] = DEVICE_INFO
        config_topic = f"{settings.DISCOVERY_PREFIX}/{component}/{settings.DEVICE_ID}/{object_id}/config"
        self._mqtt_client.publish(config_topic, json.dumps(entity_config), retain=True)

    def _publish_measurement_sensors(self):
        for object_id, name, state_topic, unit, device_class in MEASUREMENT_SENSORS:
            entity_config = {
                "name": name,
                "state_topic": state_topic,
                "state_class": "measurement",
            }
            if unit is not None:
                entity_config["unit_of_measurement"] = unit
            if device_class is not None:
                entity_config["device_class"] = device_class
            self._publish_config("sensor", object_id, entity_config)

    def _publish_energy_sensors(self):
        for object_id, name, state_topic, unit, device_class in ENERGY_SENSORS:
            self._publish_config("sensor", object_id, {
                "name": name,
                "state_topic": state_topic,
                "unit_of_measurement": unit,
                "device_class": device_class,
                "state_class": "total_increasing",
            })

    def _publish_text_sensors(self):
        for object_id, name, state_topic in TEXT_SENSORS:
            self._publish_config("sensor", object_id, {
                "name": name,
                "state_topic": state_topic,
            })

    def _publish_binary_sensors(self):
        for object_id, name, state_topic, payload_on, payload_off, device_class in BINARY_SENSORS:
            entity_config = {
                "name": name,
                "state_topic": state_topic,
                "payload_on": payload_on,
                "payload_off": payload_off,
            }
            if device_class is not None:
                entity_config["device_class"] = device_class
            self._publish_config("binary_sensor", object_id, entity_config)

    def _publish_selects(self):
        for object_id, name, state_topic, command_topic, options in SELECTS:
            self._publish_config("select", object_id, {
                "name": name,
                "state_topic": state_topic,
                "command_topic": command_topic,
                "retain": True,
                "options": list(options),
            })

    def _publish_numbers(self):
        for object_id, name, state_topic, command_topic, minimum, maximum, step, unit in NUMBERS:
            self._publish_config("number", object_id, {
                "name": name,
                "state_topic": state_topic,
                "command_topic": command_topic,
                "retain": True,
                "min": minimum,
                "max": maximum,
                "step": step,
                "unit_of_measurement": unit,
                "mode": "box",
            })
