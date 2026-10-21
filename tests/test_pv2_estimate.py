"""Tests for PV2 estimation: _estimate_total_pv_watts and _pv_total_from_ratio."""

import os
import sys
from unittest.mock import MagicMock

os.environ.setdefault("MQTT_HOST", "127.0.0.1")
os.environ.setdefault("MQTT_PORT", "1883")
os.environ.setdefault("MQTT_USER", "test")
os.environ.setdefault("MQTT_PASSWORD", "test")

import settings
from solar_monitor import SolarMonitor


def make_monitor(pv_efficiency=0.93, pv2_pv1_ratio=0.60):
    monitor = MagicMock(spec=SolarMonitor)
    monitor.pv_efficiency = pv_efficiency
    monitor.pv2_pv1_ratio = pv2_pv1_ratio
    monitor._is_grid_charging = SolarMonitor._is_grid_charging
    monitor._pv_total_from_ratio = SolarMonitor._pv_total_from_ratio.__get__(monitor)
    monitor._estimate_total_pv_watts = SolarMonitor._estimate_total_pv_watts.__get__(monitor)
    return monitor


def inverter_data(ac_output_w=2000, pv1_power_w=800, device_status="00000000"):
    return {
        "ac_output_power_w": ac_output_w,
        "pv1_power_w": pv1_power_w,
        "device_status": device_status,
    }


class TestGridActiveNotCharging:

    def test_sunny_day_grid_idle(self):
        monitor = make_monitor()
        data = inverter_data(ac_output_w=2000, pv1_power_w=800)
        total = monitor._estimate_total_pv_watts(data, battery_contribution_w=0, grid_power_w=3)
        assert total > 800

    def test_cloudy_day_grid_provides_most(self):
        monitor = make_monitor()
        data = inverter_data(ac_output_w=2000, pv1_power_w=30)
        total = monitor._estimate_total_pv_watts(data, battery_contribution_w=0, grid_power_w=1980)
        pv2 = max(total - 30, 0)
        assert pv2 < 50

    def test_grid_slightly_over_ac_output_does_not_inflate(self):
        """ZMAi reads slightly more than ac_output — PV2 must not explode."""
        monitor = make_monitor()
        data = inverter_data(ac_output_w=2000, pv1_power_w=10)
        total = monitor._estimate_total_pv_watts(data, battery_contribution_w=0, grid_power_w=2050)
        pv2 = max(total - 10, 0)
        assert pv2 < 50

    def test_battery_discharging_with_grid(self):
        monitor = make_monitor()
        data = inverter_data(ac_output_w=3000, pv1_power_w=500)
        total = monitor._estimate_total_pv_watts(data, battery_contribution_w=500, grid_power_w=1000)
        expected = (3000 - 1000) / 0.93 - 500
        assert abs(total - expected) < 1


class TestGridChargingBattery:

    def test_grid_charging_uses_ratio(self):
        """When grid charges battery, energy balance is skipped for ratio."""
        monitor = make_monitor()
        data = inverter_data(ac_output_w=2000, pv1_power_w=200, device_status="00000001")
        total = monitor._estimate_total_pv_watts(data, battery_contribution_w=-1560, grid_power_w=3500)
        expected_ratio = 200 * (1 + 0.60)
        assert abs(total - expected_ratio) < 1

    def test_grid_charging_low_pv1_returns_pv1(self):
        """PV1 below ratio threshold: total PV = PV1 only."""
        monitor = make_monitor()
        data = inverter_data(ac_output_w=1500, pv1_power_w=10, device_status="00000001")
        total = monitor._estimate_total_pv_watts(data, battery_contribution_w=-1000, grid_power_w=2500)
        assert total == 10

    def test_grid_charging_zmai_lag_no_inflation(self):
        """ZMAi lags behind (reads low) during grid charging — must not inflate PV2."""
        monitor = make_monitor()
        data = inverter_data(ac_output_w=2000, pv1_power_w=30, device_status="00000001")
        total = monitor._estimate_total_pv_watts(data, battery_contribution_w=-1560, grid_power_w=2500)
        assert total == 30

    def test_grid_charging_zero_pv1(self):
        monitor = make_monitor()
        data = inverter_data(ac_output_w=1000, pv1_power_w=0, device_status="00000001")
        total = monitor._estimate_total_pv_watts(data, battery_contribution_w=-800, grid_power_w=2000)
        assert total == 0


class TestGridOffline:

    def test_no_grid_data_uses_ac_output(self):
        monitor = make_monitor()
        data = inverter_data(ac_output_w=2000, pv1_power_w=800)
        total = monitor._estimate_total_pv_watts(data, battery_contribution_w=0, grid_power_w=None)
        expected = 2000 / 0.93
        assert abs(total - expected) < 1

    def test_no_grid_with_battery_discharge(self):
        monitor = make_monitor()
        data = inverter_data(ac_output_w=1500, pv1_power_w=600)
        total = monitor._estimate_total_pv_watts(data, battery_contribution_w=300, grid_power_w=None)
        expected = 1500 / 0.93 - 300
        assert abs(total - expected) < 1


class TestRatioFallback:

    def test_low_pv2_triggers_ratio(self):
        """When balance gives PV2 < 5% of PV1 and PV1 > 50W, use ratio."""
        monitor = make_monitor()
        data = inverter_data(ac_output_w=2000, pv1_power_w=800)
        grid_w = 2000 - 800 * 0.93 + 1
        total = monitor._estimate_total_pv_watts(data, battery_contribution_w=0, grid_power_w=grid_w)
        expected_ratio = 800 * (1 + 0.60)
        assert abs(total - expected_ratio) < 1

    def test_pv1_below_threshold_no_ratio(self):
        """PV1 below PV2_RATIO_MIN_PV1_W: ratio fallback does not apply."""
        monitor = make_monitor()
        data = inverter_data(ac_output_w=100, pv1_power_w=20)
        total = monitor._estimate_total_pv_watts(data, battery_contribution_w=0, grid_power_w=80)
        pv2 = max(total - 20, 0)
        assert pv2 < 30


class TestPvTotalFromRatio:

    def test_above_threshold(self):
        monitor = make_monitor()
        assert abs(monitor._pv_total_from_ratio(200) - 320) < 1

    def test_below_threshold(self):
        monitor = make_monitor()
        assert monitor._pv_total_from_ratio(30) == 30

    def test_zero(self):
        monitor = make_monitor()
        assert monitor._pv_total_from_ratio(0) == 0
