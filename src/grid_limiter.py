"""Grid MCB protection: locks out grid charging when current reaches the breaker rating.

If grid current (from ZMAi meter) reaches MCB amps, locks out grid charging
for a cooldown period (default 30 minutes) to prevent tripping the breaker.
"""


class GridLimiter:
    """MCB current lockout: pauses grid charging when breaker limit is reached."""

    def __init__(self, mcb_rating_a, lockout_seconds):
        self.mcb_rating_a = mcb_rating_a
        self.lockout_seconds = lockout_seconds
        self.is_locked_out = False
        self._lockout_until = None

    def update(self, grid_current_a, now):
        if self._lockout_until is not None and now >= self._lockout_until:
            self._lockout_until = None
            self.is_locked_out = False
            print(f"grid limiter: MCB lockout expired after {self.lockout_seconds}s", flush=True)

        if grid_current_a is None:
            return self.is_locked_out

        if grid_current_a >= self.mcb_rating_a and not self.is_locked_out:
            self.is_locked_out = True
            self._lockout_until = now + self.lockout_seconds
            print(f"grid limiter: MCB lockout triggered, grid {grid_current_a:.1f}A >= "
                  f"{self.mcb_rating_a}A, charging paused for {self.lockout_seconds // 60}min", flush=True)

        return self.is_locked_out

    @property
    def lockout_remaining_seconds(self):
        if self._lockout_until is None:
            return 0
        return self._lockout_until
