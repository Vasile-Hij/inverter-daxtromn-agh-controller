OUTPUT_PRIORITY_MODES = ("auto", "force_sbu", "force_sub")
OUTPUT_PRIORITY_DEFAULT = "auto"


class BatteryDischargeGuard:
    """Switches output priority to stop battery discharge when SOC is too low.

    Auto-protection: when SOC drops to the HA-configured stop threshold
    (slider minimum 10%), mode switches to force_sub.  When SOC recovers
    to resume threshold (default 50%), mode switches to force_sbu.
    A manual mode change from HA clears the auto-protection flag.
    """

    def __init__(self, stop_soc_pct, resume_soc_pct, pv_resume_threshold_w):
        self.stop_soc_pct = stop_soc_pct
        self._resume_soc_pct = resume_soc_pct
        self._pv_resume_threshold_w = pv_resume_threshold_w
        self.mode = OUTPUT_PRIORITY_DEFAULT
        self._discharge_blocked = False
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
                and estimated_soc_pct >= self._resume_soc_pct):
            self.mode = "force_sbu"
            self._auto_protection_active = False
            return "force_sbu"

        return None

    def clear_auto_protection(self):
        self._auto_protection_active = False

    def decide(self, estimated_soc_pct, battery_present, pv_total_power_w):
        if self.mode == "force_sbu":
            self._discharge_blocked = False
            return "SBU"
        if self.mode == "force_sub":
            self._discharge_blocked = True
            return "SUB"

        if not battery_present:
            self._discharge_blocked = False
            return "SBU"

        if self._discharge_blocked:
            solar_is_producing = pv_total_power_w >= self._pv_resume_threshold_w
            battery_recovered = estimated_soc_pct >= self._resume_soc_pct
            if solar_is_producing and battery_recovered:
                self._discharge_blocked = False
                return "SBU"
            return "SUB"

        if estimated_soc_pct <= self.stop_soc_pct:
            self._discharge_blocked = True
            return "SUB"
        return "SBU"

    @property
    def is_discharge_blocked(self):
        return self._discharge_blocked
