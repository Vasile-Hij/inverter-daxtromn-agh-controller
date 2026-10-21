"""Tests for _apply_charger_source: battery mode, BMS fallback, and MCB lockout combined."""

import os
from unittest.mock import MagicMock

os.environ.setdefault("MQTT_HOST", "127.0.0.1")
os.environ.setdefault("MQTT_PORT", "1883")
os.environ.setdefault("MQTT_USER", "test")
os.environ.setdefault("MQTT_PASSWORD", "test")

from grid_limiter import GridLimiter
from inverter.battery_mode import BatteryMode
from solar_monitor import SolarMonitor


def make_monitor(selected_mode="auto"):
    monitor = MagicMock(spec=SolarMonitor)
    monitor.battery_mode = BatteryMode(16, 55, 80)
    monitor.battery_mode.select(selected_mode)
    monitor.grid_limiter = GridLimiter(32, (1800, 3600, 7200))
    monitor._bms_offline_fallback_active = False
    monitor.last_applied_charger_source = None
    monitor.inverter = MagicMock()
    monitor.inverter.set_charger_source.return_value = True
    monitor._apply_charger_source = SolarMonitor._apply_charger_source.__get__(monitor)
    return monitor


def enter_low_battery_protection(monitor):
    monitor.battery_mode.update(10, battery_present=True, bms_available=True)


class TestMcbLockoutOverridesMode:

    def test_lockout_stops_solar_first_grid_charging(self):
        monitor = make_monitor()
        enter_low_battery_protection(monitor)
        monitor.grid_limiter.update(35, True, 100)
        monitor._apply_charger_source()
        assert monitor.last_applied_charger_source == "solar_only"
        monitor.inverter.set_charger_source.assert_called_with("PCP03")

    def test_lockout_stops_solar_and_grid_mode(self):
        monitor = make_monitor("solar_and_grid")
        monitor.grid_limiter.update(35, True, 100)
        monitor._apply_charger_source()
        assert monitor.last_applied_charger_source == "solar_only"

    def test_lockout_stops_bms_offline_fallback(self):
        monitor = make_monitor()
        monitor._bms_offline_fallback_active = True
        monitor.grid_limiter.update(35, True, 100)
        monitor._apply_charger_source()
        assert monitor.last_applied_charger_source == "solar_only"

    def test_no_lockout_keeps_desired_grid_charging(self):
        monitor = make_monitor()
        enter_low_battery_protection(monitor)
        monitor._apply_charger_source()
        assert monitor.last_applied_charger_source == "solar_first"


class TestLockoutRepeatReset:

    def test_grid_charging_no_longer_wanted_resets_repeats(self):
        monitor = make_monitor()
        monitor.grid_limiter.update(35, True, 100)
        monitor._apply_charger_source()
        assert monitor.grid_limiter.lockout_count == 0

    def test_repeats_kept_while_grid_charging_is_wanted(self):
        monitor = make_monitor()
        enter_low_battery_protection(monitor)
        monitor.grid_limiter.update(35, True, 100)
        monitor._apply_charger_source()
        assert monitor.grid_limiter.lockout_count == 1
