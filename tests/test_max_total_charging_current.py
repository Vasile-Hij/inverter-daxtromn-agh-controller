"""Tests for _apply_max_total_charging_current: program 02 held at the BMS charge current limit."""

import os
from unittest.mock import MagicMock

os.environ.setdefault("MQTT_HOST", "127.0.0.1")
os.environ.setdefault("MQTT_PORT", "1883")
os.environ.setdefault("MQTT_USER", "test")
os.environ.setdefault("MQTT_PASSWORD", "test")

import settings
from solar_monitor import SolarMonitor


def apply_with_actual_amps(actual_amps):
    monitor = MagicMock(spec=SolarMonitor)
    monitor.inverter = MagicMock()
    monitor.inverter.query_max_total_charge_current.return_value = actual_amps
    SolarMonitor._apply_max_total_charging_current(monitor)
    return monitor.inverter.set_max_total_charge_current


class TestProgram02:

    def test_sets_limit_when_inverter_differs(self):
        set_command = apply_with_actual_amps(160)
        set_command.assert_called_once_with(settings.MAX_TOTAL_CHARGING_CURRENT_A)

    def test_leaves_inverter_alone_when_already_at_limit(self):
        apply_with_actual_amps(settings.MAX_TOTAL_CHARGING_CURRENT_A).assert_not_called()

    def test_leaves_inverter_alone_when_unreadable(self):
        apply_with_actual_amps(None).assert_not_called()

    def test_limit_is_the_bms_charge_current_limit(self):
        assert settings.MAX_TOTAL_CHARGING_CURRENT_A == 140
