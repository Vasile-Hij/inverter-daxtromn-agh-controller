OUTPUT_PRIORITY_MODES = ("force_sbu", "force_sub")
OUTPUT_PRIORITY_DEFAULT = "force_sbu"


class BatteryDischargeGuard:
    """Switches output priority between SBU and SUB based on SOC thresholds.

    In force_sbu mode, auto-protection kicks in: when SOC drops to
    stop_soc_pct (min), switches to force_sub.  When SOC recovers to
    resume_soc_pct (max), switches back to force_sbu.
    A manual mode change from HA clears the auto-protection flag.
    """

    def __init__(self, stop_soc_pct, resume_soc_pct):
        self.stop_soc_pct = stop_soc_pct
        self.resume_soc_pct = resume_soc_pct
        self.mode = OUTPUT_PRIORITY_DEFAULT
        self._auto_protection_active = False

    def update_auto_protection(self, estimated_soc_pct, battery_present):
        """Auto-switch mode based on SOC thresholds. Returns new mode if changed, else None."""
        if not battery_present:
            return None

        if estimated_soc_pct <= self.stop_soc_pct and self.mode != "force_sub":
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

    def clear_auto_protection(self):
        self._auto_protection_active = False

    def decide(self):
        if self.mode == "force_sbu":
            return "SBU"
        return "SUB"
