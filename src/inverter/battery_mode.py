"""Battery modes, selected from Home Assistant. Battery mode is the global trigger: every state sets
output priority, charger source, the program 12/13 hold and whether program 11 grid-charges.

- normal: house on battery (SBU); at Low Battery Protection SOC the house moves to grid (SUB) and
  grid-charges up to Grid Stop Charging SOC, then back to battery
- economy: never grid-charges; at Low Battery Protection SOC the house moves to grid and the battery
  rests until PV covers the house consumption, then back to battery
- quick_grid: house on grid, grid-charging whenever SOC is below Grid Quick Charge SOC; at the target
  the house runs on battery with solar only, and grid charging resumes QUICK_GRID_RESUME_MARGIN_PCT below

Under SBU the inverter leaves the battery only below program 12 (51V maximum), where a LiFePO4 pack still
rests at about 10%, and in battery mode it never grid-charges, so every on-grid state uses SUB (POP01).
Charger source codes are named by live-tested behaviour: grid_charging (PCP01, follows program 11) and
no_grid_charging (PCP02); see settings.CHARGER_SOURCE_TO_PCP.
"""

BATTERY_MODES = ("normal", "economy", "quick_grid")
BATTERY_MODE_DEFAULT = "normal"

ON_BATTERY_GRID_READY = {"output_priority": "SBU", "charger_source": "grid_charging",
                          "hold_load_on_grid": False, "grid_charging": False}
ON_BATTERY_SOLAR_ONLY = {"output_priority": "SBU", "charger_source": "no_grid_charging",
                         "hold_load_on_grid": False, "grid_charging": False}
ON_GRID_CHARGING = {"output_priority": "SUB", "charger_source": "grid_charging",
                    "hold_load_on_grid": True, "grid_charging": True}
ON_GRID_RESTING = {"output_priority": "SUB", "charger_source": "no_grid_charging",
                   "hold_load_on_grid": True, "grid_charging": False}

STATE_SETTINGS = {
    "normal_battery": {"description": "normal: house on battery", **ON_BATTERY_GRID_READY},
    "normal_grid": {"description": "normal: low battery, house on grid, grid charging", **ON_GRID_CHARGING},
    "economy_battery": {"description": "economy: house on battery", **ON_BATTERY_SOLAR_ONLY},
    "economy_grid": {"description": "economy: low battery, house on grid, battery resting", **ON_GRID_RESTING},
    "quick_grid_grid": {"description": "quick grid: house on grid, grid charging", **ON_GRID_CHARGING},
    "quick_grid_battery": {"description": "quick grid: charged, house on battery", **ON_BATTERY_SOLAR_ONLY},
    "no_battery": {"description": "no battery, house on grid", **ON_GRID_RESTING},
}

INVERTER_CAPACITY_STOP_MARGIN_PCT = 10
NO_BATTERY_CONFIRM_CYCLES = 12
# PV must cover (or stop covering) the house this many cycles (about a minute) before economy moves the house
PV_SURPLUS_CONFIRM_CYCLES = 12
QUICK_GRID_RESUME_MARGIN_PCT = 5


class BatteryMode:
    """Chooses output priority, charger source and grid holds from the selected mode, SOC and PV surplus."""

    def __init__(self, low_battery_protection_soc_pct, grid_stop_charging_soc_pct, grid_quick_charge_soc_pct):
        self.selected_mode = BATTERY_MODE_DEFAULT
        self.low_battery_protection_soc_pct = low_battery_protection_soc_pct
        self.grid_stop_charging_soc_pct = grid_stop_charging_soc_pct
        self.grid_quick_charge_soc_pct = grid_quick_charge_soc_pct
        self._on_grid = False
        self._quick_grid_target_reached = False
        self._no_battery_active = False
        self._battery_absent_cycles = 0
        self._battery_present_cycles = 0
        self._pv_surplus = False
        self._pv_surplus_change_cycles = 0
        self._first_update_done = False
        self._last_decision_inputs = None

    @property
    def state(self):
        if self._no_battery_active:
            return "no_battery"
        if self._on_grid:
            return f"{self.selected_mode}_grid"
        return f"{self.selected_mode}_battery"

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
    def is_grid_charging_wanted(self):
        return STATE_SETTINGS[self.state]["grid_charging"]

    @property
    def status_description(self):
        state_settings = STATE_SETTINGS[self.state]
        return (f"{state_settings['description']} "
                f"({state_settings['output_priority']} + {state_settings['charger_source']})")

    @property
    def never_charges_from_grid(self):
        return self.selected_mode == "economy"

    @property
    def is_low_battery_active(self):
        return self._on_grid and self.selected_mode != "quick_grid"

    @property
    def is_no_battery_active(self):
        return self._no_battery_active

    def select(self, mode_name):
        if mode_name not in BATTERY_MODES:
            return False
        if mode_name == self.selected_mode:
            return True
        self.selected_mode = mode_name
        self._on_grid = False
        self._quick_grid_target_reached = False
        # decide the new mode's state now from the last reading, so the inverter never gets the old one for a cycle
        if self._last_decision_inputs is not None and not self._no_battery_active:
            self._on_grid = self._decide_on_grid(*self._last_decision_inputs)
        return True

    def accept_inverter_protection(self):
        if self.selected_mode != "quick_grid":
            self._on_grid = True

    def update(self, estimated_soc_pct, battery_present, inverter_capacity_pct=None, bms_available=False,
               pv_power_w=0, load_power_w=0):
        presence_change = self._update_battery_presence(battery_present, bms_available)
        if presence_change is not None or self._no_battery_active or not battery_present:
            return presence_change
        self._update_pv_surplus(pv_power_w, load_power_w)
        was_on_grid = self._on_grid
        self._last_decision_inputs = (estimated_soc_pct, inverter_capacity_pct, bms_available)
        self._on_grid = self._decide_on_grid(*self._last_decision_inputs)
        if self._on_grid == was_on_grid:
            return None
        return f"SOC {estimated_soc_pct}%, now {self.status_description}"

    def _decide_on_grid(self, estimated_soc_pct, inverter_capacity_pct, bms_available):
        soc_is_low = self._is_soc_low(estimated_soc_pct, inverter_capacity_pct, bms_available)
        if self.selected_mode == "normal":
            if self._on_grid:
                return estimated_soc_pct < self.grid_stop_charging_soc_pct
            return soc_is_low
        if self.selected_mode == "economy":
            if self._on_grid:
                return not self._pv_surplus
            return soc_is_low and not self._pv_surplus
        return self._decide_quick_grid_on_grid(estimated_soc_pct)

    def _decide_quick_grid_on_grid(self, estimated_soc_pct):
        if estimated_soc_pct >= self.grid_quick_charge_soc_pct:
            self._quick_grid_target_reached = True
            return False
        if not self._quick_grid_target_reached or self._on_grid:
            return True
        return estimated_soc_pct <= self.grid_quick_charge_soc_pct - QUICK_GRID_RESUME_MARGIN_PCT

    def _update_pv_surplus(self, pv_power_w, load_power_w):
        surplus_now = pv_power_w > load_power_w
        if surplus_now == self._pv_surplus:
            self._pv_surplus_change_cycles = 0
            return
        self._pv_surplus_change_cycles += 1
        if self._pv_surplus_change_cycles >= PV_SURPLUS_CONFIRM_CYCLES:
            self._pv_surplus = surplus_now
            self._pv_surplus_change_cycles = 0

    def _update_battery_presence(self, battery_present, bms_available):
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
        if not self._no_battery_active:
            return None
        self._battery_present_cycles += 1
        if self._battery_present_cycles < NO_BATTERY_CONFIRM_CYCLES:
            return None
        self._no_battery_active = False
        self._on_grid = False
        return f"battery returned, now {self.status_description}"

    def _is_soc_low(self, estimated_soc_pct, inverter_capacity_pct, bms_available):
        if bms_available:
            return estimated_soc_pct <= self.low_battery_protection_soc_pct
        inverter_stop_threshold = self.low_battery_protection_soc_pct + INVERTER_CAPACITY_STOP_MARGIN_PCT
        return (inverter_capacity_pct is not None
                and inverter_capacity_pct <= inverter_stop_threshold)
