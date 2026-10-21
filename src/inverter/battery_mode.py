"""Battery charging mode, selected from Home Assistant:

- auto: Low Battery Protection + Grid Stop Charging, decided from SOC
- solar_only: never charges from grid, even when the battery is low
- solar_and_grid: always charges from solar and grid together, no SOC stop
- grid_quick_charge: charges from solar and grid up to Grid Quick Charge SOC, then solar only

Output priority stays SBU, set once on the LCD: POP02 is blocked by firmware for LIb batteries,
so any POP01 (SUB) the software sent could never be undone. With no usable battery, SBU already
runs the load from the grid. Software controls the charger source (PCP commands), and in
low battery protection moves the load to grid through programs 12/13 (hold_load_on_grid).
"""

BATTERY_MODES = ("auto", "solar_only", "solar_and_grid", "grid_quick_charge")
BATTERY_MODE_DEFAULT = "auto"
FIXED_CHARGER_MODES = ("solar_only", "solar_and_grid")

STATE_SETTINGS = {
    "auto_normal": {
        "description": "auto: normal",
        "output_priority": "SBU",
        "charger_source": "solar_only",
        "hold_load_on_grid": False,
    },
    "auto_low_battery": {
        "description": "auto: low battery protection",
        "output_priority": "SBU",
        "charger_source": "solar_first",
        "hold_load_on_grid": True,
    },
    "auto_no_battery": {
        "description": "auto: no battery",
        "output_priority": "SBU",
        "charger_source": "solar_and_utility",
        "hold_load_on_grid": False,
    },
    "solar_only": {
        "description": "solar only",
        "output_priority": "SBU",
        "charger_source": "solar_only",
        "hold_load_on_grid": False,
    },
    "solar_and_grid": {
        "description": "solar and grid",
        "output_priority": "SBU",
        "charger_source": "solar_and_utility",
        "hold_load_on_grid": False,
    },
    "grid_quick_charge_charging": {
        "description": "grid quick charge",
        "output_priority": "SBU",
        "charger_source": "solar_and_utility",
        "hold_load_on_grid": False,
    },
    "grid_quick_charge_charged": {
        "description": "grid quick charge: charged, holding",
        "output_priority": "SBU",
        "charger_source": "solar_only",
        "hold_load_on_grid": False,
    },
}


INVERTER_CAPACITY_STOP_MARGIN_PCT = 10
NO_BATTERY_CONFIRM_CYCLES = 12


class BatteryMode:
    """Chooses output priority and charger source from the selected mode and battery SOC."""

    def __init__(self, low_battery_protection_soc_pct, grid_stop_charging_soc_pct, grid_quick_charge_soc_pct):
        self.selected_mode = BATTERY_MODE_DEFAULT
        self.low_battery_protection_soc_pct = low_battery_protection_soc_pct
        self.grid_stop_charging_soc_pct = grid_stop_charging_soc_pct
        self.grid_quick_charge_soc_pct = grid_quick_charge_soc_pct
        self._low_battery_active = False
        self._no_battery_active = False
        self._battery_absent_cycles = 0
        self._battery_present_cycles = 0
        self._grid_quick_charge_complete = False
        self._first_update_done = False

    @property
    def state(self):
        if self.selected_mode in FIXED_CHARGER_MODES:
            return self.selected_mode
        if self.selected_mode == "grid_quick_charge":
            if self._grid_quick_charge_complete:
                return "grid_quick_charge_charged"
            return "grid_quick_charge_charging"
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
    def holds_load_on_grid(self):
        return STATE_SETTINGS[self.state]["hold_load_on_grid"]

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
        if mode_name == "auto" and self.selected_mode == "auto":
            return True
        self.selected_mode = mode_name
        self._low_battery_active = False
        self._no_battery_active = False
        self._battery_absent_cycles = 0
        self._battery_present_cycles = 0
        self._grid_quick_charge_complete = False
        return True

    def update(self, estimated_soc_pct, battery_present, inverter_capacity_pct=None, bms_available=False):
        if self.selected_mode in FIXED_CHARGER_MODES:
            return None
        if self.selected_mode == "grid_quick_charge":
            return self._update_grid_quick_charge(estimated_soc_pct)
        return self._update_auto(estimated_soc_pct, battery_present, inverter_capacity_pct, bms_available)

    def _update_grid_quick_charge(self, estimated_soc_pct):
        if self._grid_quick_charge_complete:
            return None
        if estimated_soc_pct < self.grid_quick_charge_soc_pct:
            return None
        self._grid_quick_charge_complete = True
        return f"grid quick charge reached {estimated_soc_pct}%, now {self.status_description}"

    def _update_auto(self, estimated_soc_pct, battery_present, inverter_capacity_pct, bms_available):
        # Decide immediately on the first reading after start; debounce only later changes.
        confirm_cycles = NO_BATTERY_CONFIRM_CYCLES if self._first_update_done else 1
        self._first_update_done = True

        if not battery_present and not bms_available:
            self._battery_absent_cycles += 1
            self._battery_present_cycles = 0
            if self._no_battery_active or self._battery_absent_cycles < confirm_cycles:
                return None
            self._no_battery_active = True
            return f"no battery detected, now {self.status_description}"

        self._battery_absent_cycles = 0
        if self._no_battery_active:
            self._battery_present_cycles += 1
            if self._battery_present_cycles < NO_BATTERY_CONFIRM_CYCLES:
                return None
            self._no_battery_active = False
            # A battery that vanished is usually a BMS cutoff on a deep discharge: grid-charge it until recovered.
            self._low_battery_active = estimated_soc_pct < self.grid_stop_charging_soc_pct
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
