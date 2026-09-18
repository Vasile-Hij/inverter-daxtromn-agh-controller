from inverter.discharge_guard import BatteryDischargeGuard


class TestBatteryDischargeGuard:

    def test_initial_mode_is_force_sbu(self):
        guard = BatteryDischargeGuard(stop_soc_pct=10, resume_soc_pct=50)
        assert guard.mode == "force_sbu"

    def test_decide_sbu_when_force_sbu(self):
        guard = BatteryDischargeGuard(stop_soc_pct=10, resume_soc_pct=50)
        assert guard.decide() == "SBU"

    def test_decide_sub_when_force_sub(self):
        guard = BatteryDischargeGuard(stop_soc_pct=10, resume_soc_pct=50)
        guard.mode = "force_sub"
        assert guard.decide() == "SUB"

    def test_low_soc_triggers_force_sub(self):
        guard = BatteryDischargeGuard(stop_soc_pct=10, resume_soc_pct=50)
        result = guard.update_auto_protection(
            estimated_soc_pct=7, battery_present=True, bms_available=True,
        )
        assert result == "force_sub"
        assert guard.mode == "force_sub"
        assert guard.decide() == "SUB"

    def test_soc_above_stop_does_not_trigger(self):
        guard = BatteryDischargeGuard(stop_soc_pct=10, resume_soc_pct=50)
        result = guard.update_auto_protection(
            estimated_soc_pct=50, battery_present=True, bms_available=True,
        )
        assert result is None
        assert guard.mode == "force_sbu"

    def test_resume_after_auto_protection(self):
        guard = BatteryDischargeGuard(stop_soc_pct=10, resume_soc_pct=50)
        guard.update_auto_protection(
            estimated_soc_pct=5, battery_present=True, bms_available=True,
        )
        assert guard.mode == "force_sub"
        result = guard.update_auto_protection(
            estimated_soc_pct=55, battery_present=True, bms_available=True,
        )
        assert result == "force_sbu"
        assert guard.mode == "force_sbu"

    def test_no_resume_below_threshold(self):
        guard = BatteryDischargeGuard(stop_soc_pct=10, resume_soc_pct=50)
        guard.update_auto_protection(
            estimated_soc_pct=5, battery_present=True, bms_available=True,
        )
        result = guard.update_auto_protection(
            estimated_soc_pct=30, battery_present=True, bms_available=True,
        )
        assert result is None
        assert guard.mode == "force_sub"

    def test_no_battery_no_bms_forces_sub(self):
        guard = BatteryDischargeGuard(stop_soc_pct=10, resume_soc_pct=50)
        result = guard.update_auto_protection(
            estimated_soc_pct=80, battery_present=False, bms_available=False,
        )
        assert result == "force_sub"

    def test_inverter_fallback_with_margin(self):
        guard = BatteryDischargeGuard(stop_soc_pct=10, resume_soc_pct=50)
        result = guard.update_auto_protection(
            estimated_soc_pct=50, battery_present=True,
            inverter_capacity_pct=18, bms_available=False,
        )
        assert result == "force_sub"

    def test_inverter_fallback_above_margin_no_trigger(self):
        guard = BatteryDischargeGuard(stop_soc_pct=10, resume_soc_pct=50)
        result = guard.update_auto_protection(
            estimated_soc_pct=50, battery_present=True,
            inverter_capacity_pct=25, bms_available=False,
        )
        assert result is None

    def test_accept_inverter_protection(self):
        guard = BatteryDischargeGuard(stop_soc_pct=10, resume_soc_pct=50)
        guard.accept_inverter_protection()
        assert guard.mode == "force_sub"
        assert guard.decide() == "SUB"

    def test_clear_auto_protection_prevents_resume(self):
        guard = BatteryDischargeGuard(stop_soc_pct=10, resume_soc_pct=50)
        guard.update_auto_protection(
            estimated_soc_pct=5, battery_present=True, bms_available=True,
        )
        guard.clear_auto_protection()
        result = guard.update_auto_protection(
            estimated_soc_pct=80, battery_present=True, bms_available=True,
        )
        assert result is None
