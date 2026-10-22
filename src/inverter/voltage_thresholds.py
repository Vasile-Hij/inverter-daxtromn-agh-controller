"""LCD programs 12 (back to grid) and 13 (back to battery) under SBU priority.

Battery mode is the global trigger: a mode that holds the load on grid drives 12/13 to the hold values,
otherwise the user's values apply. The user's values are local: they can only change while no mode
holds the load on grid, and only into a combination the inverter and battery can run.
"""

import settings

HOLD_BACK_TO_GRID_V = settings.BACK_TO_GRID_V_RANGE[1]
HOLD_BACK_TO_BATTERY_V = settings.BACK_TO_BATTERY_V_RANGE[1]


class BatteryVoltageThresholds:
    """Keeps the user's program 12/13 values and decides which pair the inverter should run."""

    def __init__(self, back_to_grid_v, back_to_battery_v):
        self.back_to_grid_v = back_to_grid_v
        self.back_to_battery_v = back_to_battery_v

    def desired(self, holds_load_on_grid):
        # SBU leaves the battery only below program 12 and stops utility charging at program 13,
        # so a hold raises 12 to its maximum and 13 above the BMS charge limit.
        if holds_load_on_grid:
            return HOLD_BACK_TO_GRID_V, HOLD_BACK_TO_BATTERY_V
        return self.back_to_grid_v, self.back_to_battery_v

    def back_to_grid_rejection(self, value, holds_load_on_grid):
        """Returns why program 12 cannot be set to value, or None when it can."""
        if holds_load_on_grid:
            return f"locked at {HOLD_BACK_TO_GRID_V}V by the battery mode"
        minimum, maximum = settings.BACK_TO_GRID_V_RANGE
        if not minimum <= value <= maximum:
            return f"must be {minimum}-{maximum}V (above the BMS discharge cut-off)"
        highest_allowed = self.back_to_battery_v - settings.BACK_TO_BATTERY_MINIMUM_GAP_V
        if value > highest_allowed:
            return f"maximum is {highest_allowed}V (program 13 minus {settings.BACK_TO_BATTERY_MINIMUM_GAP_V}V)"
        return None

    def back_to_battery_rejection(self, value, holds_load_on_grid):
        """Returns why program 13 cannot be set to value, or None when it can."""
        if holds_load_on_grid:
            return f"locked at {HOLD_BACK_TO_BATTERY_V}V by the battery mode"
        minimum = settings.BACK_TO_BATTERY_V_RANGE[0]
        maximum = settings.BACK_TO_BATTERY_NORMAL_MAXIMUM_V
        if not minimum <= value <= maximum:
            return f"must be {minimum}-{maximum}V (above {maximum}V the load would never return to battery)"
        lowest_allowed = self.back_to_grid_v + settings.BACK_TO_BATTERY_MINIMUM_GAP_V
        if value < lowest_allowed:
            return f"minimum is {lowest_allowed}V (program 12 plus {settings.BACK_TO_BATTERY_MINIMUM_GAP_V}V)"
        return None
