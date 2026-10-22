"""Runs the N-PE bonding decision in its own thread every second.

Inverter serial commands take several seconds each, and a battery mode change sends several of them. When the
decision ran at the end of the main cycle, the house sat islanded on the battery with N-PE open for ~26s after
a SUB -> SBU switch. This thread only reads shared state (ZMAi readings, last inverter data) and owns the relay.
"""

import threading
import time

import settings

EVALUATE_INTERVAL_SECONDS = 1
PUBLISH_INTERVAL_SECONDS = 5


class NpeSupervisor:
    """Evaluates and drives the N-PE relay independently of the main loop."""

    def __init__(self, npe_bonding, zmai_meter, inverter, client):
        self._npe_bonding = npe_bonding
        self._zmai_meter = zmai_meter
        self._inverter = inverter
        self._client = client
        self._last_publish_time = None
        self._last_published_bond_state = None
        self._thread = threading.Thread(target=self._run, name="npe-supervisor", daemon=True)

    def start(self):
        self._thread.start()

    def is_alive(self):
        return self._thread.is_alive()

    def _run(self):
        while True:
            self._evaluate(time.time())
            time.sleep(EVALUATE_INTERVAL_SECONDS)

    def _evaluate(self, now):
        zmai_online = self._zmai_meter.has_recent_data(now, settings.ZMAI_STALE_SECONDS)
        grid_power_w = self._zmai_meter.power_w if zmai_online else None
        inverter_data = self._inverter.last_data
        ac_input_voltage_v = inverter_data.get("ac_input_voltage_v") if inverter_data is not None else None
        inverter_online = self._inverter.has_recent_data(now)
        desired_bond_state = self._npe_bonding.decide(
            ac_input_voltage_v, grid_power_w, zmai_online, inverter_online, now)
        self._npe_bonding.apply(desired_bond_state)
        self._publish(now)

    def _publish(self, now):
        bond_state = self._npe_bonding.is_bonded
        state_changed = bond_state != self._last_published_bond_state
        publish_due = self._last_publish_time is None or now - self._last_publish_time >= PUBLISH_INTERVAL_SECONDS
        if not state_changed and not publish_due:
            return
        if state_changed:
            print(f"N-PE {'bonded' if bond_state else 'released'}: {self._npe_bonding.last_reasons}", flush=True)
        self._last_publish_time = now
        self._last_published_bond_state = bond_state
        self._client.publish(f"{settings.BASE_TOPIC}/npe_bonding/state", "ON" if bond_state else "OFF")
        for reason_key, reason_value in self._npe_bonding.last_reasons.items():
            self._client.publish(f"{settings.BASE_TOPIC}/npe_bonding/debug/{reason_key}", reason_value)
        self._client.publish(f"{settings.BASE_TOPIC}/npe_bonding/mode/state", self._npe_bonding.mode)
