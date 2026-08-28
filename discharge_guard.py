OUTPUT_PRIORITY_MODES = ("auto", "force_sbu", "force_sub")
OUTPUT_PRIORITY_DEFAULT = "auto"


class BatteryDischargeGuard:
    """Switches output priority to stop battery discharge when SOC is too low.

    In auto mode, sends POP01 (solar-first/SUB) when SOC drops to stop
    threshold. Resumes SBU only when solar is producing AND battery has
    charged to resume SOC (default 50%).
    """

    def __init__(self, stop_soc_pct, resume_soc_pct, pv_resume_threshold_w):
        self.stop_soc_pct = stop_soc_pct
        self._resume_soc_pct = resume_soc_pct
        self._pv_resume_threshold_w = pv_resume_threshold_w
        self.mode = OUTPUT_PRIORITY_DEFAULT
        self._discharge_blocked = False

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
