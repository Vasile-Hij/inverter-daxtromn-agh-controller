from inverter.battery_mode import (
    BatteryMode, BATTERY_MODES, BATTERY_MODE_DEFAULT, NO_BATTERY_CONFIRM_CYCLES, PV_SURPLUS_CONFIRM_CYCLES,
    QUICK_GRID_RESUME_MARGIN_PCT, STATE_SETTINGS,
)


def create_battery_mode(mode_name=BATTERY_MODE_DEFAULT):
    mode = BatteryMode(low_battery_protection_soc_pct=16, grid_stop_charging_soc_pct=55, grid_quick_charge_soc_pct=80)
    mode.select(mode_name)
    return mode


def update(mode, soc, pv_power_w=0, load_power_w=500):
    return mode.update(soc, battery_present=True, bms_available=True, pv_power_w=pv_power_w, load_power_w=load_power_w)


def confirm_no_battery(mode):
    result = None
    for _ in range(NO_BATTERY_CONFIRM_CYCLES):
        result = mode.update(0, battery_present=False, bms_available=False) or result
    return result


def confirm_pv_surplus(mode, soc):
    for _ in range(PV_SURPLUS_CONFIRM_CYCLES):
        update(mode, soc, pv_power_w=2000, load_power_w=500)


def assert_on_grid_charging(mode):
    assert (mode.desired_output_priority, mode.desired_charger_source) == ("SUB", "grid_charging")
    assert mode.holds_load_on_grid is True
    assert mode.is_grid_charging_wanted is True


def assert_on_battery(mode, charger_source):
    assert (mode.desired_output_priority, mode.desired_charger_source) == ("SBU", charger_source)
    assert mode.holds_load_on_grid is False
    assert mode.is_grid_charging_wanted is False


class TestModeSelection:

    def test_three_modes_default_normal(self):
        assert BATTERY_MODES == ("normal", "economy", "quick_grid")
        assert BATTERY_MODE_DEFAULT == "normal"

    def test_rejects_old_mode_names(self):
        mode = create_battery_mode()
        for old_name in ("auto", "solar_only", "solar_and_grid", "grid_quick_charge", "eco"):
            assert mode.select(old_name) is False
        assert mode.selected_mode == "normal"

    def test_every_on_grid_state_uses_sub_and_holds_programs_12_13(self):
        for state_settings in STATE_SETTINGS.values():
            assert (state_settings["output_priority"] == "SUB") == state_settings["hold_load_on_grid"]

    def test_only_pcp01_grid_charges(self):
        for state_settings in STATE_SETTINGS.values():
            if state_settings["grid_charging"]:
                assert state_settings["charger_source"] == "grid_charging"


class TestNormalMode:

    def test_house_on_battery_above_low_battery_protection(self):
        mode = create_battery_mode("normal")
        assert update(mode, 17) is None
        assert mode.state == "normal_battery"
        assert_on_battery(mode, "grid_charging")

    def test_low_battery_moves_house_to_grid_and_grid_charges(self):
        mode = create_battery_mode("normal")
        assert update(mode, 16) is not None
        assert mode.state == "normal_grid"
        assert_on_grid_charging(mode)
        assert mode.is_low_battery_active is True

    def test_keeps_grid_charging_below_grid_stop(self):
        mode = create_battery_mode("normal")
        update(mode, 10)
        assert update(mode, 54) is None
        assert mode.state == "normal_grid"

    def test_grid_stop_returns_house_to_battery(self):
        mode = create_battery_mode("normal")
        update(mode, 10)
        assert update(mode, 55) is not None
        assert mode.state == "normal_battery"


class TestEconomyMode:

    def test_never_charges_from_grid(self):
        mode = create_battery_mode("economy")
        update(mode, 10)
        assert mode.never_charges_from_grid is True
        assert mode.is_grid_charging_wanted is False

    def test_low_battery_moves_house_to_grid_battery_resting(self):
        mode = create_battery_mode("economy")
        update(mode, 16)
        assert mode.state == "economy_grid"
        assert (mode.desired_output_priority, mode.desired_charger_source) == ("SUB", "no_grid_charging")
        assert mode.holds_load_on_grid is True

    def test_stays_on_grid_while_pv_below_house_consumption(self):
        mode = create_battery_mode("economy")
        update(mode, 10)
        for _ in range(PV_SURPLUS_CONFIRM_CYCLES * 2):
            update(mode, 10, pv_power_w=400, load_power_w=500)
        assert mode.state == "economy_grid"

    def test_pv_surplus_returns_house_to_battery(self):
        mode = create_battery_mode("economy")
        update(mode, 10)
        confirm_pv_surplus(mode, 10)
        assert mode.state == "economy_battery"
        assert_on_battery(mode, "no_grid_charging")

    def test_short_pv_surplus_does_not_move_house(self):
        mode = create_battery_mode("economy")
        update(mode, 10)
        for _ in range(PV_SURPLUS_CONFIRM_CYCLES - 1):
            update(mode, 10, pv_power_w=2000, load_power_w=500)
        assert mode.state == "economy_grid"

    def test_low_battery_with_pv_surplus_stays_on_battery(self):
        mode = create_battery_mode("economy")
        confirm_pv_surplus(mode, 30)
        update(mode, 12, pv_power_w=2000, load_power_w=500)
        assert mode.state == "economy_battery"


class TestQuickGridMode:

    def test_grid_charges_below_target(self):
        mode = create_battery_mode("quick_grid")
        assert update(mode, 79) is not None
        assert mode.state == "quick_grid_grid"
        assert_on_grid_charging(mode)
        assert mode.is_low_battery_active is False

    def test_target_moves_house_to_battery_without_grid_charging(self):
        mode = create_battery_mode("quick_grid")
        update(mode, 50)
        assert update(mode, 80) is not None
        assert mode.state == "quick_grid_battery"
        assert_on_battery(mode, "no_grid_charging")

    def test_resumes_grid_charging_below_resume_margin(self):
        mode = create_battery_mode("quick_grid")
        update(mode, 80)
        assert update(mode, 80 - QUICK_GRID_RESUME_MARGIN_PCT + 1) is None
        assert mode.state == "quick_grid_battery"
        update(mode, 80 - QUICK_GRID_RESUME_MARGIN_PCT)
        assert mode.state == "quick_grid_grid"


class TestModeChange:

    def test_selecting_another_mode_decides_again_from_soc(self):
        mode = create_battery_mode("quick_grid")
        update(mode, 40)
        mode.select("normal")
        update(mode, 40)
        assert mode.state == "normal_battery"

    def test_select_decides_immediately_without_passing_through_battery(self):
        mode = create_battery_mode("normal")
        update(mode, 10)
        mode.select("quick_grid")
        assert mode.state == "quick_grid_grid"
        assert mode.desired_output_priority == "SUB"

    def test_reselecting_same_mode_keeps_state(self):
        mode = create_battery_mode("normal")
        update(mode, 10)
        mode.select("normal")
        assert mode.state == "normal_grid"


class TestNoBattery:

    def test_first_reading_without_battery_decides_immediately(self):
        mode = create_battery_mode()
        assert mode.update(0, battery_present=False, bms_available=False) is not None
        assert mode.state == "no_battery"
        assert mode.desired_output_priority == "SUB"
        assert mode.is_grid_charging_wanted is False

    def test_battery_return_is_debounced(self):
        mode = create_battery_mode()
        confirm_no_battery(mode)
        for _ in range(NO_BATTERY_CONFIRM_CYCLES - 1):
            update(mode, 50)
        assert mode.state == "no_battery"
        update(mode, 50)
        assert mode.state == "normal_battery"


class TestInverterProtection:

    def test_bms_offline_fallback_moves_normal_to_grid(self):
        mode = create_battery_mode("normal")
        update(mode, 40)
        mode.accept_inverter_protection()
        assert mode.state == "normal_grid"

    def test_quick_grid_ignores_inverter_protection(self):
        mode = create_battery_mode("quick_grid")
        update(mode, 80)
        mode.accept_inverter_protection()
        assert mode.state == "quick_grid_battery"
