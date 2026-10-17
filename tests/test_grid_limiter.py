from grid_limiter import GridPowerLimiter


def make_limiter(max_power_w=5000, hysteresis_w=500, mcb_rating_a=32,
                 nominal_voltage_v=240, lockout_seconds=1800):
    return GridPowerLimiter(max_power_w, hysteresis_w, mcb_rating_a,
                            nominal_voltage_v, lockout_seconds)


class TestSoftLimit:

    def test_initial_state_is_not_throttled(self):
        limiter = make_limiter()
        assert limiter.is_throttled is False

    def test_throttles_at_max_power(self):
        limiter = make_limiter()
        limiter.update(5000, 240, 100)
        assert limiter.is_throttled is True
        assert limiter.is_locked_out is False

    def test_does_not_throttle_below_max(self):
        limiter = make_limiter()
        limiter.update(4999, 240, 100)
        assert limiter.is_throttled is False

    def test_stays_throttled_in_hysteresis_band(self):
        limiter = make_limiter()
        limiter.update(5000, 240, 100)
        limiter.update(4600, 240, 105)
        assert limiter.is_throttled is True

    def test_resumes_below_hysteresis(self):
        limiter = make_limiter()
        limiter.update(5000, 240, 100)
        limiter.update(4500, 240, 105)
        assert limiter.is_throttled is False

    def test_none_power_keeps_current_state(self):
        limiter = make_limiter()
        limiter.update(None, 240, 100)
        assert limiter.is_throttled is False
        limiter.update(6000, 240, 105)
        limiter.update(None, 240, 110)
        assert limiter.is_throttled is True

    def test_adjustable_max_power(self):
        limiter = make_limiter()
        limiter.max_grid_power_w = 3000
        limiter.update(3000, 240, 100)
        assert limiter.is_throttled is True


class TestMcbLockout:

    def test_lockout_triggers_at_mcb_threshold(self):
        limiter = make_limiter()
        limiter.update(7680, 240, 100)
        assert limiter.is_locked_out is True
        assert limiter.is_throttled is True

    def test_lockout_stays_active_even_when_power_drops(self):
        limiter = make_limiter()
        limiter.update(7680, 240, 100)
        limiter.update(2000, 240, 105)
        assert limiter.is_locked_out is True

    def test_lockout_expires_after_timeout(self):
        limiter = make_limiter(lockout_seconds=1800)
        limiter.update(7680, 240, 100)
        assert limiter.is_locked_out is True
        limiter.update(2000, 240, 1900)
        assert limiter.is_locked_out is False
        assert limiter.is_throttled is False

    def test_lockout_does_not_expire_early(self):
        limiter = make_limiter(lockout_seconds=1800)
        limiter.update(7680, 240, 100)
        limiter.update(2000, 240, 1899)
        assert limiter.is_locked_out is True

    def test_lockout_uses_live_voltage(self):
        limiter = make_limiter()
        limiter.update(7360, 230, 100)
        assert limiter.is_locked_out is True

    def test_lockout_uses_nominal_when_voltage_none(self):
        limiter = make_limiter()
        limiter.update(7680, None, 100)
        assert limiter.is_locked_out is True

    def test_mcb_power_calculation(self):
        limiter = make_limiter()
        assert limiter.mcb_power_w(240) == 7680
        assert limiter.mcb_power_w(230) == 7360
        assert limiter.mcb_power_w(None) == 7680


class TestTierPriority:

    def test_mcb_overrides_soft_limit(self):
        limiter = make_limiter(max_power_w=5000)
        limiter.update(8000, 240, 100)
        assert limiter.is_locked_out is True
        assert limiter.is_throttled is True

    def test_soft_limit_does_not_cause_lockout(self):
        limiter = make_limiter(max_power_w=5000)
        limiter.update(5500, 240, 100)
        assert limiter.is_throttled is True
        assert limiter.is_locked_out is False

    def test_after_lockout_soft_limit_resumes(self):
        limiter = make_limiter(max_power_w=5000, lockout_seconds=60)
        limiter.update(8000, 240, 100)
        assert limiter.is_locked_out is True
        limiter.update(4000, 240, 161)
        assert limiter.is_locked_out is False
        assert limiter.is_throttled is False
