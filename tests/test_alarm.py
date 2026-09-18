from alarm import Alarm


class TestAlarm:

    def test_initial_state_not_active(self):
        alarm = Alarm("test", repeat_seconds=300)
        assert alarm.active is False

    def test_fault_raises_alarm(self):
        alarm = Alarm("test", repeat_seconds=300)
        alarm.update(True, "something broke", 1000.0)
        assert alarm.active is True

    def test_clear_after_fault(self):
        alarm = Alarm("test", repeat_seconds=300)
        alarm.update(True, "something broke", 1000.0)
        alarm.update(False, "", 1001.0)
        assert alarm.active is False

    def test_no_repeat_within_interval(self, capsys):
        alarm = Alarm("test", repeat_seconds=300)
        alarm.update(True, "fault", 1000.0)
        captured = capsys.readouterr()
        assert "RAISED" in captured.out
        alarm.update(True, "fault", 1100.0)
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_repeat_after_interval(self, capsys):
        alarm = Alarm("test", repeat_seconds=300)
        alarm.update(True, "fault", 1000.0)
        capsys.readouterr()
        alarm.update(True, "fault", 1400.0)
        captured = capsys.readouterr()
        assert "ACTIVE" in captured.out

    def test_clear_prints_message(self, capsys):
        alarm = Alarm("test", repeat_seconds=300)
        alarm.update(True, "fault", 1000.0)
        capsys.readouterr()
        alarm.update(False, "", 1001.0)
        captured = capsys.readouterr()
        assert "CLEARED" in captured.out

    def test_clear_without_prior_fault_no_output(self, capsys):
        alarm = Alarm("test", repeat_seconds=300)
        alarm.update(False, "", 1000.0)
        captured = capsys.readouterr()
        assert captured.out == ""
