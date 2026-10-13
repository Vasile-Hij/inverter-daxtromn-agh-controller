"""Battery charging mode: auto (Low Battery Protection + Grid Stop Charging) or manual (Grid Quick Charge).

SBU is set on the LCD — POP02 is blocked by firmware for LIb batteries.
Software only controls charger source (PCP commands) and SUB fallback (POP01) for no-battery.
"""

BATTERY_MODES = ("auto", "manual")
BATTERY_MODE_DEFAULT = "auto"

STATE_SETTINGS = {
    "auto_normal": {
        "description": "auto: normal",
        "output_priority": "SBU",
        "charger_source": "solar_only",
    },
    "auto_low_battery": {
        "description": "auto: low battery protection",
        "output_priority": "SBU",
        "charger_source": "solar_and_utility",
    },
    "auto_no_battery": {
        "description": "auto: no battery",
        "output_priority": "SUB",
        "charger_source": "solar_and_utility",
    },
    "manual_grid_charging": {
        "description": "manual: grid quick charge",
        "output_priority": "SBU",
        "charger_source": "solar_and_utility",
    },
    "manual_charged": {
        "description": "manual: charged, holding",
        "output_priority": "SBU",
        "charger_source": "solar_only",
    },
}

OUTPUT_PRIORITY_TO_POP = {"USB": "POP00", "SUB": "POP01", "SBU": "POP02"}

INVERTER_CAPACITY_STOP_MARGIN_PCT = 10


class BatteryMode:
    """Chooses output priority and charger source from the selected mode and battery SOC."""

    def __init__(self, low_battery_protection_soc_pct, grid_stop_charging_soc_pct, grid_quick_charge_soc_pct):
        self.selected_mode = BATTERY_MODE_DEFAULT
        self.low_battery_protection_soc_pct = low_battery_protection_soc_pct
        self.grid_stop_charging_soc_pct = grid_stop_charging_soc_pct
        self.grid_quick_charge_soc_pct = grid_quick_charge_soc_pct
        self._low_battery_active = False
        self._no_battery_active = False
        self._grid_quick_charge_complete = False

    @property
    def state(self):
        if self.selected_mode == "manual":
            if self._grid_quick_charge_complete:
                return "manual_charged"
            return "manual_grid_charging"
        if self._no_battery_active:
            return "auto_no_battery"
        if self._low_battery_active:
            return "auto_low_battery"
        return "auto_normal"

    @property
    def desired_output_priority(self):
        return STATE_SETTINGS[self.state]["output_priority"]

    @property
    def desired_charger_source(self):
        return STATE_SETTINGS[self.state]["charger_source"]

    @property
    def status_description(self):
        state_settings = STATE_SETTINGS[self.state]
        return (f"{state_settings['description']} "
                f"({state_settings['output_priority']} + {state_settings['charger_source']})")

    @property
    def is_low_battery_active(self):
        return self._low_battery_active

    @property
    def is_no_battery_active(self):
        return self._no_battery_active

    def select(self, mode_name):
        if mode_name not in BATTERY_MODES:
            return False
        self.selected_mode = mode_name
        self._low_battery_active = False
        self._no_battery_active = False
        self._grid_quick_charge_complete = False
        return True

    def update(self, estimated_soc_pct, battery_present, inverter_capacity_pct=None, bms_available=False):
        if self.selected_mode == "manual":
            return self._update_manual(estimated_soc_pct)
        return self._update_auto(estimated_soc_pct, battery_present, inverter_capacity_pct, bms_available)

    def _update_manual(self, estimated_soc_pct):
        if self._grid_quick_charge_complete:
            return None
        if estimated_soc_pct < self.grid_quick_charge_soc_pct:
            return None
        self._grid_quick_charge_complete = True
        return f"grid quick charge reached {estimated_soc_pct}%, now {self.status_description}"

    def _update_auto(self, estimated_soc_pct, battery_present, inverter_capacity_pct, bms_available):
        if not battery_present and not bms_available:
            if self._no_battery_active:
                return None
            self._no_battery_active = True
            self._low_battery_active = False
            return f"no battery detected, now {self.status_description}"

        if self._no_battery_active:
            self._no_battery_active = False
            return f"battery returned, now {self.status_description}"

        if not battery_present:
            return None

        if not self._low_battery_active and self._is_soc_low(estimated_soc_pct, inverter_capacity_pct, bms_available):
            self._low_battery_active = True
            return f"low battery ({estimated_soc_pct}%), now {self.status_description}"

        if self._low_battery_active and estimated_soc_pct >= self.grid_stop_charging_soc_pct:
            self._low_battery_active = False
            return f"battery recovered ({estimated_soc_pct}%), now {self.status_description}"

        return None

    def _is_soc_low(self, estimated_soc_pct, inverter_capacity_pct, bms_available):
        if bms_available:
            return estimated_soc_pct <= self.low_battery_protection_soc_pct
        inverter_stop_threshold = self.low_battery_protection_soc_pct + INVERTER_CAPACITY_STOP_MARGIN_PCT
        return (inverter_capacity_pct is not None
                and inverter_capacity_pct <= inverter_stop_threshold)

    def accept_inverter_protection(self):
        if self.selected_mode == "auto":
            self._low_battery_active = True

    def clear_low_battery(self):
        self._low_battery_active = False
