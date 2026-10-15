from inverter.battery_mode import BatteryMode, BATTERY_MODES, BATTERY_MODE_DEFAULT, NO_BATTERY_CONFIRM_CYCLES


def confirm_no_battery(mode):
    result = None
    for _ in range(NO_BATTERY_CONFIRM_CYCLES):
        result = mode.update(0, battery_present=False, bms_available=False) or result
    return result


def create_battery_mode():
    return BatteryMode(
        low_battery_protection_soc_pct=10,
        grid_stop_charging_soc_pct=30,
        grid_quick_charge_soc_pct=90,
    )


class TestModeSelection:

    def test_selectable_modes_are_auto_and_manual(self):
        assert BATTERY_MODES == ("auto", "manual")

    def test_default_is_auto_normal(self):
        mode = create_battery_mode()
        assert mode.selected_mode == BATTERY_MODE_DEFAULT == "auto"
        assert mode.state == "auto_normal"

    def test_select_invalid_mode_is_rejected(self):
        mode = create_battery_mode()
        assert mode.select("battery_savings") is False
        assert mode.selected_mode == "auto"

    def test_reselecting_auto_keeps_low_battery(self):
        mode = create_battery_mode()
        mode.update(5, battery_present=True, bms_available=True)
        mode.select("auto")
        assert mode.is_low_battery_active is True

    def test_select_clears_low_battery(self):
        mode = create_battery_mode()
        mode.update(5, battery_present=True, bms_available=True)
        mode.select("manual")
        mode.select("auto")
        assert mode.is_low_battery_active is False

    def test_select_clears_no_battery(self):
        mode = create_battery_mode()
        confirm_no_battery(mode)
        mode.select("auto")
        assert mode.is_no_battery_active is True
        mode.select("manual")
        assert mode.is_no_battery_active is False


class TestAutoMode:

    def test_normal_is_sbu_solar_only(self):
        mode = create_battery_mode()
        assert mode.desired_output_priority == "SBU"
        assert mode.desired_charger_source == "solar_only"
        assert mode.status_description == "auto: normal (SBU + solar_only)"

    def test_low_battery_protection_keeps_sbu_adds_grid_charging(self):
        mode = create_battery_mode()
        assert mode.update(10, battery_present=True, bms_available=True) is not None
        assert mode.state == "auto_low_battery"
        assert mode.desired_output_priority == "SBU"
        assert mode.desired_charger_source == "solar_first"
        assert mode.status_description == "auto: low battery protection (SBU + solar_first)"

    def test_low_battery_protection_holds_load_on_grid(self):
        mode = create_battery_mode()
        assert mode.holds_load_on_grid is False
        mode.update(10, battery_present=True, bms_available=True)
        assert mode.holds_load_on_grid is True

    def test_grid_stop_charging_releases_load_from_grid(self):
        mode = create_battery_mode()
        mode.update(8, battery_present=True, bms_available=True)
        mode.update(30, battery_present=True, bms_available=True)
        assert mode.holds_load_on_grid is False

    def test_only_low_battery_protection_holds_load_on_grid(self):
        mode = create_battery_mode()
        confirm_no_battery(mode)
        assert mode.holds_load_on_grid is False
        mode.select("manual")
        assert mode.holds_load_on_grid is False

    def test_above_low_battery_protection_stays_normal(self):
        mode = create_battery_mode()
        assert mode.update(11, battery_present=True, bms_available=True) is None
        assert mode.state == "auto_normal"

    def test_stays_protected_below_grid_stop_charging(self):
        mode = create_battery_mode()
        mode.update(8, battery_present=True, bms_available=True)
        assert mode.update(29, battery_present=True, bms_available=True) is None
        assert mode.state == "auto_low_battery"

    def test_grid_stop_charging_returns_to_sbu_solar_only(self):
        mode = create_battery_mode()
        mode.update(8, battery_present=True, bms_available=True)
        assert mode.update(30, battery_present=True, bms_available=True) is not None
        assert mode.state == "auto_normal"
        assert mode.desired_output_priority == "SBU"
        assert mode.desired_charger_source == "solar_only"

    def test_no_battery_keeps_sbu_adds_grid_charging(self):
        mode = create_battery_mode()
        result = confirm_no_battery(mode)
        assert result is not None
        assert mode.state == "auto_no_battery"
        assert mode.desired_output_priority == "SBU"
        assert mode.desired_charger_source == "solar_and_utility"

    def test_no_battery_stays_in_no_battery(self):
        mode = create_battery_mode()
        confirm_no_battery(mode)
        assert mode.update(0, battery_present=False, bms_available=False) is None
        assert mode.state == "auto_no_battery"

    def test_battery_returns_from_no_battery(self):
        mode = create_battery_mode()
        confirm_no_battery(mode)
        for _ in range(NO_BATTERY_CONFIRM_CYCLES):
            result = mode.update(50, battery_present=True, bms_available=True) or None
        assert result is not None
        assert "battery returned" in result
        assert mode.state == "auto_normal"

    def test_inverter_capacity_fallback_uses_safety_margin(self):
        mode = create_battery_mode()
        mode.update(50, battery_present=True, inverter_capacity_pct=20, bms_available=False)
        assert mode.state == "auto_low_battery"

    def test_inverter_capacity_above_margin_stays_normal(self):
        mode = create_battery_mode()
        mode.update(50, battery_present=True, inverter_capacity_pct=21, bms_available=False)
        assert mode.state == "auto_normal"

    def test_accept_inverter_protection(self):
        mode = create_battery_mode()
        mode.accept_inverter_protection()
        assert mode.state == "auto_low_battery"
        assert mode.desired_output_priority == "SBU"
        assert mode.desired_charger_source == "solar_first"


class TestManualMode:

    def test_grid_quick_charge_is_sbu_solar_and_utility(self):
        mode = create_battery_mode()
        mode.select("manual")
        assert mode.state == "manual_grid_charging"
        assert mode.desired_output_priority == "SBU"
        assert mode.desired_charger_source == "solar_and_utility"
        assert mode.status_description == "manual: grid quick charge (SBU + solar_and_utility)"

    def test_keeps_grid_charging_below_target(self):
        mode = create_battery_mode()
        mode.select("manual")
        assert mode.update(89, battery_present=True, bms_available=True) is None
        assert mode.state == "manual_grid_charging"

    def test_target_reached_holds_sbu_solar_only(self):
        mode = create_battery_mode()
        mode.select("manual")
        assert mode.update(90, battery_present=True, bms_available=True) is not None
        assert mode.selected_mode == "manual"
        assert mode.state == "manual_charged"
        assert mode.desired_output_priority == "SBU"
        assert mode.desired_charger_source == "solar_only"
        assert mode.status_description == "manual: charged, holding (SBU + solar_only)"

    def test_charged_does_not_restart_grid_charging_when_soc_drops(self):
        mode = create_battery_mode()
        mode.select("manual")
        mode.update(90, battery_present=True, bms_available=True)
        assert mode.update(80, battery_present=True, bms_available=True) is None
        assert mode.state == "manual_charged"

    def test_low_soc_does_not_interrupt_grid_charging(self):
        mode = create_battery_mode()
        mode.select("manual")
        assert mode.update(5, battery_present=True, bms_available=True) is None
        assert mode.state == "manual_grid_charging"
        assert mode.is_low_battery_active is False

    def test_inverter_protection_ignored_in_manual(self):
        mode = create_battery_mode()
        mode.select("manual")
        mode.accept_inverter_protection()
        assert mode.state == "manual_grid_charging"

    def test_reselecting_manual_restarts_grid_charging(self):
        mode = create_battery_mode()
        mode.select("manual")
        mode.update(90, battery_present=True, bms_available=True)
        mode.select("manual")
        assert mode.state == "manual_grid_charging"

    def test_selecting_auto_leaves_manual(self):
        mode = create_battery_mode()
        mode.select("manual")
        mode.update(90, battery_present=True, bms_available=True)
        mode.select("auto")
        assert mode.state == "auto_normal"


class TestThresholdChanges:

    def test_low_battery_protection_change_applies(self):
        mode = create_battery_mode()
        mode.low_battery_protection_soc_pct = 25
        mode.update(25, battery_present=True, bms_available=True)
        assert mode.state == "auto_low_battery"

    def test_grid_quick_charge_change_applies(self):
        mode = create_battery_mode()
        mode.grid_quick_charge_soc_pct = 80
        mode.select("manual")
        mode.update(80, battery_present=True, bms_available=True)
        assert mode.state == "manual_charged"


class TestNoBatteryDebounce:
    def test_first_reading_decides_immediately(self):
        mode = create_battery_mode()
        assert mode.update(0, battery_present=False, bms_available=False) is not None
        assert mode.is_no_battery_active

    def test_brief_absence_does_not_switch(self):
        mode = create_battery_mode()
        mode.update(50, battery_present=True, bms_available=False)
        for _ in range(NO_BATTERY_CONFIRM_CYCLES - 1):
            assert mode.update(0, battery_present=False, bms_available=False) is None
        assert mode.update(0, battery_present=True, bms_available=False) is None
        assert not mode.is_no_battery_active

    def test_returned_battery_keeps_grid_charging(self):
        mode = create_battery_mode()
        confirm_no_battery(mode)
        assert mode.update(0, battery_present=True, bms_available=False) is None
        for _ in range(NO_BATTERY_CONFIRM_CYCLES - 1):
            mode.update(0, battery_present=True, bms_available=False)
        assert 'solar_first' in mode.status_description
