from grid_limiter import GridLimiter


def make_limiter(mcb_rating_a=32, lockout_seconds=1800):
    return GridLimiter(mcb_rating_a, lockout_seconds)


class TestMcbLockout:

    def test_initial_state_not_locked(self):
        limiter = make_limiter()
        assert limiter.is_locked_out is False

    def test_lockout_triggers_at_mcb_current(self):
        limiter = make_limiter()
        limiter.update(32, 100)
        assert limiter.is_locked_out is True

    def test_no_lockout_below_mcb(self):
        limiter = make_limiter()
        limiter.update(31.9, 100)
        assert limiter.is_locked_out is False

    def test_lockout_stays_active_when_current_drops(self):
        limiter = make_limiter()
        limiter.update(32, 100)
        limiter.update(8, 105)
        assert limiter.is_locked_out is True

    def test_lockout_expires_after_timeout(self):
        limiter = make_limiter(lockout_seconds=1800)
        limiter.update(32, 100)
        assert limiter.is_locked_out is True
        limiter.update(8, 1900)
        assert limiter.is_locked_out is False

    def test_lockout_does_not_expire_early(self):
        limiter = make_limiter(lockout_seconds=1800)
        limiter.update(32, 100)
        limiter.update(8, 1899)
        assert limiter.is_locked_out is True

    def test_none_current_does_not_trigger_lockout(self):
        limiter = make_limiter()
        limiter.update(None, 100)
        assert limiter.is_locked_out is False

    def test_none_current_preserves_lockout(self):
        limiter = make_limiter()
        limiter.update(32, 100)
        limiter.update(None, 105)
        assert limiter.is_locked_out is True

    def test_100a_mcb(self):
        limiter = make_limiter(mcb_rating_a=100)
        limiter.update(99, 100)
        assert limiter.is_locked_out is False
        limiter.update(100, 105)
        assert limiter.is_locked_out is True

    def test_adjustable_mcb_rating(self):
        limiter = make_limiter(mcb_rating_a=32)
        limiter.mcb_rating_a = 25
        limiter.update(25, 100)
        assert limiter.is_locked_out is True
