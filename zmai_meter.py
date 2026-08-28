from pi30 import is_number

ZMAI_TOPIC_PREFIX = "energy-smart-meter-zmai-90"
ZMAI_POWER_TOPIC = f"{ZMAI_TOPIC_PREFIX}/power/get"
ZMAI_VOLTAGE_TOPIC = f"{ZMAI_TOPIC_PREFIX}/voltage/get"
ZMAI_CURRENT_TOPIC = f"{ZMAI_TOPIC_PREFIX}/current/get"
ZMAI_RELAY_TOPIC = f"{ZMAI_TOPIC_PREFIX}/1/get"


class ZmaiMeter:
    """Grid meter fed by MQTT pushes from a ZMAi-90 (OpenBeken + RN8209).

    The meter publishes on its own schedule, so freshness is tracked from message
    arrival rather than from a poll returning.
    """

    def __init__(self):
        self.power_w = None
        self.voltage_v = None
        self.current_a = None
        self.relay_is_on = None
        self._last_update_time = None

    def on_message(self, topic, payload, now):
        if not is_number(payload):
            return
        value = float(payload)
        if topic == ZMAI_POWER_TOPIC:
            self.power_w = value
            self._last_update_time = now
        elif topic == ZMAI_VOLTAGE_TOPIC:
            self.voltage_v = value
        elif topic == ZMAI_CURRENT_TOPIC:
            self.current_a = value
        elif topic == ZMAI_RELAY_TOPIC:
            self.relay_is_on = value != 0

    def has_recent_data(self, now, stale_seconds):
        if self._last_update_time is None:
            return False
        return (now - self._last_update_time) < stale_seconds
