from unittest.mock import MagicMock

from mqtt.npe_supervisor import NpeSupervisor


def make_supervisor(grid_power_w, zmai_online=True, ac_input_voltage_v=240.0):
    npe_bonding = MagicMock()
    npe_bonding.decide.return_value = True
    npe_bonding.is_bonded = True
    npe_bonding.last_reasons = {}
    npe_bonding.mode = "auto"
    zmai_meter = MagicMock()
    zmai_meter.power_w = grid_power_w
    zmai_meter.has_recent_data.return_value = zmai_online
    inverter = MagicMock()
    inverter.last_data = {"ac_input_voltage_v": ac_input_voltage_v}
    inverter.has_recent_data.return_value = True
    return NpeSupervisor(npe_bonding, zmai_meter, inverter, MagicMock()), npe_bonding


class TestEvaluate:

    def test_passes_live_readings_to_decision_and_drives_relay(self):
        supervisor, npe_bonding = make_supervisor(grid_power_w=3.1)
        supervisor._evaluate(100.0)
        npe_bonding.decide.assert_called_once_with(240.0, 3.1, True, True, 100.0)
        npe_bonding.apply.assert_called_once_with(True)

    def test_stale_meter_reading_is_not_used(self):
        supervisor, npe_bonding = make_supervisor(grid_power_w=3.1, zmai_online=False)
        supervisor._evaluate(100.0)
        npe_bonding.decide.assert_called_once_with(240.0, None, False, True, 100.0)

    def test_publishes_on_change_and_then_every_interval_only(self):
        supervisor, _ = make_supervisor(grid_power_w=3.1)
        supervisor._evaluate(100.0)
        supervisor._evaluate(101.0)
        published_states = [call for call in supervisor._client.publish.call_args_list
                            if call.args[0].endswith("npe_bonding/state")]
        assert len(published_states) == 1
