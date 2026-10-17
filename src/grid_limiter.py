"""Grid power limiter: two-tier protection against overloading the grid MCB.

Soft limit: pauses grid charging above a user-set watt threshold (e.g. 5kW),
resumes with hysteresis when grid power drops.

Hard limit (MCB protection): if grid power reaches MCB amps × voltage,
locks out grid charging for a cooldown period (default 30 minutes).
"""


class GridPowerLimiter:
    """Two-tier grid power limiter: soft threshold + MCB lockout."""

    def __init__(self, max_grid_power_w, hysteresis_w, mcb_rating_a,
                 nominal_voltage_v, lockout_seconds):
        self.max_grid_power_w = max_grid_power_w
        self.hysteresis_w = hysteresis_w
        self.mcb_rating_a = mcb_rating_a
        self.nominal_voltage_v = nominal_voltage_v
        self.lockout_seconds = lockout_seconds
        self.is_throttled = False
        self.is_locked_out = False
        self._lockout_until = None

    def _voltage(self, grid_voltage_v):
        if grid_voltage_v is not None:
            return grid_voltage_v
        return self.nominal_voltage_v

    def mcb_power_w(self, grid_voltage_v):
        return self.mcb_rating_a * self._voltage(grid_voltage_v)

    def update(self, grid_power_w, grid_voltage_v, now):
        if self._lockout_until is not None and now >= self._lockout_until:
            self._lockout_until = None
            self.is_locked_out = False
            print(f"grid limiter: MCB lockout expired after {self.lockout_seconds}s", flush=True)

        if grid_power_w is None:
            return self.is_throttled or self.is_locked_out

        mcb_threshold_w = self.mcb_power_w(grid_voltage_v)
        if grid_power_w >= mcb_threshold_w and not self.is_locked_out:
            self.is_locked_out = True
            self.is_throttled = True
            self._lockout_until = now + self.lockout_seconds
            print(f"grid limiter: MCB lockout triggered, grid {grid_power_w}W >= "
                  f"{mcb_threshold_w:.0f}W ({self.mcb_rating_a}A), "
                  f"charging paused for {self.lockout_seconds // 60}min", flush=True)
            return True

        if self.is_locked_out:
            return True

        resume_w = self.max_grid_power_w - self.hysteresis_w
        if not self.is_throttled and grid_power_w >= self.max_grid_power_w:
            self.is_throttled = True
            print(f"grid limiter: throttling, grid {grid_power_w}W >= {self.max_grid_power_w}W", flush=True)
        elif self.is_throttled and grid_power_w <= resume_w:
            self.is_throttled = False
            print(f"grid limiter: resuming, grid {grid_power_w}W <= {resume_w}W", flush=True)

        return self.is_throttled

    @property
    def lockout_remaining_seconds(self):
        if self._lockout_until is None:
            return 0
        return self._lockout_until
