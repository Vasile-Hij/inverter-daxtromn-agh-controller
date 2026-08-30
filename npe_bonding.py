"""N-PE bonding relay control: bonds neutral to earth only when the inverter islands."""

from gpiozero import DigitalOutputDevice

GRID_VOLTAGE_THRESHOLD_V = 50


class NpeBonding:
    """Decides and drives the N-PE bonding relay from grid and battery signals."""

    def __init__(self, pin, threshold_w, stable_seconds, battery_stale_seconds):
        self._threshold_w = threshold_w
        self._stable_seconds = stable_seconds
        self._battery_stale_seconds = battery_stale_seconds
        self._relay = DigitalOutputDevice(pin, active_high=True, initial_value=False)
        self._low_power_since = None
        self._last_battery_power_w = None
        self._last_battery_update_time = None
        self.mode = "auto"
        self.last_reasons = {}

    def _held_battery_power(self, battery_power_w, now):
        if battery_power_w is not None:
            self._last_battery_power_w = battery_power_w
            self._last_battery_update_time = now
        if self._last_battery_update_time is None:
            return None
        if (now - self._last_battery_update_time) >= self._battery_stale_seconds:
            return None
        return self._last_battery_power_w

    def _is_off_grid(self, ac_input_voltage_v, grid_power_w, grid_online, battery_power_w, now):
        held_battery_power_w = self._held_battery_power(battery_power_w, now)
        grid_absent_by_inverter = ac_input_voltage_v is not None and ac_input_voltage_v < GRID_VOLTAGE_THRESHOLD_V
        grid_absent_by_meter = grid_power_w is not None and grid_power_w < self._threshold_w
        grid_absent_by_battery_failsafe = (
            not grid_online and held_battery_power_w is not None and held_battery_power_w > self._threshold_w
        )
        self.last_reasons = {
            "grid_absent_by_inverter": grid_absent_by_inverter,
            "grid_absent_by_meter": grid_absent_by_meter,
            "grid_absent_by_failsafe": grid_absent_by_battery_failsafe,
            "ac_input_v": ac_input_voltage_v,
            "grid_power_w": grid_power_w,
        }
        return grid_absent_by_inverter or grid_absent_by_meter or grid_absent_by_battery_failsafe

    def decide(self, ac_input_voltage_v, grid_power_w, grid_online, battery_power_w, now):
        if self.mode == "manual_on":
            self._low_power_since = None
            return True
        if self.mode == "manual_off":
            self._low_power_since = None
            return False

        if not self._is_off_grid(ac_input_voltage_v, grid_power_w, grid_online, battery_power_w, now):
            self._low_power_since = None
            return False

        if self._low_power_since is None:
            self._low_power_since = now
        return (now - self._low_power_since) >= self._stable_seconds

    def apply(self, desired_state):
        if desired_state and not self._relay.value:
            self._relay.on()
        elif not desired_state and self._relay.value:
            self._relay.off()

    @property
    def is_bonded(self):
        return bool(self._relay.value)
