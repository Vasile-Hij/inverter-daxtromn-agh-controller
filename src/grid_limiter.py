"""Grid MCB protection: locks out grid charging when grid current reaches the breaker rating.

Only trips while the inverter is charging from the grid, since pausing the charger is the only
lever: an overload from house load alone is reported (is_over_rating) but not acted on.
Each repeated lockout lasts longer (lockout_steps_seconds); after the last step grid charging
stays off until local midnight, so the charger source is not rewritten on the inverter every
half hour. The repeat count resets when grid charging is no longer wanted (reset_repeats).
"""

import time


def seconds_until_local_midnight(now):
    local_time = time.localtime(now)
    next_midnight = time.mktime((local_time.tm_year, local_time.tm_mon, local_time.tm_mday + 1, 0, 0, 0, 0, 0, -1))
    return next_midnight - now


class GridLimiter:
    """MCB current lockout: pauses grid charging when the breaker limit is reached, longer on each repeat."""

    def __init__(self, mcb_rating_a, lockout_steps_seconds):
        self.mcb_rating_a = mcb_rating_a
        self.lockout_steps_seconds = lockout_steps_seconds
        self.is_locked_out = False
        self.is_over_rating = False
        self.lockout_count = 0
        self._lockout_until = None

    def update(self, grid_current_a, grid_charging_active, now):
        self._expire_lockout(now)

        if grid_current_a is None:
            return self.is_locked_out

        self.is_over_rating = grid_current_a >= self.mcb_rating_a
        if self.is_over_rating and grid_charging_active and not self.is_locked_out:
            self._start_lockout(grid_current_a, now)

        return self.is_locked_out

    def reset_repeats(self):
        if self.lockout_count == 0:
            return
        self.lockout_count = 0
        print("grid limiter: grid charging no longer wanted, lockout repeats reset", flush=True)

    @property
    def runs_until_midnight(self):
        return self.lockout_count > len(self.lockout_steps_seconds)

    def _start_lockout(self, grid_current_a, now):
        lockout_seconds = self._next_lockout_seconds(now)
        self.lockout_count += 1
        self.is_locked_out = True
        self._lockout_until = now + lockout_seconds
        print(f"grid limiter: MCB lockout #{self.lockout_count} triggered, grid {grid_current_a:.1f}A >= "
              f"{self.mcb_rating_a}A while grid charging, charging paused for {int(lockout_seconds // 60)}min", flush=True)

    def _next_lockout_seconds(self, now):
        if self.lockout_count < len(self.lockout_steps_seconds):
            return self.lockout_steps_seconds[self.lockout_count]
        return max(seconds_until_local_midnight(now), self.lockout_steps_seconds[-1])

    def _expire_lockout(self, now):
        if self._lockout_until is None or now < self._lockout_until:
            return
        if self.runs_until_midnight:
            self.lockout_count = 0
        self._lockout_until = None
        self.is_locked_out = False
        print("grid limiter: MCB lockout expired, grid charging allowed again", flush=True)
