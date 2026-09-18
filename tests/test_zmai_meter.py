from mqtt.zmai_meter import ZmaiMeter, ZMAI_POWER_TOPIC, ZMAI_VOLTAGE_TOPIC, ZMAI_CURRENT_TOPIC, ZMAI_RELAY_TOPIC


class TestZmaiMeter:

    def test_initial_state_is_none(self):
        meter = ZmaiMeter()
        assert meter.power_w is None
        assert meter.voltage_v is None
        assert meter.current_a is None
        assert meter.relay_is_on is None

    def test_power_message_updates_power(self):
        meter = ZmaiMeter()
        meter.on_message(ZMAI_POWER_TOPIC, "150.5", 1000.0)
        assert meter.power_w == 150.5

    def test_voltage_message_updates_voltage(self):
        meter = ZmaiMeter()
        meter.on_message(ZMAI_VOLTAGE_TOPIC, "230.1", 1000.0)
        assert meter.voltage_v == 230.1

    def test_current_message_updates_current(self):
        meter = ZmaiMeter()
        meter.on_message(ZMAI_CURRENT_TOPIC, "0.65", 1000.0)
        assert meter.current_a == 0.65

    def test_relay_on(self):
        meter = ZmaiMeter()
        meter.on_message(ZMAI_RELAY_TOPIC, "1", 1000.0)
        assert meter.relay_is_on is True

    def test_relay_off(self):
        meter = ZmaiMeter()
        meter.on_message(ZMAI_RELAY_TOPIC, "0", 1000.0)
        assert meter.relay_is_on is False

    def test_non_numeric_payload_ignored(self):
        meter = ZmaiMeter()
        meter.on_message(ZMAI_POWER_TOPIC, "not_a_number", 1000.0)
        assert meter.power_w is None

    def test_has_recent_data_true(self):
        meter = ZmaiMeter()
        meter.on_message(ZMAI_POWER_TOPIC, "100", 1000.0)
        assert meter.has_recent_data(1005.0, stale_seconds=15) is True

    def test_has_recent_data_false_when_stale(self):
        meter = ZmaiMeter()
        meter.on_message(ZMAI_POWER_TOPIC, "100", 1000.0)
        assert meter.has_recent_data(1020.0, stale_seconds=15) is False

    def test_has_recent_data_false_when_no_data(self):
        meter = ZmaiMeter()
        assert meter.has_recent_data(1000.0, stale_seconds=15) is False

    def test_only_power_topic_updates_timestamp(self):
        meter = ZmaiMeter()
        meter.on_message(ZMAI_VOLTAGE_TOPIC, "230", 1000.0)
        assert meter.has_recent_data(1000.0, stale_seconds=15) is False
        meter.on_message(ZMAI_POWER_TOPIC, "100", 1001.0)
        assert meter.has_recent_data(1001.0, stale_seconds=15) is True
