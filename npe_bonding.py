from gpiozero import DigitalOutputDevice

GRID_VOLTAGE_THRESHOLD_V = 50


class NpeBonding:
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

    def decide(self, ac_input_voltage_v, grid_power_w, grid_online, battery_power_w, now):
        if self.mode == "manual_on":
            self._low_power_since = None
            return True
        if self.mode == "manual_off":
            self._low_power_since = None
            return False

        if battery_power_w is not None:
            self._last_battery_power_w = battery_power_w
            self._last_battery_update_time = now
        battery_reading_is_recent = (
            self._last_battery_update_time is not None
            and (now - self._last_battery_update_time) < self._battery_stale_seconds
        )
        held_battery_power_w = self._last_battery_power_w if battery_reading_is_recent else None

        grid_absent_by_inverter = ac_input_voltage_v is not None and ac_input_voltage_v < GRID_VOLTAGE_THRESHOLD_V
        grid_absent_by_meter = grid_power_w is not None and grid_power_w < self._threshold_w
        grid_absent_by_battery_failsafe = (
            not grid_online and held_battery_power_w is not None and held_battery_power_w > self._threshold_w
        )
        off_grid_signal = grid_absent_by_inverter or grid_absent_by_meter or grid_absent_by_battery_failsafe

        self.last_reasons = {
            "grid_absent_by_inverter": grid_absent_by_inverter,
            "grid_absent_by_meter": grid_absent_by_meter,
            "grid_absent_by_failsafe": grid_absent_by_battery_failsafe,
            "ac_input_v": ac_input_voltage_v,
            "grid_power_w": grid_power_w,
        }

        if not off_grid_signal:
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
