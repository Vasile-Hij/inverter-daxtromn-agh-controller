from inverter.battery_mode import BatteryMode, BATTERY_MODE_DEFAULT


class TestBatteryModeSelection:

    def test_initial_mode_is_battery_savings(self):
        mode = BatteryMode(stop_soc_pct=10, resume_soc_pct=50)
        assert mode.selected_mode == "battery_savings"

    def test_select_valid_mode(self):
        mode = BatteryMode(stop_soc_pct=10, resume_soc_pct=50)
        assert mode.select("battery_quick_charge") is True
        assert mode.selected_mode == "battery_quick_charge"

    def test_select_invalid_mode(self):
        mode = BatteryMode(stop_soc_pct=10, resume_soc_pct=50)
        assert mode.select("invalid") is False
        assert mode.selected_mode == BATTERY_MODE_DEFAULT

    def test_select_clears_low_battery(self):
        mode = BatteryMode(stop_soc_pct=10, resume_soc_pct=50)
        mode.update(5, battery_present=True, pv_power_w=0, bms_available=True)
        assert mode.is_low_battery_active is True
        mode.select("battery_charge_slow")
        assert mode.is_low_battery_active is False


class TestBatteryModeSettings:

    def test_battery_savings_output_priority(self):
        mode = BatteryMode(stop_soc_pct=10, resume_soc_pct=50)
        assert mode.desired_output_priority == "SBU"

    def test_battery_savings_charger_source(self):
        mode = BatteryMode(stop_soc_pct=10, resume_soc_pct=50)
        assert mode.desired_charger_source == "solar_only"

    def test_battery_charge_slow_settings(self):
        mode = BatteryMode(stop_soc_pct=10, resume_soc_pct=50)
        mode.select("battery_charge_slow")
        assert mode.desired_output_priority == "SUB"
        assert mode.desired_charger_source == "solar_first"

    def test_battery_quick_charge_settings(self):
        mode = BatteryMode(stop_soc_pct=10, resume_soc_pct=50)
        mode.select("battery_quick_charge")
        assert mode.desired_output_priority == "USB"
        assert mode.desired_charger_source == "solar_and_utility"


class TestLowBatteryProtection:

    def test_low_soc_forces_sub_solar_only(self):
        mode = BatteryMode(stop_soc_pct=10, resume_soc_pct=50)
        result = mode.update(7, battery_present=True, pv_power_w=0, bms_available=True)
        assert result is not None
        assert mode.desired_output_priority == "SUB"
        assert mode.desired_charger_source == "solar_only"

    def test_soc_above_stop_no_trigger(self):
        mode = BatteryMode(stop_soc_pct=10, resume_soc_pct=50)
        result = mode.update(50, battery_present=True, pv_power_w=0, bms_available=True)
        assert result is None
        assert mode.desired_output_priority == "SBU"

    def test_recovery_restores_selected_mode(self):
        mode = BatteryMode(stop_soc_pct=10, resume_soc_pct=50)
        mode.update(5, battery_present=True, pv_power_w=0, bms_available=True)
        assert mode.desired_output_priority == "SUB"
        result = mode.update(55, battery_present=True, pv_power_w=0, bms_available=True)
        assert result is not None
        assert mode.desired_output_priority == "SBU"
        assert mode.desired_charger_source == "solar_only"

    def test_no_recovery_below_resume_threshold(self):
        mode = BatteryMode(stop_soc_pct=10, resume_soc_pct=50)
        mode.update(5, battery_present=True, pv_power_w=0, bms_available=True)
        result = mode.update(30, battery_present=True, pv_power_w=0, bms_available=True)
        assert result is None
        assert mode.desired_output_priority == "SUB"

    def test_no_battery_no_bms_forces_sub(self):
        mode = BatteryMode(stop_soc_pct=10, resume_soc_pct=50)
        result = mode.update(80, battery_present=False, pv_power_w=0, bms_available=False)
        assert result is not None
        assert mode.desired_output_priority == "SUB"
        assert mode.desired_charger_source == "solar_only"

    def test_inverter_fallback_with_margin(self):
        mode = BatteryMode(stop_soc_pct=10, resume_soc_pct=50)
        result = mode.update(
            50, battery_present=True, pv_power_w=0,
            inverter_capacity_pct=18, bms_available=False,
        )
        assert result is not None
        assert mode.desired_output_priority == "SUB"

    def test_inverter_fallback_above_margin_no_trigger(self):
        mode = BatteryMode(stop_soc_pct=10, resume_soc_pct=50)
        result = mode.update(
            50, battery_present=True, pv_power_w=0,
            inverter_capacity_pct=25, bms_available=False,
        )
        assert result is None

    def test_accept_inverter_protection(self):
        mode = BatteryMode(stop_soc_pct=10, resume_soc_pct=50)
        mode.accept_inverter_protection()
        assert mode.is_low_battery_active is True
        assert mode.desired_output_priority == "SUB"

    def test_low_battery_stays_solar_only_charger(self):
        mode = BatteryMode(stop_soc_pct=10, resume_soc_pct=50)
        mode.select("battery_quick_charge")
        mode.update(5, battery_present=True, pv_power_w=0, bms_available=True)
        assert mode.desired_charger_source == "solar_only"


class TestQuickChargeAutoSwitch:

    def test_switches_to_savings_above_51_with_pv(self):
        mode = BatteryMode(stop_soc_pct=10, resume_soc_pct=50)
        mode.select("battery_quick_charge")
        result = mode.update(55, battery_present=True, pv_power_w=100, bms_available=True)
        assert result is not None
        assert mode.selected_mode == "battery_savings"
        assert mode.desired_output_priority == "SBU"
        assert mode.desired_charger_source == "solar_only"

    def test_no_switch_below_51(self):
        mode = BatteryMode(stop_soc_pct=10, resume_soc_pct=50)
        mode.select("battery_quick_charge")
        result = mode.update(45, battery_present=True, pv_power_w=100, bms_available=True)
        assert result is None
        assert mode.selected_mode == "battery_quick_charge"

    def test_no_switch_without_pv(self):
        mode = BatteryMode(stop_soc_pct=10, resume_soc_pct=50)
        mode.select("battery_quick_charge")
        result = mode.update(55, battery_present=True, pv_power_w=0, bms_available=True)
        assert result is None
        assert mode.selected_mode == "battery_quick_charge"

    def test_no_switch_with_pv_below_threshold(self):
        mode = BatteryMode(stop_soc_pct=10, resume_soc_pct=50)
        mode.select("battery_quick_charge")
        result = mode.update(55, battery_present=True, pv_power_w=5, bms_available=True)
        assert result is None
        assert mode.selected_mode == "battery_quick_charge"

    def test_no_switch_for_savings_mode(self):
        mode = BatteryMode(stop_soc_pct=10, resume_soc_pct=50)
        result = mode.update(55, battery_present=True, pv_power_w=100, bms_available=True)
        assert result is None
        assert mode.selected_mode == "battery_savings"

    def test_no_switch_for_charge_slow_mode(self):
        mode = BatteryMode(stop_soc_pct=10, resume_soc_pct=50)
        mode.select("battery_charge_slow")
        result = mode.update(55, battery_present=True, pv_power_w=100, bms_available=True)
        assert result is None
        assert mode.selected_mode == "battery_charge_slow"

    def test_no_switch_during_low_battery(self):
        mode = BatteryMode(stop_soc_pct=10, resume_soc_pct=50)
        mode.select("battery_quick_charge")
        mode.update(5, battery_present=True, pv_power_w=0, bms_available=True)
        assert mode.is_low_battery_active is True
        result = mode.update(55, battery_present=True, pv_power_w=100, bms_available=True)
        assert "recovered" in result
        assert mode.selected_mode == "battery_quick_charge"

    def test_switch_at_exactly_51_does_not_trigger(self):
        mode = BatteryMode(stop_soc_pct=10, resume_soc_pct=50)
        mode.select("battery_quick_charge")
        result = mode.update(51, battery_present=True, pv_power_w=100, bms_available=True)
        assert result is None
        assert mode.selected_mode == "battery_quick_charge"

    def test_manual_override_switch_soc_threshold(self):
        mode = BatteryMode(stop_soc_pct=10, resume_soc_pct=50)
        mode.select("battery_quick_charge")
        mode.quick_charge_switch_soc_pct = 80
        result = mode.update(55, battery_present=True, pv_power_w=100, bms_available=True)
        assert result is None
        assert mode.selected_mode == "battery_quick_charge"
        result = mode.update(85, battery_present=True, pv_power_w=100, bms_available=True)
        assert result is not None
        assert mode.selected_mode == "battery_savings"

    def test_manual_override_stop_soc_persists_through_mode_change(self):
        mode = BatteryMode(stop_soc_pct=10, resume_soc_pct=50)
        mode.stop_soc_pct = 25
        mode.select("battery_charge_slow")
        assert mode.stop_soc_pct == 25

    def test_manual_override_resume_soc_persists_through_mode_change(self):
        mode = BatteryMode(stop_soc_pct=10, resume_soc_pct=50)
        mode.resume_soc_pct = 70
        mode.select("battery_quick_charge")
        assert mode.resume_soc_pct == 70
