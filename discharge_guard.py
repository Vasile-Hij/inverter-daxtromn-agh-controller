OUTPUT_PRIORITY_MODES = ("force_sbu", "force_sub")
OUTPUT_PRIORITY_DEFAULT = "force_sbu"


class BatteryDischargeGuard:
    """Switches output priority between SBU and SUB based on SOC thresholds.

    In force_sbu mode, auto-protection kicks in: when SOC drops to
    stop_soc_pct (min), switches to force_sub.  When SOC recovers to
    resume_soc_pct (max), switches back to force_sbu.
    A manual mode change from HA clears the auto-protection flag.

    The inverter's own battery_capacity_pct is checked alongside the
    estimated SOC — if either is at or below the stop threshold, protection
    triggers.  This prevents command faults when the inverter hardware
    rejects SBU due to its own low-battery judgment.
    """

    def __init__(self, stop_soc_pct, resume_soc_pct):
        self.stop_soc_pct = stop_soc_pct
        self.resume_soc_pct = resume_soc_pct
        self.mode = OUTPUT_PRIORITY_DEFAULT
        self._auto_protection_active = False

    def update_auto_protection(self, estimated_soc_pct, battery_present, inverter_capacity_pct=None):
        """Auto-switch mode based on SOC thresholds. Returns new mode if changed, else None."""
        if not battery_present:
            return None

        soc_is_low = estimated_soc_pct <= self.stop_soc_pct
        if inverter_capacity_pct is not None and inverter_capacity_pct <= self.stop_soc_pct:
            soc_is_low = True

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
