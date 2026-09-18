OUTPUT_PRIORITY_MODES = ("force_sbu", "force_sub")
OUTPUT_PRIORITY_DEFAULT = "force_sbu"

INVERTER_CAPACITY_STOP_MARGIN_PCT = 10


class BatteryDischargeGuard:
    """Switches output priority between SBU and SUB based on SOC thresholds.

    When BMS is available, trusts BMS SOC against stop_soc_pct.
    When BMS is offline but the inverter still detects a battery, falls back
    to inverter battery_capacity_pct with an extra safety margin since the
    inverter gauge is less accurate for LiFePO4.
    When BMS is offline and the inverter detects no battery, forces SUB.
    """

    def __init__(self, stop_soc_pct, resume_soc_pct):
        self.stop_soc_pct = stop_soc_pct
        self.resume_soc_pct = resume_soc_pct
        self.mode = OUTPUT_PRIORITY_DEFAULT
        self._auto_protection_active = False

    def update_auto_protection(self, estimated_soc_pct, battery_present,
                               inverter_capacity_pct=None, bms_available=False):
        """Auto-switch mode based on SOC thresholds. Returns new mode if changed, else None."""
        if not battery_present and not bms_available:
            if self.mode != "force_sub":
                self.mode = "force_sub"
                self._auto_protection_active = True
                return "force_sub"
            return None

        if not battery_present:
            return None

        if bms_available:
            soc_is_low = estimated_soc_pct <= self.stop_soc_pct
        else:
            inverter_stop_threshold = self.stop_soc_pct + INVERTER_CAPACITY_STOP_MARGIN_PCT
            soc_is_low = (inverter_capacity_pct is not None
                          and inverter_capacity_pct <= inverter_stop_threshold)

        if soc_is_low and self.mode != "force_sub":
            self.mode = "force_sub"
            self._auto_protection_active = True
            return "force_sub"

        if (self._auto_protection_active
                and self.mode == "force_sub"
                and estimated_soc_pct >= self.resume_soc_pct):
            self.mode = "force_sbu"
            self._auto_protection_active = False
            return "force_sbu"

        return None

    def accept_inverter_protection(self):
        """Accept that the inverter hardware is protecting the battery on SUB."""
        if self.mode != "force_sub":
            self.mode = "force_sub"
            self._auto_protection_active = True

    def clear_auto_protection(self):
        self._auto_protection_active = False

    def decide(self):
        if self.mode == "force_sbu":
            return "SBU"
        return "SUB"
