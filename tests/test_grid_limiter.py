from grid_limiter import GridLimiter, seconds_until_local_midnight

LOCKOUT_STEPS = (1800, 3600, 7200)


def make_limiter(mcb_rating_a=32, lockout_steps_seconds=LOCKOUT_STEPS):
    return GridLimiter(mcb_rating_a, lockout_steps_seconds)


def trigger_and_expire(limiter, now):
    limiter.update(40, True, now)
    expiry = limiter._lockout_until
    limiter.update(8, False, expiry)
    return expiry


class TestMcbLockout:

    def test_initial_state_not_locked(self):
        limiter = make_limiter()
        assert limiter.is_locked_out is False

    def test_lockout_triggers_at_mcb_current_while_grid_charging(self):
        limiter = make_limiter()
        limiter.update(32, True, 100)
        assert limiter.is_locked_out is True

    def test_no_lockout_below_mcb(self):
        limiter = make_limiter()
        limiter.update(31.9, True, 100)
        assert limiter.is_locked_out is False

    def test_house_load_alone_reports_but_does_not_lock_out(self):
        limiter = make_limiter()
        limiter.update(40, False, 100)
        assert limiter.is_over_rating is True
        assert limiter.is_locked_out is False
        assert limiter.lockout_count == 0

    def test_over_rating_clears_when_current_drops(self):
        limiter = make_limiter()
        limiter.update(40, False, 100)
        limiter.update(20, False, 105)
        assert limiter.is_over_rating is False

    def test_lockout_stays_active_when_current_drops(self):
        limiter = make_limiter()
        limiter.update(32, True, 100)
        limiter.update(8, False, 105)
        assert limiter.is_locked_out is True

    def test_first_lockout_expires_after_first_step(self):
        limiter = make_limiter()
        limiter.update(32, True, 100)
        limiter.update(8, False, 1899)
        assert limiter.is_locked_out is True
        limiter.update(8, False, 1900)
        assert limiter.is_locked_out is False

    def test_none_current_does_not_trigger_lockout(self):
        limiter = make_limiter()
        limiter.update(None, True, 100)
        assert limiter.is_locked_out is False

    def test_none_current_preserves_lockout(self):
        limiter = make_limiter()
        limiter.update(32, True, 100)
        limiter.update(None, True, 105)
        assert limiter.is_locked_out is True

    def test_100a_mcb(self):
        limiter = make_limiter(mcb_rating_a=100)
        limiter.update(99, True, 100)
        assert limiter.is_locked_out is False
        limiter.update(100, True, 105)
        assert limiter.is_locked_out is True

    def test_adjustable_mcb_rating(self):
        limiter = make_limiter(mcb_rating_a=32)
        limiter.mcb_rating_a = 25
        limiter.update(25, True, 100)
        assert limiter.is_locked_out is True


class TestLockoutEscalation:

    def test_each_repeat_lasts_longer(self):
        limiter = make_limiter()
        now = 1000
        for expected_seconds in LOCKOUT_STEPS:
            limiter.update(40, True, now)
            assert limiter._lockout_until - now == expected_seconds
            now = limiter._lockout_until
            limiter.update(8, False, now)

    def test_after_last_step_lockout_runs_until_midnight(self):
        limiter = make_limiter()
        now = 1000
        for _ in LOCKOUT_STEPS:
            now = trigger_and_expire(limiter, now)
        limiter.update(40, True, now)
        expected_seconds = max(seconds_until_local_midnight(now), LOCKOUT_STEPS[-1])
        assert limiter._lockout_until - now == expected_seconds
        assert limiter.runs_until_midnight is True

    def test_midnight_expiry_starts_a_fresh_day(self):
        limiter = make_limiter()
        now = 1000
        for _ in range(len(LOCKOUT_STEPS) + 1):
            now = trigger_and_expire(limiter, now)
        assert limiter.lockout_count == 0
        limiter.update(40, True, now)
        assert limiter._lockout_until - now == LOCKOUT_STEPS[0]

    def test_reset_repeats_returns_to_first_step(self):
        limiter = make_limiter()
        now = trigger_and_expire(limiter, 1000)
        limiter.reset_repeats()
        limiter.update(40, True, now)
        assert limiter._lockout_until - now == LOCKOUT_STEPS[0]

    def test_reset_repeats_keeps_active_lockout(self):
        limiter = make_limiter()
        limiter.update(40, True, 1000)
        limiter.reset_repeats()
        assert limiter.is_locked_out is True


class TestSecondsUntilMidnight:

    def test_is_within_one_day(self):
        remaining = seconds_until_local_midnight(1_792_561_529)
        assert 0 < remaining <= 24 * 3600
