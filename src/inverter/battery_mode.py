"""Battery mode: combined output priority and charger source management.

Three named modes replace separate output-priority and charger-source selectors,
preventing invalid combinations. Low-battery protection overrides any mode to
SUB + solar_only. Quick-charge mode auto-switches to battery_savings once the
battery reaches 51% with PV producing.
"""

BATTERY_MODES = ("battery_savings", "battery_charge_slow", "battery_quick_charge")
BATTERY_MODE_DEFAULT = "battery_savings"

MODE_SETTINGS = {
    "battery_savings": {"output_priority": "SBU", "charger_source": "solar_only"},
    "battery_charge_slow": {"output_priority": "SUB", "charger_source": "solar_first"},
    "battery_quick_charge": {"output_priority": "USB", "charger_source": "solar_and_utility"},
}

MODE_DISPLAY = {
    "battery_savings": "SBU + 050",
    "battery_charge_slow": "SUB + C50",
    "battery_quick_charge": "USB + SNU",
}

LOW_BATTERY_OVERRIDE = {"output_priority": "SUB", "charger_source": "solar_only"}

OUTPUT_PRIORITY_TO_POP = {"USB": "POP00", "SUB": "POP01", "SBU": "POP02"}

INVERTER_CAPACITY_STOP_MARGIN_PCT = 10
QUICK_CHARGE_AUTO_SWITCH_SOC_PCT = 51
PV_PRODUCING_THRESHOLD_W = 10


class BatteryMode:
    """Combined output priority and charger source based on named battery modes."""

    def __init__(self, stop_soc_pct, resume_soc_pct):
        self.selected_mode = BATTERY_MODE_DEFAULT
        self.stop_soc_pct = stop_soc_pct
        self.resume_soc_pct = resume_soc_pct
        self._low_battery_active = False

    @property
    def effective_settings(self):
        if self._low_battery_active:
            return LOW_BATTERY_OVERRIDE
        return MODE_SETTINGS[self.selected_mode]

    @property
    def desired_output_priority(self):
        return self.effective_settings["output_priority"]

    @property
    def desired_charger_source(self):
        return self.effective_settings["charger_source"]

    @property
    def is_low_battery_active(self):
        return self._low_battery_active

    def select(self, mode_name):
        if mode_name not in BATTERY_MODES:
            return False
        self.selected_mode = mode_name
        self._low_battery_active = False
        return True

    def update(self, estimated_soc_pct, battery_present, pv_power_w,
               inverter_capacity_pct=None, bms_available=False):
        if not battery_present and not bms_available:
            if not self._low_battery_active:
                self._low_battery_active = True
                return "no battery detected, forcing SUB + solar_only"
            return None

        if not battery_present:
            return None

        soc_is_low = self._check_soc_low(
            estimated_soc_pct, inverter_capacity_pct, bms_available,
        )
        if soc_is_low and not self._low_battery_active:
            self._low_battery_active = True
            return f"low battery ({estimated_soc_pct}%), forcing SUB + solar_only"

        if self._low_battery_active and estimated_soc_pct >= self.resume_soc_pct:
            self._low_battery_active = False
            return f"battery recovered ({estimated_soc_pct}%), restoring {self.selected_mode}"

        if self._should_auto_switch_from_quick_charge(estimated_soc_pct, pv_power_w):
            self.selected_mode = "battery_savings"
            return (f"quick charge complete ({estimated_soc_pct}% > "
                    f"{QUICK_CHARGE_AUTO_SWITCH_SOC_PCT}% with PV), "
                    "switching to battery_savings")

        return None

    def _check_soc_low(self, estimated_soc_pct, inverter_capacity_pct, bms_available):
        if bms_available:
            return estimated_soc_pct <= self.stop_soc_pct
        inverter_stop_threshold = self.stop_soc_pct + INVERTER_CAPACITY_STOP_MARGIN_PCT
        return (inverter_capacity_pct is not None
                and inverter_capacity_pct <= inverter_stop_threshold)

    def _should_auto_switch_from_quick_charge(self, estimated_soc_pct, pv_power_w):
        if self.selected_mode != "battery_quick_charge":
            return False
        if self._low_battery_active:
            return False
        if estimated_soc_pct <= QUICK_CHARGE_AUTO_SWITCH_SOC_PCT:
            return False
        return pv_power_w is not None and pv_power_w > PV_PRODUCING_THRESHOLD_W

    def accept_inverter_protection(self):
        if not self._low_battery_active:
            self._low_battery_active = True

    def clear_low_battery(self):
        self._low_battery_active = False
