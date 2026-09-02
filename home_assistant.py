"""Home Assistant MQTT discovery: declares every sensor, select, and number entity."""

import json

import settings
from discharge_guard import OUTPUT_PRIORITY_MODES

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
]

# (object_id, name, state_topic, unit, device_class)
ENERGY_SENSORS = [
    ("battery_charge_energy", "Battery Charge Energy 14.8kW", f"{settings.BASE_TOPIC}/derived/battery_charge_energy_kwh", "kWh", "energy"),
    ("battery_discharge_energy", "Battery Discharge Energy 14.8kW", f"{settings.BASE_TOPIC}/derived/battery_discharge_energy_kwh", "kWh", "energy"),
]

# (object_id, name, state_topic)
TEXT_SENSORS = [
    ("zmai_data", "ZMAi-90 Data Status", f"{settings.BASE_TOPIC}/zmai/data_status"),
    ("inverter_data", "Daxtromn Data Status", f"{settings.BASE_TOPIC}/inverter/data_status"),
    ("output_priority", "Output Priority", f"{settings.BASE_TOPIC}/output_priority/state"),
]

# (object_id, name, state_topic, payload_on, payload_off, device_class or None)
BINARY_SENSORS = [
    ("inverter_fault", "Daxtromn Link Fault", f"{settings.BASE_TOPIC}/inverter/data_status", "offline", "online", "problem"),
    ("npe_failsafe", "N-PE Failsafe Blind", f"{settings.BASE_TOPIC}/npe_bonding/failsafe_status", "blind", "ok", "safety"),
    ("npe_bonded", "N-PE Bonded", f"{settings.BASE_TOPIC}/npe_bonding/state", "ON", "OFF", None),
    ("battery_low", "Battery Low Voltage", f"{settings.BASE_TOPIC}/battery/low_voltage_status", "low", "ok", "problem"),
    ("output_priority_fault", "Output Priority Command Fault", f"{settings.BASE_TOPIC}/output_priority/command_fault", "ON", "OFF", "problem"),
]

# (object_id, name, state_topic, command_topic, options)
SELECTS = [
    ("npe_mode", "N-PE Bonding Mode", f"{settings.BASE_TOPIC}/npe_bonding/mode/state", settings.NPE_MODE_TOPIC, settings.NPE_MODES),
    ("output_priority_mode", "Output Priority Mode", f"{settings.BASE_TOPIC}/output_priority/mode/state", settings.OUTPUT_PRIORITY_MODE_TOPIC, OUTPUT_PRIORITY_MODES),
    ("charger_source", "Charger Source", f"{settings.BASE_TOPIC}/charger_source/state", settings.CHARGER_SOURCE_TOPIC, settings.CHARGER_SOURCE_OPTIONS),
]

# (object_id, name, state_topic, command_topic, minimum, maximum, step, unit)
NUMBERS = [
    ("discharge_stop_soc", "Battery Discharge Stop SOC", f"{settings.BASE_TOPIC}/battery/discharge_stop_soc/state", settings.DISCHARGE_STOP_SOC_TOPIC, 10, 50, 1, "%"),
    ("discharge_resume_soc", "Battery Discharge Resume SOC", f"{settings.BASE_TOPIC}/battery/discharge_resume_soc/state", settings.DISCHARGE_RESUME_SOC_TOPIC, 50, 100, 1, "%"),
]


class HomeAssistantDiscovery:
    """Publishes retained MQTT discovery configs so Home Assistant creates entities."""

    def __init__(self, mqtt_client):
        self._mqtt_client = mqtt_client

    def publish_all(self):
        self._publish_measurement_sensors()
        self._publish_energy_sensors()
        self._publish_text_sensors()
        self._publish_binary_sensors()
        self._publish_selects()
        self._publish_numbers()

    def _publish_config(self, component, object_id, entity_config):
        entity_config["unique_id"] = f"{settings.UNIQUE_ID_PREFIX}_{object_id}"
        entity_config["availability"] = AVAILABILITY
        entity_config["device"] = DEVICE_INFO
        config_topic = f"{settings.DISCOVERY_PREFIX}/{component}/{settings.DEVICE_ID}/{object_id}/config"
        self._mqtt_client.publish(config_topic, json.dumps(entity_config), retain=True)

    def _publish_measurement_sensors(self):
        for object_id, name, state_topic, unit, device_class in MEASUREMENT_SENSORS:
            self._publish_config("sensor", object_id, {
                "name": name,
                "state_topic": state_topic,
                "unit_of_measurement": unit,
                "device_class": device_class,
                "state_class": "measurement",
            })

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
                "options": list(options),
            })

    def _publish_numbers(self):
        for object_id, name, state_topic, command_topic, minimum, maximum, step, unit in NUMBERS:
            self._publish_config("number", object_id, {
                "name": name,
                "state_topic": state_topic,
                "command_topic": command_topic,
                "min": minimum,
                "max": maximum,
                "step": step,
                "unit_of_measurement": unit,
            })
