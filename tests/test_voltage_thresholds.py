from inverter.voltage_thresholds import BatteryVoltageThresholds, HOLD_BACK_TO_GRID_V, HOLD_BACK_TO_BATTERY_V


def create_thresholds():
    return BatteryVoltageThresholds(back_to_grid_v=50.0, back_to_battery_v=52.0)


class TestDesiredThresholds:

    def test_user_values_without_hold(self):
        assert create_thresholds().desired(holds_load_on_grid=False) == (50.0, 52.0)

    def test_hold_values_with_hold(self):
        assert create_thresholds().desired(holds_load_on_grid=True) == (HOLD_BACK_TO_GRID_V, HOLD_BACK_TO_BATTERY_V)
        assert (HOLD_BACK_TO_GRID_V, HOLD_BACK_TO_BATTERY_V) == (51.0, 58.0)


class TestBackToGridRejection:

    def test_accepts_valid_value(self):
        assert create_thresholds().back_to_grid_rejection(49.5, holds_load_on_grid=False) is None

    def test_locked_while_held(self):
        assert "locked" in create_thresholds().back_to_grid_rejection(49.5, holds_load_on_grid=True)

    def test_rejects_below_bms_cut_off(self):
        assert create_thresholds().back_to_grid_rejection(45.0, holds_load_on_grid=False) is not None

    def test_rejects_too_close_to_back_to_battery(self):
        assert create_thresholds().back_to_grid_rejection(50.5, holds_load_on_grid=False) is not None


class TestBackToBatteryRejection:

    def test_accepts_valid_value(self):
        assert create_thresholds().back_to_battery_rejection(54.0, holds_load_on_grid=False) is None

    def test_locked_while_held(self):
        assert "locked" in create_thresholds().back_to_battery_rejection(54.0, holds_load_on_grid=True)

    def test_rejects_value_that_never_returns_to_battery(self):
        assert create_thresholds().back_to_battery_rejection(58.0, holds_load_on_grid=False) is not None

    def test_rejects_too_close_to_back_to_grid(self):
        assert create_thresholds().back_to_battery_rejection(51.5, holds_load_on_grid=False) is not None
