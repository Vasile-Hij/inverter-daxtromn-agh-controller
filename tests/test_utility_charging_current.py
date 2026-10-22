"""Tests for _desired_utility_charging_current_a: program 11 per battery mode state."""

import os
from unittest.mock import MagicMock

os.environ.setdefault("MQTT_HOST", "127.0.0.1")
os.environ.setdefault("MQTT_PORT", "1883")
os.environ.setdefault("MQTT_USER", "test")
os.environ.setdefault("MQTT_PASSWORD", "test")

from inverter.battery_mode import BatteryMode
from solar_monitor import SolarMonitor


def desired_amps(selected_mode, soc):
    monitor = MagicMock(spec=SolarMonitor)
    monitor.battery_mode = BatteryMode(16, 55, 80)
    monitor.battery_mode.select(selected_mode)
    monitor.battery_mode.update(soc, battery_present=True, bms_available=True)
    monitor.normal_grid_charging_current_a = 50
    monitor.quick_grid_charging_current_a = 90
    return SolarMonitor._desired_utility_charging_current_a(monitor)


class TestProgram11PerMode:

    def test_normal_grid_charging_uses_normal_current(self):
        assert desired_amps("normal", 10) == 50

    def test_quick_grid_charging_uses_quick_current(self):
        assert desired_amps("quick_grid", 40) == 90

    def test_economy_low_battery_runs_minimum(self):
        assert desired_amps("economy", 10) == 2

    def test_house_on_battery_runs_minimum(self):
        assert desired_amps("normal", 60) == 2
        assert desired_amps("quick_grid", 85) == 2
