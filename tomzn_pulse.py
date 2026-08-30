"""Standalone diagnostic: reads the Tomzn meter pulse output on GPIO17 and prints power.

Kept as a manual tool; the pulse input is not used by solar_monitor (EMI on
GPIO17 made it unreliable).
"""

import sys
import time

from gpiozero import Button

PULSE_GPIO_PIN = 17
IMPULSES_PER_KWH = 1600
# ignore anything faster than 100ms (36kW+ implausible)
MIN_PULSE_INTERVAL_SECONDS = 0.1


class PulsePowerMeter:
    """Derives instantaneous power from the interval between meter pulses."""

    def __init__(self, pin, impulses_per_kwh):
        self._impulses_per_kwh = impulses_per_kwh
        self._last_pulse_time = None
        self._pulse_input = Button(pin, pull_up=True, bounce_time=0.05)
        self._pulse_input.when_released = self._on_pulse

    def _on_pulse(self):
        now = time.time()
        if self._last_pulse_time is not None:
            interval = now - self._last_pulse_time
            if interval > MIN_PULSE_INTERVAL_SECONDS:
                power_w = (3600 * 1000) / (interval * self._impulses_per_kwh)
                print(f"Power: {power_w:.1f} W", flush=True)
        self._last_pulse_time = now


def main():
    meter = PulsePowerMeter(PULSE_GPIO_PIN, IMPULSES_PER_KWH)
    print(f"Listening for pulses on GPIO{PULSE_GPIO_PIN}...", flush=True)
    while True:
        time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
